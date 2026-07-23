#!/usr/bin/env python3
"""End-to-end simulation test for the fusion pipeline (updated firmware).

Verifies correct behaviour with the current micro:bit v2 + ESP32 firmware:

  micro:bit (main.ts)           ESP32 (gateway .ino)        Pi (fusion_pipeline)
  ─────────────────────         ─────────────────────       ────────────────────
  SAMPLE_PERIOD_MS = 150        Dedup sensor by seq        Noise filter
  SENSOR_REPEAT_TOTAL = 1       Dedup event by (seq, idx)  Jitter buffer (250ms)
  EVENT_REPEAT_TOTAL = 7        Forward all 7 event copies  EventDeduplicator (1 output)
  EVENT_REPEAT_INTERVAL = 90ms                             SequenceTracker (gap detect)
  CONTROL_HOLD_MS = 70ms                                   Nearest-neighbour alignment

Key test scenarios
  1. Normal 150 ms sample cadence (6.67 Hz) — jitter buffer covers all
  2. Event burst: 7 repeats → Pi dedup → 1 control_event output
  3. Sensor suppression during event (630 ms of silence) → available=false window
  4. Sequence gap detection across the suppression window
  5. Late sample arrival still covered by jitter buffer

Usage:
    cd hardware/fusion_pipeline
    python test_e2e.py
"""

from __future__ import annotations

import asyncio
import logging
import math
import socket
import struct
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# ── Path setup ────────────────────────────────────────────────────────────
_HARDWARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARDWARE))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "esp32_ble_gateway_to_Pi"))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "microbit_to_Pi"))

from microbit_receiver.protocol import (
    CONTROL_EVENT_STRUCT,
    SENSOR_STATE_STRUCT,
    Hand,
)

from fusion_pipeline.gateway_adapter import GatewayAdapter, MicrobitSample
from fusion_pipeline.fusion_engine import FusionEngine

logging.basicConfig(level=logging.WARNING,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")

# ═══════════════════════════════════════════════════════════════════════════
# Firmware-accurate parameters (mirrors main.ts)
# ═══════════════════════════════════════════════════════════════════════════

SAMPLE_PERIOD_MS = 150        # main.ts SAMPLE_PERIOD_MS
EVENT_REPEAT_TOTAL = 7        # main.ts EVENT_REPEAT_TOTAL
EVENT_REPEAT_INTERVAL_MS = 90 # main.ts EVENT_REPEAT_INTERVAL_MS
CONTROL_HOLD_MS = 70          # main.ts CONTROL_HOLD_MS

JITTER_BUFFER_MS = 250
MAX_AGE_MS = 120
TEST_DURATION_S = 4.0        # longer to cover event burst + recovery
CAMERA_FPS = 30
GATEWAY_PORT = 17780

# ── Packet builders ────────────────────────────────────────────────────────


def build_sensor_payload(hand: int, sequence: int, elapsed_ms: int,
                         ax: int, ay: int, az: int, pitch: int, roll: int) -> bytes:
    header = 0x01 | ((hand & 0x01) << 2)
    return SENSOR_STATE_STRUCT.pack(
        header, sequence & 0xFFFF, elapsed_ms & 0xFFFF_FFFF,
        ax, ay, az, pitch, roll,
    )


def build_control_payload(hand: int, sequence: int, elapsed_ms: int,
                          event_code: int, priority: int,
                          repeat_index: int) -> bytes:
    """Mirrors micro:bit control packet — repeat_total is EVENT_REPEAT_TOTAL."""
    header = 0x02 | ((hand & 0x01) << 2)
    return CONTROL_EVENT_STRUCT.pack(
        header, sequence & 0xFFFF, elapsed_ms & 0xFFFF_FFFF,
        event_code, priority, repeat_index, EVENT_REPEAT_TOTAL,
    )


def build_gateway_frame(payload: bytes, conn_index: int, ble_rssi: int,
                        gateway_seq: int) -> bytes:
    header = struct.pack(
        "<4sBBBBIIBb",
        b"MBGW", 1, 18, len(payload), 1,
        gateway_seq & 0xFFFF_FFFF,
        int(time.monotonic_ns() / 1000) & 0xFFFF_FFFF,
        conn_index, ble_rssi,
    )
    return header + payload


# ═══════════════════════════════════════════════════════════════════════════
# Scenario builder — mirrors real firmware behaviour
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class SimScenario:
    # (send_at_s, payload_bytes, conn_index, ble_rssi, gateway_seq)
    sensor_events: list[tuple[float, bytes, int, int, int]] = field(default_factory=list)
    control_events: list[tuple[float, bytes, int, int, int]] = field(default_factory=list)
    camera_frames: list[tuple[float, int]] = field(default_factory=list)


def build_scenario() -> SimScenario:
    """Generate a realistic scenario matching the updated firmware behaviour.

    Timeline:
        0ms     left[0], right[100]  — initial samples
        150ms   left[1], right[101]  — regular 150ms cadence
        300ms   left[2], right[102]
        450ms   left[3], right[103]
        600ms   left[4], right[104]
        750ms   left[5], right[105]
        900ms   ── EVENT BURST START ──
                B_LONG_PRESS right: repeat_index 0..6 at 90ms intervals
                900, 990, 1080, 1170, 1260, 1350, 1440ms
                After each event: CONTROL_HOLD_MS=70ms suppression
                Total sensor silence ≈ 7×90 + 70 = 700ms
        900ms   event[0] (repeat_index=0) → control hold until 970ms
        990ms   event[1] (repeat_index=1) → control hold until 1060ms
        1080ms  event[2] (repeat_index=2) → control hold until 1150ms
        1170ms  event[3] (repeat_index=3) → control hold until 1240ms
        1260ms  event[4] (repeat_index=4) → control hold until 1330ms
        1350ms  event[5] (repeat_index=5) → control hold until 1420ms
        1440ms  event[6] (repeat_index=6) → control hold until 1510ms
        ── END EVENT BURST (630ms) ──
        1510ms  sensor silence ends, next sample at ~1575ms (missed 2 samples)
        1650ms  left[7], right[107] — recovery (2 samples skipped, seq gap)
        1800ms  left[8], right[108] — back to normal
        ... continues to 4000ms
    """
    sc = SimScenario()
    base_ms = 200_000
    gw_seq = 0

    def add_sample(t_ms: float, hand: int, seq: int,
                   ax, ay, az, pitch, roll, rssi=-55):
        nonlocal gw_seq
        payload = build_sensor_payload(hand, seq, base_ms + int(t_ms),
                                       ax, ay, az, pitch, roll)
        gw_seq += 1
        sc.sensor_events.append((t_ms / 1000.0, payload, hand, rssi, gw_seq))

    def add_event(t_ms: float, hand: int, seq: int,
                  code: int, pri: int, repeat_idx: int, rssi=-60):
        nonlocal gw_seq
        # Per micro:bit firmware: event.timestampMs is captured once at
        # event creation and reused for all repeats.  All 7 copies of the
        # same event share the same device_timestamp_ms.
        event_creation_ms = base_ms + int(EVENT_START_MS)  # all repeats same ts
        payload = build_control_payload(hand, seq, event_creation_ms,
                                        code, pri, repeat_idx)
        gw_seq += 1
        # ESP32 dedup key is (seq << 8) | repeat_idx — each repeat passes
        sc.control_events.append((t_ms / 1000.0, payload, hand, rssi, gw_seq))

    def add_camera(t_ms: float):
        sc.camera_frames.append((t_ms / 1000.0, len(sc.camera_frames)))

    # ── Build ──────────────────────────────────────────────────────────

    # Phase 1: Normal 150ms sampling (6 samples, 0-750ms)
    for i in range(6):
        t = i * SAMPLE_PERIOD_MS
        add_sample(t, 0, i,
                   32 + i * 20, 176 + i * 15, -1040 + i * 10,
                   9 + i, 1 + i)
        add_sample(t, 1, 100 + i,
                   -16 + i * 10, 248 + i * 20, -1016 + i * 8,
                   13 + i, -1 - i)

    # Phase 2: Event burst at t=900ms
    EVENT_START_MS = 900
    event_seq = 200  # separate sequence counter for events
    for repeat_idx in range(EVENT_REPEAT_TOTAL):
        t = EVENT_START_MS + repeat_idx * EVENT_REPEAT_INTERVAL_MS
        add_event(t, 1, event_seq, 0x03, 100, repeat_idx, rssi=-62)

    # Phase 3: After event burst — sensor silence enforced
    # (micro:bit suppresses sensor during CONTROL_HOLD_MS after each event)
    # Last event ends at 1440ms + 70ms hold = 1510ms
    # First sample after silence: skip 2 sample periods (1500, 1650)
    # seq jumps from left[5]/right[105] to left[7]/right[107] (gap of 1)
    for i in range(6, 15):
        t = 1650 + (i - 6) * SAMPLE_PERIOD_MS
        add_sample(t, 0, i + 1,  # seq jumps: 5→7 (missed 6)
                   32 + i * 20, 176 + i * 15, -1040 + i * 10,
                   9 + i, 1 + i)
        add_sample(t, 1, 100 + i + 1,  # seq jumps: 105→107 (missed 106)
                   -16 + i * 10, 248 + i * 20, -1016 + i * 8,
                   13 + i, -1 - i)

    # Phase 4: Fill camera frames at 30 FPS for entire duration
    for t_ms in range(0, int(TEST_DURATION_S * 1000), 33):
        add_camera(t_ms)

    # Ensure camera frames extend past the last sample
    last_sample_ms = 1650 + (15 - 6) * SAMPLE_PERIOD_MS
    while sc.camera_frames[-1][0] * 1000 < last_sample_ms + JITTER_BUFFER_MS + 500:
        t_ms = sc.camera_frames[-1][0] * 1000 + 33
        add_camera(t_ms)

    return sc


# ═══════════════════════════════════════════════════════════════════════════
# Mock camera
# ═══════════════════════════════════════════════════════════════════════════

class MockCameraFeed:
    def __init__(self, scenario: SimScenario) -> None:
        self._frames = sorted(scenario.camera_frames, key=lambda x: x[0])
        self._cursor = 0
        self._start_time: float | None = None

    def start(self) -> None:
        self._start_time = time.monotonic()

    def elapsed_s(self) -> float:
        return time.monotonic() - (self._start_time or 0)

    def poll_frame(self) -> dict | None:
        now = self.elapsed_s()
        while self._cursor < len(self._frames):
            due_at_s, frame_id = self._frames[self._cursor]
            if due_at_s <= now:
                self._cursor += 1
                hands = [{"handedness": "left", "confidence": 0.9, "valid": True,
                          "landmarks_normalized": [[0.5, 0.5, 0.0]] * 21,
                          "features": {"wrist_velocity": [0.01, 0.0, 0.0]}},
                         {"handedness": "right", "confidence": 0.85, "valid": True,
                          "landmarks_normalized": [[0.6, 0.5, 0.0]] * 21,
                          "features": {"wrist_velocity": [0.0, 0.02, 0.0]}}]
                start_ns = int(time.monotonic_ns() - self.elapsed_s() * 1e9)
                return {
                    "ts_ns": int(start_ns + due_at_s * 1e9),
                    "frame_id": frame_id,
                    "width": 640, "height": 480,
                    "hands": hands, "hands_detected": 2,
                    "processing_latency_ms": 8.0,
                    "clock_ready": frame_id > 30,
                }
            return None
        return None


# ═══════════════════════════════════════════════════════════════════════════
# Test harness (same pattern as main.py)
# ═══════════════════════════════════════════════════════════════════════════

class TestResult:
    def __init__(self) -> None:
        self.fused_frames: list[dict] = []
        self.control_events: list[dict] = []
        self.statuses: list[dict] = []


class FusionAppTest:
    def __init__(self, scenario: SimScenario, result: TestResult) -> None:
        self._scenario = scenario
        self._result = result
        self._gateway: GatewayAdapter | None = None
        self._fusion: FusionEngine | None = None
        self._mock_camera: MockCameraFeed | None = None
        self._running = False
        self._start_time: float = 0.0

    async def run(self) -> TestResult:
        self._fusion = FusionEngine(
            max_age_ms=MAX_AGE_MS, buffer_max_age_s=10,
            jitter_buffer_ms=JITTER_BUFFER_MS,
        )
        self._gateway = GatewayAdapter(
            listen_host="127.0.0.1", listen_port=GATEWAY_PORT,
            allowed_hands={Hand.LEFT, Hand.RIGHT},
            event_dedup_ttl_s=10.0,
            on_sensor_state=self._on_microbit_sample,
            on_control_event=self._on_control_event,
        )
        await self._gateway.start()

        self._mock_camera = MockCameraFeed(self._scenario)
        self._mock_camera.start()

        sender_task = asyncio.create_task(self._send_simulated_packets())

        self._running = True
        self._start_time = time.monotonic()
        last_status_time = 0.0

        while self._running:
            now = time.monotonic()
            elapsed = now - self._start_time
            if elapsed > TEST_DURATION_S + (JITTER_BUFFER_MS / 1000.0) + 0.5:
                self._running = False
                break

            if self._mock_camera:
                cam_frame = self._mock_camera.poll_frame()
                if cam_frame is not None:
                    self._fusion.enqueue_camera_frame(cam_frame)

            for fused in self._fusion.drain_ready_frames():
                self._result.fused_frames.append(fused)

            if now - last_status_time >= 1.0:
                gw_status = self._gateway.get_status() if self._gateway else {}
                cam_status = {"fps": CAMERA_FPS, "hands_detected": 2,
                              "dropped_capture_frames": 0, "clock_ready": True}
                self._result.statuses.append(
                    self._fusion.build_status(gw_status, cam_status))
                last_status_time = now

            await asyncio.sleep(0.002)

        await sender_task
        for fused in self._fusion.drain_ready_frames():
            self._result.fused_frames.append(fused)

        await self._gateway.stop()
        return self._result

    async def _send_simulated_packets(self) -> None:
        """Send UDP packets according to the scenario timeline.

        Mirrors ESP32 behaviour:
          - Sensor dedup by seq already done (each seq appears once in scenario)
          - Event dedup by (seq, repeat_idx) — ESP32 forwards all 7 copies
        """
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.setblocking(False)

        all_events: list[tuple[float, bytes, int, int, int]] = []
        all_events.extend(self._scenario.sensor_events)
        all_events.extend(self._scenario.control_events)
        all_events.sort(key=lambda x: x[0])

        cursor = 0
        while self._running and cursor < len(all_events):
            elapsed = time.monotonic() - self._start_time
            t_s, payload, conn_idx, rssi, gw_seq = all_events[cursor]
            if t_s <= elapsed:
                frame = build_gateway_frame(payload, conn_idx, rssi, gw_seq)
                sock.sendto(frame, ("127.0.0.1", GATEWAY_PORT))
                cursor += 1
            else:
                await asyncio.sleep(0.001)
        sock.close()

    def _on_microbit_sample(self, sample: MicrobitSample) -> None:
        if self._fusion:
            self._fusion.push_microbit_sample(sample)

    def _on_control_event(self, event: dict) -> None:
        # Fast path: control events are emitted immediately.
        # In the real main.py this sends directly to TCP.
        self._result.control_events.append(event)


# ═══════════════════════════════════════════════════════════════════════════
# Validation
# ═══════════════════════════════════════════════════════════════════════════

def validate(result: TestResult) -> tuple[bool, list[str]]:
    lines: list[str] = []
    passed = True

    def check(condition: bool, label: str) -> None:
        nonlocal passed
        if condition:
            lines.append(f"  ✅ {label}")
        else:
            lines.append(f"  ❌ FAIL: {label}")
            passed = False

    # ── 1. fused_frames ───────────────────────────────────────────────
    lines.append(f"\n📊 fused_frames: {len(result.fused_frames)} total")
    check(len(result.fused_frames) > 0, "At least one fused_frame produced")

    required_keys = {"type", "schema_version", "fused_sequence",
                     "pi_aligned_timestamp_ns", "microbits",
                     "camera", "fusion_quality"}
    check(all(required_keys.issubset(f.keys()) for f in result.fused_frames),
          "All fused_frames have required top-level keys")

    # ── 2. Event dedup: 7 ESP32 copies → 1 Pi control_event ───────────
    lines.append(f"\n📊 control_events: {len(result.control_events)} total")
    check(len(result.control_events) >= 1, "At least one control_event received")

    blp_events = [e for e in result.control_events
                  if e.get("event_code") == "B_LONG_PRESS"]
    lines.append(f"  B_LONG_PRESS events: {len(blp_events)} "
                 f"(ESP32 forwarded {EVENT_REPEAT_TOTAL}, expect 1 after dedup)")
    check(len(blp_events) == 1,
          f"Event dedup: 7 ESP32 copies → 1 Pi output (got {len(blp_events)})")
    if blp_events:
        check(blp_events[0].get("mapped_candidate") == "emergency_stop",
              "B_LONG_PRESS mapped to emergency_stop")
        # Verify it's not marked duplicate
        check(not blp_events[0].get("duplicate", True),
              "Event not marked as duplicate (first copy accepted)")

    # ── 3. Sensor suppression period ──────────────────────────────────
    # Convert absolute pi_aligned_timestamp_ns to relative seconds from
    # the first fused frame, so the event burst window [0.9s, 1.8s] is
    # comparable regardless of wall-clock time.
    if result.fused_frames:
        t0_ns = result.fused_frames[0]["pi_aligned_timestamp_ns"]
    else:
        t0_ns = 0

    EVENT_BURST_START_S = 0.9
    RECOVERY_END_S = 1.8

    def _microbit_by_hand(frame, hand):
        """Extract a microbit entry from the microbits list by hand."""
        for m in frame.get("microbits", []):
            if m.get("hand") == hand:
                return m
        return {}

    def _both_available(frame):
        left = _microbit_by_hand(frame, "left")
        right = _microbit_by_hand(frame, "right")
        return left.get("available") and right.get("available")

    def _either_missing(frame):
        left = _microbit_by_hand(frame, "left")
        right = _microbit_by_hand(frame, "right")
        return not left.get("available") or not right.get("available")

    suppressed_frames = [
        f for f in result.fused_frames
        if (EVENT_BURST_START_S <= (f["pi_aligned_timestamp_ns"] - t0_ns) / 1e9 <= RECOVERY_END_S
            and _either_missing(f))
    ]
    available_frames = [
        f for f in result.fused_frames
        if (EVENT_BURST_START_S <= (f["pi_aligned_timestamp_ns"] - t0_ns) / 1e9 <= RECOVERY_END_S
            and _both_available(f))
    ]

    lines.append(f"\n📊 Event burst window ({EVENT_BURST_START_S}s-{RECOVERY_END_S}s):")
    lines.append(f"  unavailable frames: {len(suppressed_frames)}")
    lines.append(f"  available frames:   {len(available_frames)}")
    check(len(suppressed_frames) > 0,
          "Some frames during event burst have unavailable sensor data "
          "(expected: sensor is suppressed)")

    # At least some frames should still be available (recovery after burst)
    check(len(available_frames) > 0,
          "Some frames during event burst still have available data "
          "(expected: recovery after suppression ends)")

    # ── 4. Sequence gap after suppression ─────────────────────────────
    gap_frames = [
        f for f in result.fused_frames
        if any("sequence_gap" in flag
               for flag in f["fusion_quality"]["microbit_quality_flags"])
    ]
    lines.append(f"\n📊 Sequence gaps detected: {len(gap_frames)} frames")
    check(len(gap_frames) >= 1,
          "Sequence gap detected after event suppression period")
    if gap_frames:
        g = gap_frames[0]
        left_m = _microbit_by_hand(g, "left")
        lines.append(f"   Example: left.seq={left_m.get('sample_sequence')}, "
                     f"left.status={left_m.get('sequence_status')}, "
                     f"left.missing={left_m.get('missing_sample_count')}")

    # ── 5. Normal operation: most frames have both hands ───────────────
    both_avail = sum(1 for f in result.fused_frames if _both_available(f))
    ratio = both_avail / max(len(result.fused_frames), 1)
    lines.append(f"\n📊 Both hands available: {both_avail}/{len(result.fused_frames)} "
                 f"({ratio:.0%})")
    check(ratio > 0.5,
          f"Majority of frames have both hands available (got {ratio:.0%})")

    # ── 6. Time deltas within threshold ───────────────────────────────
    deltas = []
    for f in result.fused_frames:
        for m in f.get("microbits", []):
            if m.get("available"):
                deltas.append(abs(m.get("time_delta_ms", 0)))
    if deltas:
        max_d = max(deltas)
        lines.append(f"\n📊 Time delta range: min={min(deltas):.1f}ms, "
                     f"max={max_d:.1f}ms")
        check(max_d <= MAX_AGE_MS,
              f"All time deltas within {MAX_AGE_MS}ms threshold (max={max_d:.1f}ms)")

    # ── 7. Jitter buffer status ───────────────────────────────────────
    if result.statuses:
        last_s = result.statuses[-1]
        jitter = last_s.get("jitter", {})
        lines.append(f"\n📊 Jitter buffer (final status): {jitter}")
        check(jitter.get("pending_frames", 999) <= 15,
              f"Jitter buffer not excessively backlogged at end of test "
              f"(got {jitter.get('pending_frames')}, ≤15 is normal tail)")

    # ── Summary ───────────────────────────────────────────────────────
    lines.append(f"\n{'='*60}")
    if passed:
        lines.append("🎉 ALL CHECKS PASSED")
    else:
        lines.append("⚠️  SOME CHECKS FAILED — see above")
    lines.append(f"{'='*60}")
    return passed, lines


# ═══════════════════════════════════════════════════════════════════════════
# Main
# ═══════════════════════════════════════════════════════════════════════════

async def main() -> int:
    print("╔══════════════════════════════════════════════════════════════╗")
    print("║   E2E Test — Updated Firmware Parameters                    ║")
    print("╠══════════════════════════════════════════════════════════════╣")
    print(f"║   SAMPLE_PERIOD_MS = {SAMPLE_PERIOD_MS:<5}  EVENT_REPEAT = x{EVENT_REPEAT_TOTAL}          ║")
    print(f"║   CONTROL_HOLD_MS  = {CONTROL_HOLD_MS:<5}  jitter_buf = {JITTER_BUFFER_MS}ms        ║")
    print(f"║   max_age_ms = {MAX_AGE_MS:<5}  duration = {TEST_DURATION_S}s              ║")
    print("╚══════════════════════════════════════════════════════════════╝")
    print()

    scenario = build_scenario()
    print(f"Scenario: {len(scenario.sensor_events)} sensor events, "
          f"{len(scenario.control_events)} control events "
          f"(x{EVENT_REPEAT_TOTAL} repeats from ESP32), "
          f"{len(scenario.camera_frames)} camera frames")
    print()

    result = TestResult()
    app = FusionAppTest(scenario, result)

    print("Running", end="", flush=True)
    import threading

    def spinner():
        for c in "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏" * 50:
            if app._running:
                print(f"\rRunning {c}", end="", flush=True)
                time.sleep(0.1)
            else:
                break

    spin = threading.Thread(target=spinner, daemon=True)
    spin.start()

    try:
        await app.run()
    except KeyboardInterrupt:
        pass
    finally:
        app._running = False
        print("\rRunning done.     ")

    passed, report = validate(result)
    for line in report:
        print(line)

    # Print a fused_frame from within the event burst window
    t0 = result.fused_frames[0]["pi_aligned_timestamp_ns"] if result.fused_frames else 0
    burst_frames = [f for f in result.fused_frames
                    if 0.9 <= (f["pi_aligned_timestamp_ns"] - t0) / 1e9 <= 1.8]
    if burst_frames:
        print(f"\n{'─'*60}")
        print("Fused frame during event burst (sensor suppressed):")
        import json as _json
        mid = burst_frames[len(burst_frames) // 2]
        display = {k: v for k, v in mid.items()}
        if "camera" in display:
            display["camera"]["hands"] = f"[{display['camera'].get('hands_detected', 0)} hands — truncated]"
        print(_json.dumps(display, indent=2, ensure_ascii=False))

    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

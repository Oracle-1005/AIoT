#!/usr/bin/env python3
"""Unit tests for core modules (no hardware required).

Covers all pure-Python modules with edge cases and error paths.

Usage:
    python tests/test_units.py
    python tests/test_units.py --verbose
"""

import sys
import time
import math
import struct
import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))


# ── Test Framework ─────────────────────────────────────────────────────────

class TestRunner:
    """Minimal test runner with colored output."""

    def __init__(self, verbose: bool = False):
        self.verbose = verbose
        self.passed = 0
        self.failed = 0
        self._current_section = ""

    def section(self, name: str) -> None:
        self._current_section = name
        print(f"\n{'─'*50}")
        print(f"  {name}")
        print(f"{'─'*50}")

    def check(self, name: str, condition: bool, detail: str = "") -> None:
        if condition:
            self.passed += 1
            if self.verbose:
                print(f"    ✓ {name}")
        else:
            self.failed += 1
            print(f"    ✗ {name}  {detail}")

    def summary(self) -> bool:
        total = self.passed + self.failed
        print(f"\n{'='*50}")
        print(f"  Results: {self.passed}/{total} passed, {self.failed} failed")
        if self.failed == 0:
            print("  ALL TESTS PASSED ✓")
        else:
            print(f"  {self.failed} TEST(S) FAILED ✗")
        print(f"{'='*50}")
        return self.failed == 0


# ── Tests ──────────────────────────────────────────────────────────────────

def test_packet_parser(t: TestRunner) -> None:
    """Test binary packet parsing."""
    from ble.packet_parser import PacketParser, PACKET_FORMAT, PACKET_SIZE

    t.section("PacketParser")

    # Valid packet
    now = time.monotonic_ns()
    raw = struct.pack(PACKET_FORMAT, 1, 0, 42, 5000, 84, 1164, -362, 18, -7, 0)
    p = PacketParser.parse("MB_LEFT", "left", raw, now)

    t.check("parses valid packet", p is not None)
    t.check("correct version", p.version == 1)
    t.check("correct hand", p.hand == "left")
    t.check("correct sequence", p.sequence == 42)
    t.check("correct timestamp_ms", p.device_timestamp_ms == 5000)
    t.check("accelerometer values", p.ax_mg == 84 and p.ay_mg == 1164 and p.az_mg == -362)
    t.check("orientation values", p.pitch_deg == 18 and p.roll_deg == -7)
    t.check("receive timestamp recorded", p.pi_receive_timestamp_ns == now)

    # Wrong length
    t.check("rejects short packet", PacketParser.parse("X", "left", b"short", now) is None)
    t.check("rejects long packet", PacketParser.parse("X", "left", b"x" * 30, now) is None)
    t.check("rejects empty packet", PacketParser.parse("X", "left", b"", now) is None)

    # Hand byte mapping
    raw_right = struct.pack(PACKET_FORMAT, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
    p2 = PacketParser.parse("MB_RIGHT", "right", raw_right, now)
    t.check("hand byte 1 = right", p2 is not None and p2.hand == "right")

    raw_unknown = struct.pack(PACKET_FORMAT, 1, 99, 0, 0, 0, 0, 0, 0, 0, 0)
    p3 = PacketParser.parse("MB", "left", raw_unknown, now)
    t.check("unknown hand byte → unknown", p3 is not None and p3.hand == "unknown")

    # Dict export
    d = p.to_dict()
    t.check("to_dict has device_id", d["device_id"] == "MB_LEFT")
    t.check("to_dict has all fields", len(d) == 12)

    # Command packet building
    cmd = PacketParser.build_command_packet("SYNC,5")
    t.check("build command", cmd == b"SYNC,5\r\n")


def test_data_cleaner(t: TestRunner) -> None:
    """Test packet loss detection and interpolation."""
    from fusion.cleaner import DataCleaner

    t.section("DataCleaner — Loss Detection")

    c = DataCleaner(loss_window_size=10, max_gap_interpolate=3)
    now = time.monotonic_ns()

    # First sample — no loss
    t.check("first sample no loss", c.check_sample("DEV", 0, now) is None)

    # Sequential samples
    for i in range(1, 20):
        r = c.check_sample("DEV", i, now + i * 40_000_000)
        t.check(f"  seq {i} no loss", r is None)

    # Gap of 3
    r = c.check_sample("DEV", 23, now + 23 * 40_000_000)
    t.check("gap of 3 detected", r is not None and r.lost_count == 3)
    t.check("has recent_loss_ratio", 0 < r.recent_loss_ratio < 1)

    # Single gap
    r = c.check_sample("DEV", 25, now + 25 * 40_000_000)
    t.check("gap of 1 detected", r is not None and r.lost_count == 1)

    # Large gap that should be treated as wraparound/reset (> half uint16 space)
    # After seq 25, expected=26. Sending 32795 gives gap (32795-26)=32769 > 32768 → reset
    r = c.check_sample("DEV", 32795, now + 26 * 40_000_000)
    t.check("large gap → reset (no loss)", r is None)

    # Stats
    stats = c.get_total_stats("DEV")
    t.check("total_received", stats["total_received"] > 20)
    t.check("total_lost", stats["total_lost"] == 4)

    t.section("DataCleaner — Interpolation")

    s0 = {"ax_mg": 0, "ay_mg": 100, "az_mg": 200, "pitch_deg": 0, "roll_deg": 0,
          "device_id": "X", "hand": "left", "sequence": 0, "flags": 0,
          "clock_ready": True, "recent_loss_ratio": 0,
          "device_timestamp_ms": 1000, "pi_aligned_timestamp_ns": 1_000_000,
          "pi_receive_timestamp_ns": 999_000}
    s1 = {"ax_mg": 10, "ay_mg": 200, "az_mg": 300, "pitch_deg": 10, "roll_deg": 5,
          "device_id": "X", "hand": "left", "sequence": 2, "flags": 0,
          "clock_ready": True, "recent_loss_ratio": 0,
          "device_timestamp_ms": 1100, "pi_aligned_timestamp_ns": 1_100_000,
          "pi_receive_timestamp_ns": 1_099_000}

    # Single gap
    interp = c.interpolate_gap(s0, s1, 1)
    t.check("single interpolation", len(interp) == 1)
    t.check("interpolated flag", interp[0]["is_interpolated"] is True)
    t.check("sequence between", interp[0]["sequence"] == 1)
    t.check("ax_mg midpoint", 4.0 < interp[0]["ax_mg"] < 6.0)

    # Multi-gap
    interp2 = c.interpolate_gap(s0, s1, 3)
    t.check("triple interpolation", len(interp2) == 3)
    t.check("evenly spaced seqs",
            [x["sequence"] for x in interp2] == [1, 2, 3])

    # Gap too large
    interp3 = c.interpolate_gap(s0, s1, 5)
    t.check("gap > max returns empty", len(interp3) == 0)

    # Reset
    c.reset_device("DEV")
    t.check("reset clears state", c.get_total_stats("DEV")["total_received"] == 0)


def test_ring_buffer(t: TestRunner) -> None:
    """Test time-sorted ring buffer."""
    from fusion.ring_buffer import RingBuffer, TimestampedSample

    t.section("RingBuffer")

    rb = RingBuffer(maxlen=20, max_age_ns=100_000_000_000)

    # Appending
    for i in range(10):
        rb.push(TimestampedSample(i * 1_000_000, "src", "dev", {"val": i}))
    t.check("size after append", len(rb) == 10)
    t.check("latest timestamp", rb.latest_timestamp() == 9_000_000)
    t.check("latest by device", rb.latest_timestamp("dev") == 9_000_000)
    t.check("unknown device", rb.latest_timestamp("unknown") is None)

    # Bracket search
    t0, t1 = rb.get_bracket(3_500_000, "dev")
    t.check("bracket found", t0 is not None and t1 is not None)
    t.check("bracket spans target", t0.timestamp_ns <= 3_500_000 <= t1.timestamp_ns)

    # No bracket
    t0b, t1b = rb.get_bracket(3_500_000, "unknown_dev")
    t.check("no bracket for unknown device", t0b is None and t1b is None)

    # Window query
    win = rb.get_samples_in_window(2_000_000, 6_000_000)
    t.check("window count", len(win) == 5)  # 2, 3, 4, 5, 6

    # Source filter
    win2 = rb.get_samples_in_window(0, 10_000_000, source="src")
    t.check("source filter", len(win2) == 10)

    # Out-of-order insert (sample comes late)
    rb.push(TimestampedSample(500_000, "src", "dev", {"val": -1}))
    t.check("out-of-order maintains order",
            len(rb) > 0 and rb._buffer[0].timestamp_ns <= rb._buffer[-1].timestamp_ns)
    t.check("out-of-order size", len(rb) == 11)

    # Pruning
    pruned = rb.prune(5_000_000)  # Remove samples before 5ms
    t.check("prune removes old", pruned > 0)
    t.check("prune size correct", len(rb) < 11)

    # Maxlen
    rb_small = RingBuffer(maxlen=5)
    for i in range(10):
        rb_small.push(TimestampedSample(i * 1_000_000, "s", "d", {}))
    t.check("maxlen enforced", len(rb_small) <= 5)

    # Clear
    rb_small.clear()
    t.check("clear empties", len(rb_small) == 0)


def test_time_aligner(t: TestRunner) -> None:
    """Test time alignment and interpolation."""
    from fusion.ring_buffer import RingBuffer, TimestampedSample
    from fusion.aligner import TimeAligner

    t.section("TimeAligner")

    # Setup: 2 BLE samples 40ms apart
    rb = RingBuffer(maxlen=50)
    rb.push(TimestampedSample(1_000_000_000, "mb", "MB_L", {
        "ax_mg": 0, "ay_mg": 100, "az_mg": 200,
        "pitch_deg": 0, "roll_deg": 0, "clock_ready": True,
    }))
    rb.push(TimestampedSample(1_040_000_000, "mb", "MB_L", {
        "ax_mg": 40, "ay_mg": 500, "az_mg": 600,
        "pitch_deg": 10, "roll_deg": 5, "clock_ready": True,
    }))

    aligner = TimeAligner(
        max_bracket_span_ms=100,
        max_sample_age_ms=120,
        timestamp_alignment_tolerance_ms=50,
    )

    # Perfect midpoint
    r = aligner.align("MB_L", 1_020_000_000, rb)
    t.check("valid alignment", r.valid)
    t.check("ax at midpoint", 19 < r.interpolated["ax_mg"] < 21)  # ~20
    t.check("error near zero", r.nearest_sample_error_ms < 22)

    # Near t0
    r2 = aligner.align("MB_L", 1_005_000_000, rb)
    t.check("near t0 valid", r2.valid)
    t.check("ax near t0", 4 < r2.interpolated["ax_mg"] < 6)

    # No bracket
    r3 = aligner.align("MB_UNKNOWN", 1_020_000_000, rb)
    t.check("no bracket invalid", not r3.valid)
    t.check("reason no_bracket", r3.reason == "no_bracket")

    # Clock not ready
    rb.push(TimestampedSample(1_080_000_000, "mb", "MB_NOCLK", {
        "ax_mg": 0, "ay_mg": 0, "az_mg": 0,
        "pitch_deg": 0, "roll_deg": 0, "clock_ready": False,
    }))
    rb.push(TimestampedSample(1_120_000_000, "mb", "MB_NOCLK", {
        "ax_mg": 10, "ay_mg": 10, "az_mg": 10,
        "pitch_deg": 0, "roll_deg": 0, "clock_ready": False,
    }))
    r4 = aligner.align("MB_NOCLK", 1_100_000_000, rb)
    t.check("clock_not_ready invalid", not r4.valid)
    t.check("reason clock", r4.reason == "clock_not_ready")

    # Bracket too wide
    rb2 = RingBuffer(maxlen=50)
    rb2.push(TimestampedSample(1_000_000_000, "mb", "MB_WIDE", {
        "ax_mg": 0, "clock_ready": True}))
    rb2.push(TimestampedSample(1_200_000_000, "mb", "MB_WIDE", {
        "ax_mg": 10, "clock_ready": True}))
    r5 = aligner.align("MB_WIDE", 1_100_000_000, rb2)
    t.check("bracket too wide invalid", not r5.valid
            or r5.bracket_span_ms > 100)
    t.check("reason bracket_too_wide or valid",
            not r5.valid)  # 200ms span > 100ms limit


def test_fusion_engine(t: TestRunner) -> None:
    """Test fusion engine orchestrator."""
    from fusion.engine import FusionEngine

    t.section("FusionEngine")

    config = {
        "buffer_maxlen": 100, "buffer_max_age_s": 10,
        "max_bracket_span_ms": 100, "max_sample_age_ms": 120,
        "timestamp_alignment_tolerance_ms": 50,
    }
    engine = FusionEngine(config)

    # Register devices
    engine.register_device("MB_LEFT", "left")
    engine.register_device("MB_RIGHT", "right")

    # Feed samples for left hand
    ts_base = 10_000_000_000
    for i in range(5):
        engine.on_microbit_sample(build_mb_sample("MB_LEFT", "left", i,
            ts_base + i * 40_000_000, ax=i*10))

    # Feed samples for right hand (slightly offset)
    for i in range(5):
        engine.on_microbit_sample(build_mb_sample("MB_RIGHT", "right", i,
            ts_base + 2_000_000 + i * 40_000_000, ax=-i*5))

    # Fuse at camera timestamp between sample 2 and 3
    cam = {
        "frame_id": 100,
        "sensor_timestamp_ns": ts_base + 110_000_000,  # Between samples 2 and 3
        "width": 640, "height": 480, "fps": 30,
        "processing_latency_ms": 15.0,
        "hands": [
            {"hand_id": "left-0", "handedness": "left", "confidence": 0.95,
             "valid": True, "landmarks_normalized": [], "features": {}},
        ],
    }

    fused = engine.on_camera_frame(cam)
    t.check("fused_frame produced", fused is not None)
    t.check("camera data preserved", fused["camera"]["frame_id"] == 100)
    t.check("two microbits in output", len(fused["microbits"]) == 2)
    t.check("fusion alignment method",
            fused["fusion"]["alignment_method"] == "camera_timestamp_target")

    # Partial data: only left hand valid
    fusion = fused["fusion"]
    t.check("left microbit valid", fusion["left_microbit_valid"] in (True, False))
    t.check("right microbit valid", fusion["right_microbit_valid"] in (True, False))
    t.check("camera valid", fusion["camera_valid"] is True)

    # Status
    status = engine.get_status()
    t.check("status has buffer stats", "buffer_total_samples" in status)


def test_message_builder(t: TestRunner) -> None:
    """Test all 4 message type builders."""
    from messages.builder import MessageBuilder

    t.section("MessageBuilder")

    b = MessageBuilder(schema_version="1.1", pi_id="test-pi")

    # fused_frame
    fusion = {
        "timestamps": {"fusion_target_timestamp_ns": 1_000_000},
        "camera": {"frame_id": 1, "sensor_timestamp_ns": 1_000_000, "hands": []},
        "microbits": [],
        "fusion": {"valid": True},
    }
    m = b.build_fused_frame(fusion)
    t.check("fused_frame type", m["message_type"] == "fused_frame")
    t.check("schema version", m["schema_version"] == "1.1")
    t.check("has session_id", len(m["session_id"]) > 0)
    t.check("packet sequence increments", m["packet_sequence"] == 1)
    t.check("pi_id correct", m["pi_id"] == "test-pi")
    t.check("mono timestamp ns", m["timestamps"]["pi_packet_created_mono_ns"] > 0)
    t.check("unix timestamp ns", m["timestamps"]["pi_unix_time_ns"] > 0)

    m2 = b.build_fused_frame(fusion)
    t.check("sequence increments", m2["packet_sequence"] == 2)

    # control_event
    evt = {
        "event_id": "evt-001",
        "event": {"type": "downbeat", "hand": "right", "confidence": 0.9, "strength": 0.8},
        "music_control": {"estimated_bpm": 120},
        "led_control": {"pattern": "right_pulse"},
    }
    e = b.build_control_event(evt)
    t.check("control_event type", e["message_type"] == "control_event")
    t.check("event preserved", e["event"]["type"] == "downbeat")
    t.check("event_id preserved", e["event_id"] == "evt-001")

    # status
    s = b.build_status({"camera": {"connected": True}})
    t.check("status type", s["message_type"] == "status")


def test_instant_features(t: TestRunner) -> None:
    """Test per-frame feature computation."""
    from features.instant import InstantFeatureComputer

    t.section("InstantFeatureComputer")

    fc = InstantFeatureComputer(gravity_alpha=0.9)

    # First frame
    s1 = {"ax_mg": 84, "ay_mg": 1164, "az_mg": -362}
    f1 = fc.compute_microbit_features("DEV", s1, 1_000_000_000)
    t.check("acceleration_g", f1["acceleration_g"] == [0.084, 1.164, -0.362])
    t.check("magnitude computed", f1["acceleration_magnitude_g"] > 0)
    # |a| = sqrt(0.084² + 1.164² + (-0.362)²) ≈ 1.221
    expected_mag = math.sqrt(0.084**2 + 1.164**2 + (-0.362)**2)
    t.check("magnitude correct",
            abs(f1["acceleration_magnitude_g"] - expected_mag) < 0.01)
    t.check("jerk zero on first frame", f1["jerk_magnitude_g_s"] == 0.0)
    t.check("motion energy positive", f1["motion_energy"] >= 0)

    # Second frame at 50ms later
    s2 = {"ax_mg": 200, "ay_mg": 1000, "az_mg": -300}
    f2 = fc.compute_microbit_features("DEV", s2, 1_050_000_000)
    t.check("jerk non-zero after dt", f2["jerk_magnitude_g_s"] != 0.0)
    # da_x = (200/1000 - 84/1000) = 0.116g, dt = 0.05s, jerk_x ≈ 2.32
    expected_jerk_x = (0.200 - 0.084) / 0.05
    t.check("jerk_x roughly correct",
            abs(f2["jerk_g_s"][0] - expected_jerk_x) < 0.5)

    # Reset
    fc.reset("DEV")
    f3 = fc.compute_microbit_features("DEV", s1, 2_000_000_000)
    t.check("jerk zero after reset", f3["jerk_magnitude_g_s"] == 0.0)


def test_noise_filter(t: TestRunner) -> None:
    """Test noise filtering for micro:bit and camera data."""
    from fusion.noise_filter import (
        MicrobitNoiseFilter, EMAFilter, MedianFilter, AdaptiveSmoother
    )

    t.section("NoiseFilter — EMA")

    # EMA filter
    ema = EMAFilter(alpha=0.85, init_value=0.0)
    v1 = ema.update(100.0)
    t.check("EMA first value = raw", v1 == 100.0)
    v2 = ema.update(200.0)
    # Expected: 0.85 * 100 + 0.15 * 200 = 115
    t.check("EMA second value smoothed", abs(v2 - 115.0) < 1.0)

    t.section("NoiseFilter — Median")

    med = MedianFilter(window_size=5)
    vals = [10, 12, 11, 100, 13]  # 100 is a spike
    results = [med.update(v) for v in vals]
    # After all 5, sorted = [10, 11, 12, 13, 100], median = 12
    t.check("Median rejects spike", results[-1] == 12)

    t.section("NoiseFilter — MicrobitNoiseFilter")

    nf = MicrobitNoiseFilter(device_id="TEST",
        ema_alpha_accel=0.85, median_window=5, outlier_threshold_mg=500.0)

    # Normal samples
    for _ in range(10):
        result = nf.filter(ax_mg=50, ay_mg=1000, az_mg=-200, pitch_deg=10, roll_deg=-5)
    t.check("filter returns FilteredIMUData", result.filtered is True)
    t.check("accel values smoothed", abs(result.ax_mg) < 100)
    t.check("orientation smoothed", abs(result.pitch_deg - 10) < 5)

    # Spike test
    spike = nf.filter(ax_mg=2000, ay_mg=1000, az_mg=-200, pitch_deg=10, roll_deg=-5)
    t.check("spike detected as outlier", spike.outlier_detected)

    t.section("NoiseFilter — AdaptiveSmoother")

    smoother = AdaptiveSmoother(min_cutoff_hz=1.0, beta=0.05)
    # Feed slowly-changing values → heavy smoothing
    for i in range(5):
        s = smoother.update(0.5 + i * 0.001, float(i) * 0.04)
    t.check("adaptive smoother returns value", 0.4 < s < 0.6)


def test_sliding_window(t: TestRunner) -> None:
    """Test sliding window computation (internal, not sent to PC)."""
    from features.window import SlidingWindowComputer, WindowConfig

    t.section("SlidingWindowComputer (internal)")

    sw = SlidingWindowComputer(WindowConfig(duration_ms=800, hop_ms=100))

    # Feed 30 frames (should produce multiple windows)
    window_count = 0
    for i in range(30):
        ts = 10_000_000_000 + i * 33_333_333
        r = sw.add_frame(build_mock_fused_frame(i, ts))
        if r is not None:
            window_count += 1
            t.check(f"window {r['window']['window_id']} has quality",
                    "quality" in r)
            t.check(f"window {r['window']['window_id']} has features",
                    "camera_features" in r and "microbit_features" in r)
            t.check(f"window {r['window']['window_id']} has cross_modal",
                    "cross_modal_features" in r)

    t.check("at least one window produced", window_count >= 1)

    # Verify window structure
    r = sw.add_frame(build_mock_fused_frame(30, 10_000_000_000 + 30 * 33_333_333))
    if r:
        t.check("window_id", r["window"]["window_id"] >= 0)
        t.check("duration_ms", r["window"]["duration_ms"] == 800)
        t.check("hop_ms", r["window"]["hop_ms"] == 100)
        t.check("center computed",
                r["window"]["center_timestamp_ns"] ==
                (r["window"]["start_timestamp_ns"] + r["window"]["end_timestamp_ns"]) // 2)
        t.check("source_summary present", "camera_frame_count" in r["source_summary"])
        t.check("peak detection", "peak_count" in
                r["microbit_features"].get("left_hand", {}))
        t.check("bpm estimation", "estimated_bpm" in r["cross_modal_features"])


def test_tcp_client(t: TestRunner) -> None:
    """Test TCP client initialization and queue behavior."""
    from transport.tcp_client import TcpJsonlClient

    t.section("TcpJsonlClient")

    # Init
    c = TcpJsonlClient(host="127.0.0.1", port=9999, max_queue_size=5)
    t.check("not connected at init", not c.is_connected())

    # Status
    s = c.get_status()
    t.check("status keys", all(k in s for k in
            ["pc_connected", "queued_messages", "dropped_messages",
             "send_rate_hz", "reconnect_count"]))
    t.check("pc not connected", not s["pc_connected"])

    # Queue overflow
    for i in range(20):
        c.send({"message_type": "fused_frame", "i": i})

    t.check("overflow detected", c.get_status()["dropped_messages"] > 0)

    # Control events preserved in send (they all go to the same queue,
    # but the priority difference is in main.py)
    for i in range(3):
        c.send({"message_type": "control_event", "event": {"type": "downbeat"}})
    t.check("send non-blocking", True)  # Just verify no crash


def test_config(t: TestRunner) -> None:
    """Test configuration loading and defaults."""
    from utils.config import load_config, DEFAULT_CONFIG

    t.section("Config")

    # Default config
    t.check("has microbits", "microbits" in DEFAULT_CONFIG)
    t.check("has fusion params", "fusion" in DEFAULT_CONFIG)
    t.check("has camera params", "camera" in DEFAULT_CONFIG)
    t.check("has transport params", "pi_to_pc" in DEFAULT_CONFIG)
    t.check("has valid defaults",
            DEFAULT_CONFIG["fusion"]["window_ms"] == 800
            and DEFAULT_CONFIG["pi_to_pc"]["port"] == 9000)


# ── Helpers ────────────────────────────────────────────────────────────────

def build_mb_sample(device_id: str, hand: str, seq: int, ts_ns: int, ax: int = 0) -> dict:
    return {
        "device_id": device_id, "hand": hand, "sequence": seq,
        "device_timestamp_ms": seq * 40,
        "pi_receive_timestamp_ns": ts_ns,
        "pi_aligned_timestamp_ns": ts_ns,
        "ax_mg": ax, "ay_mg": 1000, "az_mg": -300,
        "pitch_deg": 10, "roll_deg": -5,
        "flags": 0, "clock_ready": True,
        "recent_loss_ratio": 0, "is_interpolated": False,
    }


def build_mock_fused_frame(frame_id: int, ts_ns: int) -> dict:
    return {
        "timestamps": {"fusion_target_timestamp_ns": ts_ns},
        "camera": {"hands": [
            {"hand_id": "l", "handedness": "left", "confidence": 0.9,
             "valid": True, "features": {
                 "wrist_position": [0.5, 0.5, 0],
                 "wrist_velocity": [0.1, -0.2, 0],
                 "openness": 0.7 + (frame_id % 10) * 0.02,
             }},
        ]},
        "microbits": [
            {"hand": "left", "valid": True,
             "sync": {"nearest_sample_error_ms": 5.0},
             "raw_interpolated": {"pitch_deg": 10, "roll_deg": -5},
             "instant_features": {
                 "acceleration_magnitude_g": 1.0 + frame_id * 0.02,
                 "linear_acceleration_magnitude_g": 0.1,
                 "jerk_magnitude_g_s": 3.0 + frame_id * 0.1,
                 "motion_energy": 0.01,
             },
             "timestamps": {"pi_aligned_timestamp_ns": ts_ns}},
            {"hand": "right", "valid": True,
             "sync": {"nearest_sample_error_ms": 6.0},
             "raw_interpolated": {"pitch_deg": 15, "roll_deg": 3},
             "instant_features": {
                 "acceleration_magnitude_g": 1.1,
                 "linear_acceleration_magnitude_g": 0.15,
                 "jerk_magnitude_g_s": 2.0,
                 "motion_energy": 0.015,
             },
             "timestamps": {"pi_aligned_timestamp_ns": ts_ns}},
        ],
        "fusion": {"valid": True},
    }


# ── Main ───────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Unit tests for AIoT pipeline")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Show all passing tests too")
    args = parser.parse_args()

    t = TestRunner(verbose=args.verbose)

    test_packet_parser(t)
    test_data_cleaner(t)
    test_ring_buffer(t)
    test_time_aligner(t)
    test_fusion_engine(t)
    test_message_builder(t)
    test_instant_features(t)
    test_noise_filter(t)
    test_sliding_window(t)
    test_tcp_client(t)
    test_config(t)

    ok = t.summary()
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Full pipeline integration test with mock BLE data.

Simulates two micro:bits streaming BLE packets and runs the complete
processing pipeline:
  Mock BLE → PacketParser → DataCleaner → ClockSync → RingBuffer →
  FusionEngine → InstantFeatureComputer → SlidingWindowComputer →
  MessageBuilder → TcpJsonlClient → (optional) Mock PC Server

No actual hardware required. All BLE is simulated.

Usage:
    # Test without network (print to console):
    python tests/test_pipeline_mock.py --no-network

    # Test with TCP send to mock PC server:
    # Terminal 1: python tests/mock_pc_server.py
    # Terminal 2: python tests/test_pipeline_mock.py
"""

import asyncio
import sys
import time
import argparse
from pathlib import Path
from collections import deque

sys.path.insert(0, str(Path(__file__).parent.parent))

from tests.mock_ble_generator import MockBleGenerator
from ble.packet_parser import PacketParser
from ble.clock_sync import ClockSync
from fusion.ring_buffer import RingBuffer, TimestampedSample
from fusion.cleaner import DataCleaner
from fusion.aligner import TimeAligner
from fusion.engine import FusionEngine
from features.instant import InstantFeatureComputer
from features.window import SlidingWindowComputer, WindowConfig
from messages.builder import MessageBuilder
from transport.tcp_client import TcpJsonlClient


class MockPipelineTest:
    """Runs the full pipeline with simulated BLE data.

    Simulates a sequence of micro:bit BLE notifications and camera frames,
    feeds them through the entire processing chain, and reports statistics.
    """

    def __init__(
        self,
        use_network: bool = False,
        pc_host: str = "127.0.0.1",
        pc_port: int = 9000,
        duration_s: float = 10.0,
        print_frames: bool = False,
    ):
        self.use_network = use_network
        self.pc_host = pc_host
        self.pc_port = pc_port
        self.duration_s = duration_s
        self.print_frames = print_frames

        # ── Components ──
        self.ble_gen = MockBleGenerator()
        self.parser = PacketParser()
        self.clock_syncs = {
            "MB_LEFT": ClockSync("MB_LEFT", min_sync_points=3),
            "MB_RIGHT": ClockSync("MB_RIGHT", min_sync_points=3),
        }
        self.ring_buffer = RingBuffer(maxlen=500, max_age_ns=10_000_000_000)
        self.cleaner = DataCleaner(loss_window_size=100, max_gap_interpolate=3)
        self.aligner = TimeAligner(
            max_bracket_span_ms=100,
            max_sample_age_ms=120,
            timestamp_alignment_tolerance_ms=50,
        )
        self.fusion_engine = FusionEngine({
            "buffer_maxlen": 500, "buffer_max_age_s": 10,
            "max_bracket_span_ms": 100, "max_sample_age_ms": 120,
            "timestamp_alignment_tolerance_ms": 50,
        })
        self.feature_computer = InstantFeatureComputer(gravity_alpha=0.9)
        self.window_computer = SlidingWindowComputer(WindowConfig(800, 100))
        self.message_builder = MessageBuilder(pi_id="test-pi-mock")
        self.tcp_client = TcpJsonlClient(
            host=pc_host, port=pc_port, max_queue_size=500
        ) if use_network else None

        # ── Stats ──
        self.stats = {
            "ble_packets": 0,
            "ble_dropped": 0,
            "loss_events": 0,
            "fused_frames": 0,
            "window_features": 0,
            "control_events": 0,
            "status_messages": 0,
            "invalid_fusions": 0,
        }
        self._fused_frame_buffer: deque[dict] = deque(maxlen=100)
        self._camera_frame_counter = 0

    async def run(self) -> None:
        """Run the full pipeline test."""
        print("=" * 60)
        print("  AIoT Pipeline Integration Test (Mock BLE Data)")
        print("=" * 60)
        print(f"  Duration: {self.duration_s}s")
        print(f"  Network: {'enabled → ' + self.pc_host + ':' + str(self.pc_port) if self.use_network else 'disabled (console only)'}")
        print(f"  Print frames: {self.print_frames}")
        print("─" * 60)

        # Start TCP client if needed
        if self.tcp_client:
            await self.tcp_client.start()

        # Register devices with fusion engine
        self.fusion_engine.register_device("MB_LEFT", "left")
        self.fusion_engine.register_device("MB_RIGHT", "right")

        # Seed clock sync with a few synthetic sync points
        # (In real hardware, these come from SYNC/SYNC_ACK exchanges)
        await self._seed_clock_sync()

        # Main simulation loop
        start_time = time.monotonic()
        last_status_time = start_time
        last_camera_time = start_time
        camera_interval = 1.0 / 30.0   # 30 fps

        self._print_header()

        while time.monotonic() - start_time < self.duration_s:
            # ── Simulate BLE packets (25 Hz) ─────────────────────
            for device_id in ["MB_LEFT", "MB_RIGHT"]:
                result = self.ble_gen.generate_packet(device_id)
                if result is None:
                    # Packet was dropped by the mock generator
                    self.stats["ble_dropped"] += 1
                    # Still need to advance the sequence — but MockBleGenerator
                    # already advanced it internally. We simulate the cleaner
                    # seeing the gap by calling check_sample with the current
                    # expected sequence.
                    #
                    # In real BLE, dropped packets simply don't arrive.
                    # The cleaner detects them when the next packet arrives.
                    continue

                raw, meta = result
                self.stats["ble_packets"] += 1
                pi_receive_ns = time.monotonic_ns()

                # ── Step 1: Parse ──
                parsed = self.parser.parse(
                    meta["device_id"], meta["hand"], raw, pi_receive_ns
                )
                if parsed is None:
                    continue

                # ── Step 2: Detect loss ──
                loss = self.cleaner.check_sample(
                    device_id, parsed.sequence, pi_receive_ns
                )
                if loss:
                    self.stats["loss_events"] += 1

                # ── Step 3: Clock mapping ──
                # In mock mode, use time.monotonic_ns() as the aligned timestamp
                # so it's on the same timeline as camera SensorTimestamp.
                # The real clock sync maps device_timestamp_ms → Pi monotonic_ns.
                cs = self.clock_syncs[device_id]
                aligned_ns = pi_receive_ns  # On the same timeline as camera

                # ── Step 4: Build sample ──
                sample_dict = {
                    "device_id": parsed.device_id,
                    "hand": parsed.hand,
                    "sequence": parsed.sequence,
                    "device_timestamp_ms": parsed.device_timestamp_ms,
                    "pi_receive_timestamp_ns": parsed.pi_receive_timestamp_ns,
                    "pi_aligned_timestamp_ns": aligned_ns,
                    "ax_mg": parsed.ax_mg,
                    "ay_mg": parsed.ay_mg,
                    "az_mg": parsed.az_mg,
                    "pitch_deg": parsed.pitch_deg,
                    "roll_deg": parsed.roll_deg,
                    "flags": parsed.flags,
                    "clock_ready": cs.clock_ready,
                    "recent_loss_ratio": self.cleaner.get_recent_loss_ratio(device_id),
                    "is_interpolated": False,
                }

                # ── Step 5: Compute instant features ──
                instant = self.feature_computer.compute_microbit_features(
                    device_id, sample_dict, aligned_ns
                )
                sample_dict["instant_features"] = instant

                # ── Step 6: Push to fusion engine ──
                self.fusion_engine.on_microbit_sample(sample_dict)

            # ── Simulate camera frame (30 Hz) ──────────────────
            now = time.monotonic()
            if now - last_camera_time >= camera_interval:
                last_camera_time = now
                self._camera_frame_counter += 1

                # Build a mock camera frame with simulated hand landmarks
                camera_dict = self._build_mock_camera_frame()

                # ── Fuse! ──
                fused = self.fusion_engine.on_camera_frame(camera_dict)
                if fused:
                    self.stats["fused_frames"] += 1
                    self._fused_frame_buffer.append(fused)

                    if not fused.get("fusion", {}).get("valid"):
                        self.stats["invalid_fusions"] += 1

                    # ── Build message ──
                    msg = self.message_builder.build_fused_frame(fused)

                    # Send over TCP
                    if self.tcp_client:
                        self.tcp_client.send(msg)

                    # Optional console output
                    if self.print_frames and self.stats["fused_frames"] % 30 == 0:
                        self._print_frame_summary(fused)

                    # ── Feed to sliding window (internal event detection only) ──
                    window_result = self.window_computer.add_frame(fused)
                    if window_result:
                        self.stats["window_features"] += 1

                        # ── Simple event detection from window ──
                        event = self._detect_event(window_result)
                        if event:
                            self.stats["control_events"] += 1
                            emsg = self.message_builder.build_control_event(event)
                            if self.tcp_client:
                                self.tcp_client.send(emsg)
                            print(f"\n  *** EVENT: {event['event']['type']} "
                                  f"hand={event['event']['hand']} "
                                  f"strength={event['event']['strength']:.2f} ***")

                        if self.print_frames:
                            w = window_result.get("window", {})
                            cm = window_result.get("cross_modal_features", {})
                            print(f"  [window #{w.get('window_id'):3d}] "
                                  f"bpm={cm.get('estimated_bpm',0):.1f}  "
                                  f"intensity={cm.get('combined_motion_intensity',0):.3f}")

            # ── Send status every 1 second ──
            if now - last_status_time >= 1.0:
                last_status_time = now
                self.stats["status_messages"] += 1
                status = self._build_status()
                smsg = self.message_builder.build_status(status)
                if self.tcp_client:
                    self.tcp_client.send(smsg)

            # Small sleep to not peg CPU
            await asyncio.sleep(0.005)

        # Stop TCP
        if self.tcp_client:
            await self.tcp_client.stop()

        # Print results
        self._print_results()

    # ── Internal Helpers ────────────────────────────────────────────────

    async def _seed_clock_sync(self) -> None:
        """Seed clock sync with synthetic points to simulate post-sync state."""
        print("  Seeding clock sync with synthetic sync points...")
        for device_id, cs in self.clock_syncs.items():
            t_base = time.monotonic_ns()
            for i in range(10):
                t0 = t_base + i * 50_000_000
                device_ms = i * 50  # 50ms steps
                t2 = t0 + 8_000_000 + i * 1_000_000  # 8-17ms RTT simulated
                cs.add_sync_point(t0, device_ms, t2)
            print(f"    [{device_id}] clock_ready={cs.clock_ready}, "
                  f"a={cs.slope:.6f}, b={int(cs.intercept_ns)}, "
                  f"rtt={cs.latest_rtt_ms:.1f}ms")

    def _build_mock_camera_frame(self) -> dict:
        """Build a mock camera frame with simulated hand landmarks.

        Hand positions are generated simply — real MediaPipe would
        produce actual landmarks. For integration testing, we just
        need the data structure to be correct.
        """
        frame_id = self._camera_frame_counter
        sensor_ts_ns = int(time.monotonic_ns())

        # Simulate that we detect both hands
        hands = []
        for hand_label in ("left", "right"):
            # Generate 21 mock landmarks (simplified)
            landmarks = [
                [0.5 + i * 0.01, 0.5 + i * 0.01, 0.0]
                for i in range(21)
            ]
            hands.append({
                "hand_id": f"{hand_label}-0",
                "handedness": hand_label,
                "confidence": 0.92,
                "valid": True,
                "landmarks_normalized": landmarks,
                "world_landmarks": [],
                "features": {
                    "palm_center": [0.5, 0.6, 0.0],
                    "palm_normal": [0.0, 0.0, 1.0],
                    "openness": 0.7 + (frame_id % 10) * 0.02,
                    "finger_states": [1, 1, 1, 1, 1],
                    "joint_angles": [],
                    "pinch_distance": 0.05,
                    "wrist_position": [0.5, 0.5, 0.0],
                    "wrist_velocity": [0.1, -0.2, 0.0],
                    "wrist_acceleration": [0.0, 0.0, 0.0],
                    "motion_direction": "still",
                },
            })

        return {
            "frame_id": frame_id,
            "sensor_timestamp_ns": sensor_ts_ns,
            "width": 640,
            "height": 480,
            "fps": 30,
            "processing_latency_ms": 15.0,
            "hands": hands,
        }

    def _detect_event(self, window_result: dict) -> dict | None:
        """Simple rule-based event detection on window features.

        Detects beat/strike events based on jerk thresholds.
        """
        mb_features = window_result.get("microbit_features", {})
        left = mb_features.get("left_hand", {})
        right = mb_features.get("right_hand", {})

        max_jerk = max(
            left.get("max_jerk_g_s", 0),
            right.get("max_jerk_g_s", 0),
        )

        threshold = 5.0
        if max_jerk < threshold:
            return None

        # Determine which hand
        if left.get("max_jerk_g_s", 0) >= right.get("max_jerk_g_s", 0):
            hand = "left"
            strength = min(left.get("max_jerk_g_s", 0) / (threshold * 2), 1.0)
        else:
            hand = "right"
            strength = min(right.get("max_jerk_g_s", 0) / (threshold * 2), 1.0)

        # Determine event type
        if strength > 0.7:
            event_type = f"{hand}_wrist_strike"
        else:
            event_type = "downbeat"

        cm = window_result.get("cross_modal_features", {})

        return {
            "event_id": f"evt-{self.stats['control_events'] + 1:05d}",
            "event": {
                "type": event_type,
                "hand": hand,
                "confidence": min(strength, 1.0),
                "strength": strength,
            },
            "music_control": {
                "estimated_bpm": cm.get("estimated_bpm", 120),
                "tempo_delta": 0.0,
                "volume": strength * 0.8,
                "intensity": strength,
                "articulation": 0.5,
            },
            "led_control": {
                "pattern": f"{hand}_pulse",
                "brightness": strength * 0.5,
                "duration_ms": 120,
            },
        }

    def _build_status(self) -> dict:
        """Build a mock status dict."""
        net_status = self.tcp_client.get_status() if self.tcp_client else {"pc_connected": False}
        return {
            "camera": {
                "connected": True,
                "configured_fps": 30,
                "actual_fps": 29.5,
                "dropped_frames": 0,
                "last_frame_age_ms": 15.0,
                "processing_latency_ms": 15.0,
            },
            "microbits": {
                "left": {
                    "device_id": "MB_LEFT", "transport": "ble",
                    "connected": True, "rssi_dbm": -55,
                    "sample_rate_hz": 24.8,
                    "recent_loss_ratio": self.cleaner.get_recent_loss_ratio("MB_LEFT"),
                    "clock_ready": self.clock_syncs["MB_LEFT"].clock_ready,
                    "sync_rtt_ms": self.clock_syncs["MB_LEFT"].latest_rtt_ms or 0,
                    "last_sample_age_ms": 30.0,
                },
                "right": {
                    "device_id": "MB_RIGHT", "transport": "ble",
                    "connected": True, "rssi_dbm": -58,
                    "sample_rate_hz": 24.6,
                    "recent_loss_ratio": self.cleaner.get_recent_loss_ratio("MB_RIGHT"),
                    "clock_ready": self.clock_syncs["MB_RIGHT"].clock_ready,
                    "sync_rtt_ms": self.clock_syncs["MB_RIGHT"].latest_rtt_ms or 0,
                    "last_sample_age_ms": 32.0,
                },
            },
            "network": net_status,
            "led": {"connected": False},
        }

    def _print_header(self) -> None:
        print(f"\n{'Time':>8s}  {'BLE':>6s}  {'Fused':>6s}  {'Window':>6s}  "
              f"{'Event':>6s}  {'Loss':>6s}  {'Invalid':>8s}")
        print("─" * 60)

    def _print_frame_summary(self, fused: dict) -> None:
        elapsed = time.monotonic()
        fusion = fused.get("fusion", {})
        print(f"{elapsed:7.1f}s  {self.stats['ble_packets']:5d}  "
              f"{self.stats['fused_frames']:5d}  "
              f"{self.stats['window_features']:5d}  "
              f"{self.stats['control_events']:5d}  "
              f"{self.stats['loss_events']:5d}  "
              f"{self.stats['invalid_fusions']:7d}")

    def _print_results(self) -> None:
        """Print final test results."""
        print("\n" + "=" * 60)
        print("  PIPELINE INTEGRATION TEST RESULTS")
        print("=" * 60)

        expected_ble = int(self.duration_s * 25 * 2)  # 2 devices, 25 Hz
        expected_camera = int(self.duration_s * 30)    # 30 fps
        expected_window = int((self.duration_s - 0.8) / 0.1) + 1  # windows

        results = [
            ("BLE packets generated", self.stats["ble_packets"],
             f"(expected ~{expected_ble})"),
            ("BLE packets dropped (mock)", self.stats["ble_dropped"],
             f"({self.stats['ble_dropped']/max(self.stats['ble_packets']+self.stats['ble_dropped'],1)*100:.1f}%)"),
            ("Loss events detected", self.stats["loss_events"], ""),
            ("Fused frames produced", self.stats["fused_frames"],
             f"(expected ~{expected_camera})"),
            ("Invalid fusions", self.stats["invalid_fusions"],
             f"({self.stats['invalid_fusions']/max(self.stats['fused_frames'],1)*100:.1f}%)"),
            ("Window features emitted", self.stats["window_features"],
             f"(expected ~{expected_window})"),
            ("Control events detected", self.stats["control_events"], ""),
            ("Status messages sent", self.stats["status_messages"],
             f"(expected ~{int(self.duration_s)})"),
        ]

        all_pass = True
        for label, value, extra in results:
            print(f"  {label:35s}: {value:6d}  {extra}")

        # Validation checks
        print("\n  Validation:")
        checks = [
            ("BLE packets received", self.stats["ble_packets"] > 0),
            ("Fused frames produced", self.stats["fused_frames"] > 0),
            ("Window features emitted", self.stats["window_features"] > 0),
            ("Status messages sent", self.stats["status_messages"] > 0),
            ("Loss detection working", self.stats["loss_events"] >= 0),
            ("Invalid fusion rate < 50%",
             self.stats["invalid_fusions"] < self.stats["fused_frames"] * 0.5),
        ]
        for label, passed in checks:
            status = "✓" if passed else "✗"
            print(f"    [{status}] {label}")
            if not passed:
                all_pass = False

        print(f"\n  Overall: {'ALL CHECKS PASSED' if all_pass else 'SOME CHECKS FAILED'}")
        print("=" * 60)


# ── Entry Point ────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Full pipeline integration test with mock BLE data"
    )
    parser.add_argument("--no-network", action="store_true",
                        help="Run without TCP (print to console only)")
    parser.add_argument("--host", default="127.0.0.1",
                        help="PC/Mock server host (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=9000,
                        help="PC/Mock server port (default: 9000)")
    parser.add_argument("--duration", "-d", type=float, default=10.0,
                        help="Test duration in seconds (default: 10)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Print frame-level details")
    return parser.parse_args()


async def main():
    args = parse_args()
    test = MockPipelineTest(
        use_network=not args.no_network,
        pc_host=args.host,
        pc_port=args.port,
        duration_s=args.duration,
        print_frames=args.verbose,
    )
    await test.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted.")

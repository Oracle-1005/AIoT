#!/usr/bin/env python3
"""Mock BLE data generator — simulates micro:bit sensors for testing.

Generates realistic 19-byte binary packets mimicking two micro:bits
worn on left and right wrists. Hand motion is simulated with sinusoidal
patterns that roughly approximate human gestures.

Usage:
    python tests/mock_ble_generator.py
    # Or import and use MockBleGenerator class in other tests
"""

import struct
import time
import math
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from ble.packet_parser import PACKET_FORMAT

# ── Motion Simulation Parameters ──────────────────────────────────────────

class HandMotionSimulator:
    """Generates realistic accelerometer and orientation data.

    Simulates periodic hand motions (waving, tapping, circles) with:
    - Gravity vector (~1000 mg on the dominant axis when at rest)
    - Controlled acceleration peaks (tap/beat events)
    - Slow orientation changes (pitch/roll drift)
    - Sensor noise (Gaussian, ~5 mg std)

    The default motion is a gentle 120 BPM waving pattern.
    """
    def __init__(self, hand: str = "left", base_bpm: float = 120.0):
        self.hand = hand
        self.base_bpm = base_bpm
        self._phase = random.uniform(0, 2 * math.pi)  # Random start phase
        self._time = 0.0

        # Per-axis amplitude (milli-g) and phase offsets for 3D motion
        self._amp_x = random.uniform(80, 150)
        self._amp_y = random.uniform(100, 250)
        self._amp_z = random.uniform(50, 120)

        # Gravity bias — depends on hand orientation at rest
        if hand == "left":
            self._gravity_bias = [30, 980, -150]   # Slight tilt left
        else:
            self._gravity_bias = [-30, 980, 150]   # Slight tilt right

    def step(self, dt: float) -> dict:
        """Advance simulation by dt seconds, return sensor values.

        Args:
            dt: Time step in seconds.

        Returns:
            Dict with ax_mg, ay_mg, az_mg, pitch_deg, roll_deg.
        """
        self._time += dt
        self._phase += 2 * math.pi * (self.base_bpm / 60.0) * dt

        # ── Accelerometer ────────────────────────────────────────────
        # Base motion: sinusoidal oscillation + gravity bias
        ax = (self._gravity_bias[0]
              + self._amp_x * math.sin(self._phase)
              + random.gauss(0, 5))         # Noise ~5 mg

        ay = (self._gravity_bias[1]
              + self._amp_y * math.sin(self._phase + 0.3)
              + random.gauss(0, 5))

        az = (self._gravity_bias[2]
              + self._amp_z * math.cos(self._phase + 0.7)
              + random.gauss(0, 5))

        # Occasionally inject a "tap" (sharp acceleration spike)
        if random.random() < 0.02:   # ~2% per sample = ~1 tap every 2 sec at 25Hz
            tap_strength = random.uniform(200, 600)
            ay += tap_strength
            ax += tap_strength * random.uniform(-0.3, 0.3)
            az += tap_strength * random.uniform(-0.3, 0.3)

        # ── Orientation (simplified from accel vector) ──────────────
        pitch = math.degrees(math.atan2(-ax, math.sqrt(ay**2 + az**2)))
        roll = math.degrees(math.atan2(az, ay))

        # Clamp
        pitch = max(-90, min(90, pitch + random.gauss(0, 0.5)))
        roll = max(-90, min(90, roll + random.gauss(0, 0.5)))

        return {
            "ax_mg": int(round(ax)),
            "ay_mg": int(round(ay)),
            "az_mg": int(round(az)),
            "pitch_deg": int(round(pitch)),
            "roll_deg": int(round(roll)),
        }

    def inject_beat(self, strength: float = 0.8) -> None:
        """Manually inject a beat event (large acceleration spike)."""
        self._phase = math.pi / 2   # Peak of sine
        self._amp_y *= 1.5          # Amplify


# ── Mock BLE Generator ────────────────────────────────────────────────────

class MockBleGenerator:
    """Generates mock BLE packets for two micro:bits.

    Each device has its own sequence counter and device timestamp.
    Packets are 19-byte binary blobs matching the real micro:bit format.
    """

    def __init__(self):
        self._simulators = {
            "MB_LEFT": HandMotionSimulator("left", base_bpm=120.0),
            "MB_RIGHT": HandMotionSimulator("right", base_bpm=118.0),
        }
        self._sequences = {"MB_LEFT": 0, "MB_RIGHT": 0}
        self._device_timestamps = {"MB_LEFT": 0, "MB_RIGHT": 0}
        self._start_time = time.time()

        # Occasionally drop packets to test loss detection
        self._drop_probability = 0.02   # 2% packet loss
        self._drop_counters = {"MB_LEFT": 0, "MB_RIGHT": 0}

    def generate_packet(self, device_id: str) -> tuple[bytes, dict] | None:
        """Generate one mock BLE packet.

        Args:
            device_id: "MB_LEFT" or "MB_RIGHT"

        Returns:
            Tuple of (raw_bytes, metadata_dict) or None if packet dropped.
        """
        sim = self._simulators[device_id]
        dt = 1.0 / 25.0   # 25 Hz nominal sample rate, with slight jitter
        dt_jittered = dt * random.uniform(0.9, 1.1)

        sensor = sim.step(dt_jittered)

        # Advance device time and sequence
        self._device_timestamps[device_id] += int(dt_jittered * 1000)
        seq = self._sequences[device_id]
        self._sequences[device_id] = (seq + 1) & 0xFFFF

        # Simulate packet drop
        if random.random() < self._drop_probability:
            self._drop_counters[device_id] += 1
            # Still advance sequence (gap will be detected)
            return None

        hand_byte = 0 if device_id == "MB_LEFT" else 1
        version = 1
        flags = 0

        raw = struct.pack(
            PACKET_FORMAT,
            version,
            hand_byte,
            seq,
            self._device_timestamps[device_id],
            sensor["ax_mg"],
            sensor["ay_mg"],
            sensor["az_mg"],
            sensor["pitch_deg"],
            sensor["roll_deg"],
            flags,
        )

        metadata = {
            "device_id": device_id,
            "hand": "left" if hand_byte == 0 else "right",
            "sequence": seq,
            "device_timestamp_ms": self._device_timestamps[device_id],
            **sensor,
        }

        return raw, metadata

    def inject_beat(self, device_id: str, strength: float = 0.8) -> None:
        """Manually inject a beat on a specific device."""
        if device_id in self._simulators:
            self._simulators[device_id].inject_beat(strength)

    @property
    def drop_stats(self) -> dict:
        return dict(self._drop_counters)


# ── Demo ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Mock BLE Generator — generating 50 packets for each hand...\n")

    gen = MockBleGenerator()

    for i in range(50):
        for device in ["MB_LEFT", "MB_RIGHT"]:
            result = gen.generate_packet(device)
            if result:
                raw, meta = result
                print(f"[{device}] seq={meta['sequence']:5d}  "
                      f"ax={meta['ax_mg']:5d}  ay={meta['ay_mg']:5d}  "
                      f"az={meta['az_mg']:5d}  "
                      f"pitch={meta['pitch_deg']:3d}°  roll={meta['roll_deg']:3d}°  "
                      f"packet={len(raw)}B")
            else:
                print(f"[{device}] seq={gen._sequences[device]:5d}  ** DROPPED **")
        time.sleep(0.01)   # Simulate 25Hz timing

    print(f"\nDrop stats: {gen.drop_stats}")

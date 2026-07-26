#!/usr/bin/env python3
"""Tests for the Sonic Pi → Pi LED music forwarder (backend/sonic_pi.py).

Covers:
  1. _handle_beat forwards a music_beat downlink message (clean payload).
  2. _handle_state forwards a music_state message with playing coercion.
  3. AIOT_MUSIC_LED_ENABLED=0 silences the forwarder.
  4. Pi offline (send → False) is silent; send exceptions are throttled.

Run: python test_music_led_forward.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import sonic_pi
from sonic_pi import SonicPiOscAdapter

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


class FakeGateway:
    """pi_gateway stand-in recording sent messages."""

    def __init__(self, fail: bool = False) -> None:
        self.sent: list[dict] = []
        self.fail = fail

    def send(self, message: dict) -> bool:
        if self.fail:
            raise OSError("boom")
        self.sent.append(message)
        return True


def with_fake_gateway(fake: FakeGateway, fn) -> None:
    orig = sonic_pi.pi_gateway
    sonic_pi.pi_gateway = fake
    try:
        fn()
    finally:
        sonic_pi.pi_gateway = orig


def test_beat_forward() -> None:
    print("\n[1] _handle_beat forwards music_beat")
    fake = FakeGateway()
    adapter = SonicPiOscAdapter()

    def run() -> None:
        adapter._handle_beat("/music/beat", 3, 1, 108.0, 1.0)
        adapter._handle_beat("/music/beat", 3, 2, 108.0, 0.45)

    with_fake_gateway(fake, run)
    check("two beats forwarded", len(fake.sent) == 2, repr(fake.sent))
    msg = fake.sent[0]
    check("message_type music_beat", msg["message_type"] == "music_beat")
    check("payload fields",
          msg["payload"] == {"bar": 3.0, "beat": 1.0, "bpm": 108.0,
                             "beat_strength": 1.0},
          repr(msg["payload"]))
    check("weak beat strength preserved",
          fake.sent[1]["payload"]["beat_strength"] == 0.45)


def test_state_forward() -> None:
    print("\n[2] _handle_state forwards music_state with coercion")
    fake = FakeGateway()
    adapter = SonicPiOscAdapter()

    def run() -> None:
        adapter._handle_state("/music/state", 1, 108.0, "A", 0.7)
        adapter._handle_state("/music/state", "false", 96, "B", 0.3)

    with_fake_gateway(fake, run)
    check("two states forwarded", len(fake.sent) == 2, repr(fake.sent))
    msg = fake.sent[0]
    check("message_type music_state", msg["message_type"] == "music_state")
    check("playing coerced to True", msg["payload"]["playing"] is True)
    check("payload types JSON-clean",
          msg["payload"] == {"playing": True, "bpm": 108.0, "section": "A",
                             "energy": 0.7},
          repr(msg["payload"]))
    check("string 'false' coerced to False",
          fake.sent[1]["payload"]["playing"] is False)


def test_disabled() -> None:
    print("\n[3] MUSIC_LED_ENABLED=0 silences forwarding")
    fake = FakeGateway()
    adapter = SonicPiOscAdapter()
    orig = sonic_pi.MUSIC_LED_ENABLED
    sonic_pi.MUSIC_LED_ENABLED = False
    try:
        with_fake_gateway(fake, lambda: (
            adapter._handle_beat("/music/beat", 1, 1, 108.0, 1.0),
            adapter._handle_state("/music/state", True, 108.0, "A", 0.7),
        ))
    finally:
        sonic_pi.MUSIC_LED_ENABLED = orig
    check("nothing forwarded when disabled", fake.sent == [])


def test_failure_silent() -> None:
    print("\n[4] send failure is silent and throttled")
    fake = FakeGateway(fail=True)
    adapter = SonicPiOscAdapter()

    def run() -> None:
        for i in range(5):
            adapter._handle_beat("/music/beat", 1, i % 4 + 1, 108.0, 0.45)

    with_fake_gateway(fake, run)  # must not raise
    check("exceptions swallowed", adapter._last_error is not None
          and "music LED forward failed" in adapter._last_error,
          repr(adapter._last_error))
    first_error_at = adapter._music_led_error_at
    check("error timestamp set once (throttled)",
          abs(first_error_at - time.time()) < 5.0)


def main() -> int:
    test_beat_forward()
    test_state_forward()
    test_disabled()
    test_failure_silent()

    print(f"\n{'=' * 50}\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

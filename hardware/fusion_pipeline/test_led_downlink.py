#!/usr/bin/env python3
"""Tests for the LED downlink path (led_consumer + tcp_client downlink).

Covers:
  1. Effect → pattern mapping (canonical §8.2 names, Chinese RF labels, aliases)
  2. led_command schema validation (frozen contract §8.1)
  3. duration_ms timed revert to default pattern (injected clock)
  4. Offline degrade (no LED backend → commands dropped, no crash)
  5. TCP downlink end-to-end: backend → TcpJsonlClient read loop → LedConsumer,
     including uplink still working and downlink surviving a reconnect.

Usage:
    cd hardware/fusion_pipeline
    python test_led_downlink.py
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import time
from pathlib import Path

# ── Path setup (same as main.py) ──────────────────────────────────────────
_HARDWARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARDWARE))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "esp32_ble_gateway_to_Pi"))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "microbit_to_Pi"))

from fusion_pipeline.led_consumer import LedConsumer
import fusion_pipeline.led_consumer as led_consumer_mod
from fusion_pipeline.tcp_client import TcpJsonlClient

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

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


class FakeController:
    """LedController stand-in recording every call."""

    def __init__(self, connected: bool = True) -> None:
        self._connected = connected
        self.patterns: list[str] = []
        self.states: list[dict] = []
        self.updates = 0
        self.cleared = 0

    def set_pattern(self, pattern: str) -> bool:
        self.patterns.append(pattern)
        return True

    def set_state(self, **kwargs) -> None:
        self.states.append(kwargs)

    def update(self) -> None:
        self.updates += 1

    def clear(self) -> None:
        self.cleared += 1

    def get_status(self) -> dict:
        return {
            "connected": self._connected,
            "backend": "fake",
            "total_leds": 512,
            "current_pattern": self.patterns[-1] if self.patterns else None,
        }


# ── 1. Effect mapping ─────────────────────────────────────────────────────

def test_effect_mapping() -> None:
    print("\n[1] Effect → pattern mapping")
    fake = FakeController()
    consumer = LedConsumer(enabled=True, controller=fake)
    # Constructor sets the default pattern
    check("default pattern at init", fake.patterns == ["breathing"], repr(fake.patterns))

    cases = [
        # canonical backend event types (INTERFACE_CONTRACT §8.2)
        ("idle", "breathing"),
        ("gesture_start", "start"),
        ("stop", "stop"),
        ("downbeat", "downbeat"),
        ("upbeat", "upbeat"),
        ("crescendo", "crescendo"),
        ("decrescendo", "diminuendo"),
        ("left_cue", "left"),
        ("right_cue", "right"),
        # Chinese RF labels
        ("静止", "breathing"),
        ("开始", "start"),
        ("停止", "stop"),
        ("强拍", "downbeat"),
        ("弱拍", "upbeat"),
        ("渐强", "crescendo"),
        ("渐弱", "diminuendo"),
        ("左手提示", "left"),
        ("右手提示", "right"),
        # English aliases / raw pattern names
        ("strong_beat", "downbeat"),
        ("weak_beat", "upbeat"),
        ("diminuendo", "diminuendo"),
        ("start", "start"),
        ("wave", "wave"),
    ]
    for effect, expected in cases:
        fake.patterns.clear()
        consumer.apply_command({"effect": effect, "brightness": 0.8, "duration_ms": 0})
        check(f"effect {effect!r} → {expected}", fake.patterns == [expected], repr(fake.patterns))

    check("all mapped commands applied",
          consumer.commands_applied == len(cases),
          f"applied={consumer.commands_applied} expected={len(cases)}")
    check("no rejections during mapping", consumer.commands_rejected == 0)


# ── 2. Schema validation ──────────────────────────────────────────────────

def test_schema_validation() -> None:
    print("\n[2] led_command schema validation")
    fake = FakeController()
    consumer = LedConsumer(enabled=True, controller=fake)
    fake.patterns.clear()

    bad_payloads = [
        ("not a dict", "led_command"),
        ("missing brightness", {"effect": "stop", "duration_ms": 0}),
        ("missing duration_ms", {"effect": "stop", "brightness": 0.5}),
        ("missing effect", {"brightness": 0.5, "duration_ms": 0}),
        ("brightness not a number", {"effect": "stop", "brightness": "high", "duration_ms": 0}),
        ("duration_ms not a number", {"effect": "stop", "brightness": 0.5, "duration_ms": "soon"}),
        ("negative duration_ms", {"effect": "stop", "brightness": 0.5, "duration_ms": -1}),
        ("empty effect", {"effect": "  ", "brightness": 0.5, "duration_ms": 0}),
        ("effect not a string", {"effect": 7, "brightness": 0.5, "duration_ms": 0}),
        ("unknown effect", {"effect": "florp", "brightness": 0.5, "duration_ms": 0}),
    ]
    for name, payload in bad_payloads:
        before = consumer.commands_rejected
        consumer.apply_command(payload)
        check(f"reject: {name}", consumer.commands_rejected == before + 1)

    check("rejected commands never reach the controller", fake.patterns == [], repr(fake.patterns))

    # brightness is clamped into [0, 1], not rejected
    fake.states.clear()
    consumer.apply_command({"effect": "stop", "brightness": 1.7, "duration_ms": 0})
    check("brightness clamped to 1.0", fake.states == [{"intensity": 1.0}], repr(fake.states))


# ── 3. Timed revert ───────────────────────────────────────────────────────

def test_timed_revert() -> None:
    print("\n[3] duration_ms timed revert")
    now = [1000.0]
    fake = FakeController()
    consumer = LedConsumer(enabled=True, controller=fake, clock=lambda: now[0])
    fake.patterns.clear()

    consumer.apply_command({"effect": "downbeat", "brightness": 0.9, "duration_ms": 100})
    check("pattern applied", fake.patterns == ["downbeat"], repr(fake.patterns))

    consumer.update()
    check("no revert before deadline", fake.patterns == ["downbeat"], repr(fake.patterns))

    now[0] += 0.101
    consumer.update()
    check("revert to default after deadline", fake.patterns == ["downbeat", "breathing"], repr(fake.patterns))

    # duration_ms=0 holds until the next command
    consumer.apply_command({"effect": "stop", "brightness": 0.5, "duration_ms": 0})
    now[0] += 999.0
    consumer.update()
    check("duration_ms=0 holds", fake.patterns[-1] == "stop", repr(fake.patterns))

    check("update() renders frames", fake.updates >= 3, f"updates={fake.updates}")

    consumer.close()
    check("close() clears the strip", fake.cleared == 1)


# ── 4. Offline degrade ────────────────────────────────────────────────────

def test_offline_degrade() -> None:
    print("\n[4] Offline degrade (no LED backend)")
    fake = FakeController(connected=False)
    consumer = LedConsumer(enabled=True, controller=fake)
    consumer.apply_command({"effect": "downbeat", "brightness": 0.9, "duration_ms": 0})
    check("command dropped offline", consumer.commands_dropped_offline == 1)
    check("not counted as applied", consumer.commands_applied == 0)
    check("controller untouched", fake.patterns == [], repr(fake.patterns))

    consumer.update()  # must not crash
    consumer.close()

    # Auto-construction paths: stub the LedController factory so the result is
    # deterministic on every host — on the Pi a REAL LedController would
    # connect to /dev/leds0 and these checks would fail.
    orig_factory = led_consumer_mod.LedController
    try:
        led_consumer_mod.LedController = lambda **kw: FakeController(connected=False)
        auto = LedConsumer(enabled=True, controller=None)
        auto.handle_message({"message_type": "led_command",
                             "payload": {"effect": "stop", "brightness": 1.0, "duration_ms": 0}})
        check("auto-constructed disconnected controller drops",
              auto.commands_dropped_offline == 1)

        def _boom(**kw):
            raise RuntimeError("no LED hardware")

        led_consumer_mod.LedController = _boom
        broken = LedConsumer(enabled=True, controller=None)
        broken.handle_message({"message_type": "led_command",
                               "payload": {"effect": "stop", "brightness": 1.0, "duration_ms": 0}})
        check("factory failure → controller None, command dropped",
              broken.commands_dropped_offline == 1 and broken._controller is None)
    finally:
        led_consumer_mod.LedController = orig_factory

    disabled = LedConsumer(enabled=False)
    disabled.handle_message({"message_type": "led_command",
                             "payload": {"effect": "stop", "brightness": 1.0, "duration_ms": 0}})
    check("enabled=False survives commands", disabled.commands_dropped_offline == 1)


def test_controller_midrun_failure_degrade() -> None:
    """LedController.update(): persistent render errors must not flood logs
    forever and must eventually flip connected=False (degrade path)."""
    print("\n[4b] LedController mid-run failure degrade")
    from raspberry_pi_iot.led.controller import LedController as RealController

    ctl = RealController.__new__(RealController)  # bypass hardware init
    ctl._connected = True
    ctl._consecutive_errors = 0
    ctl._error = None

    def _always_fail():
        raise OSError("EIO on /dev/leds0")

    ctl._update_animation = _always_fail

    for _ in range(249):
        ctl.update()
    check("still connected at 249 consecutive errors", ctl._connected is True)
    ctl.update()
    check("disconnected after 250 consecutive errors", ctl._connected is False)
    check("error recorded", ctl._error is not None and "EIO" in ctl._error)
    ctl.update()  # disconnected → early return, no further counting
    check("no more error counting once disconnected", ctl._consecutive_errors == 250)


# ── 5. TCP downlink end-to-end ────────────────────────────────────────────

async def _wait_for(cond, timeout: float, what: str) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        await asyncio.sleep(0.02)
    print(f"    (timeout waiting for: {what})")
    return False


async def test_tcp_downlink_e2e() -> None:
    print("\n[5] TCP downlink end-to-end (server → client → consumer)")
    uplink_received: list[dict] = []
    server_writers: list[asyncio.StreamWriter] = []

    async def handle_conn(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        server_writers.append(writer)
        # Backend pushes one led_command per connection (also after reconnect)
        cmd = {"message_type": "led_command",
               "payload": {"effect": "downbeat", "brightness": 0.9,
                           "duration_ms": 0, "source": "backend"}}
        writer.write((json.dumps(cmd) + "\n").encode())
        await writer.drain()
        try:
            while True:
                line = await reader.readline()
                if not line:
                    break
                uplink_received.append(json.loads(line))
        except (ConnectionResetError, asyncio.IncompleteReadError):
            pass
        finally:
            try:
                writer.close()
            except OSError:
                pass

    server = await asyncio.start_server(handle_conn, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    fake = FakeController()
    consumer = LedConsumer(enabled=True, controller=fake)
    fake.patterns.clear()

    client = TcpJsonlClient(host="127.0.0.1", port=port,
                            reconnect_delay_s=0.2, connect_timeout_s=2.0)
    client.set_downlink_handler(consumer.handle_message)
    await client.start()
    try:
        ok = await _wait_for(lambda: "downbeat" in fake.patterns, 3.0,
                             "downlink led_command applied")
        check("downlink led_command applied", ok, repr(fake.patterns))

        # Uplink path still works while the read loop runs
        client.send({"message_type": "status", "payload": {"probe": True}})
        ok = await _wait_for(lambda: len(uplink_received) >= 1, 3.0, "uplink message")
        check("uplink still works", ok and uplink_received[0]["message_type"] == "status",
              repr(uplink_received))

        # Server drops the connection → client must reconnect and the new
        # reader must deliver the next downlink command.
        before = client.get_status()["downlink_received"]
        server_writers[0].close()
        ok = await _wait_for(lambda: len(server_writers) >= 2, 8.0, "reconnect")
        check("client reconnected after server close", ok,
              f"connections={len(server_writers)}")
        ok = await _wait_for(
            lambda: client.get_status()["downlink_received"] > before, 5.0,
            "downlink after reconnect")
        check("downlink works after reconnect", ok,
              f"downlink_received={client.get_status()['downlink_received']} (was {before})")
    finally:
        await client.stop()
        server.close()
        await server.wait_closed()

    # Non-led_command downlink is ignored without crashing
    consumer.handle_message({"message_type": "system_command", "payload": {"cmd": "reboot"}})
    consumer.handle_message({"message_type": "time_sync", "payload": {"t": 1}})
    consumer.handle_message({"garbage": True})
    check("unhandled downlink types ignored", consumer.commands_applied == 1 + 1,
          f"applied={consumer.commands_applied}")  # one per connection


# ── Runner ────────────────────────────────────────────────────────────────

def main() -> int:
    test_effect_mapping()
    test_schema_validation()
    test_timed_revert()
    test_offline_degrade()
    test_controller_midrun_failure_degrade()
    asyncio.run(test_tcp_downlink_e2e())

    print(f"\n{'=' * 50}\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

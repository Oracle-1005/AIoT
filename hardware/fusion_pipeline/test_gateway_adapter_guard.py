#!/usr/bin/env python3
"""Regression test: control-event dedup ProtocolError must not escape.

EventDeduplicator.is_duplicate raises ProtocolError when repeat copies of
the same event disagree. Before the guard, that exception escaped
_handle_control_event and killed the serial/UDP read loop silently —
all micro:bit input (sensors included) stopped until service restart.

Usage:
    cd hardware/fusion_pipeline
    python test_gateway_adapter_guard.py
"""

from __future__ import annotations

import sys
from pathlib import Path

_HARDWARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARDWARE))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "esp32_ble_gateway_to_Pi"))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "microbit_to_Pi"))

from microbit_receiver.protocol import Hand, ProtocolError

from fusion_pipeline.gateway_adapter import GatewayAdapter


class _RaisingDedup:
    def is_duplicate(self, packet):
        raise ProtocolError("repeat copies disagree")


class _StubHand:
    label = "L"


class _StubPacket:
    hand = _StubHand()
    event_sequence = 1


def main() -> None:
    delivered: list[dict] = []
    adapter = GatewayAdapter(
        listen_host="127.0.0.1",
        listen_port=0,
        allowed_hands={Hand.LEFT, Hand.RIGHT},
        event_dedup_ttl_s=10.0,
        on_sensor_state=None,
        on_control_event=delivered.append,
    )
    adapter._event_deduplicator = _RaisingDedup()

    # Must swallow ProtocolError, log, and drop the packet — no raise,
    # no delivery. (Before the fix this raised and killed the read loop.)
    adapter._handle_control_event(
        _StubPacket(), None, ("127.0.0.1", 4000), transport_name="serial"
    )
    assert delivered == [], delivered
    print("PASS 去重 ProtocolError 被就地拦截（不抛出、不下发）")

    print("\nAll gateway-adapter guard tests passed.")


if __name__ == "__main__":
    main()

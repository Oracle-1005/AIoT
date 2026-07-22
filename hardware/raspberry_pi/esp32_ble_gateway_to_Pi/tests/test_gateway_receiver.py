from __future__ import annotations

import json
import struct
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MICROBIT_RECEIVER = ROOT.parent / "microbit_to_Pi"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(MICROBIT_RECEIVER))

from esp32_gateway_receiver.gateway_frame import parse_gateway_frame
from microbit_receiver.protocol import Hand


def make_gateway_frame(payload: bytes) -> bytes:
    header = struct.pack(
        "<4sBBBBIIBb",
        b"MBGW",
        1,
        18,
        len(payload),
        0,
        123,
        456789,
        1,
        -42,
    )
    return header + payload


def test_parse_gateway_frame_keeps_microbit_payload() -> None:
    payload = struct.pack(
        "<BHIhhhhh",
        0x01 | (int(Hand.LEFT) << 2),
        7,
        1200,
        10,
        20,
        -1000,
        12,
        -3,
    )

    frame = parse_gateway_frame(make_gateway_frame(payload))

    assert frame.gateway_sequence == 123
    assert frame.esp_rx_micros == 456789
    assert frame.conn_index == 1
    assert frame.ble_rssi == -42
    assert frame.payload == payload

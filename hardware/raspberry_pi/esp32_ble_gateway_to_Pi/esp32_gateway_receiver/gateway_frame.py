"""Binary UDP frame used by the ESP32 BLE-to-Wi-Fi gateway."""

from __future__ import annotations

import struct
from dataclasses import dataclass


MAGIC = b"MBGW"
VERSION = 1
HEADER_STRUCT = struct.Struct("<4sBBBBIIBb")
HEADER_LENGTH = HEADER_STRUCT.size


class GatewayFrameError(ValueError):
    """Raised when a UDP datagram is not a valid gateway frame."""


@dataclass(frozen=True, slots=True)
class GatewayFrame:
    gateway_sequence: int
    esp_rx_micros: int
    conn_index: int
    ble_rssi: int
    flags: int
    payload: bytes


def parse_gateway_frame(datagram: bytes) -> GatewayFrame:
    if len(datagram) < HEADER_LENGTH:
        raise GatewayFrameError(
            f"gateway frame too short: {len(datagram)} B"
        )

    (
        magic,
        version,
        header_len,
        payload_len,
        flags,
        gateway_sequence,
        esp_rx_micros,
        conn_index,
        ble_rssi,
    ) = HEADER_STRUCT.unpack_from(datagram)

    if magic != MAGIC:
        raise GatewayFrameError(f"bad gateway magic: {magic!r}")
    if version != VERSION:
        raise GatewayFrameError(f"unsupported gateway version: {version}")
    if header_len != HEADER_LENGTH:
        raise GatewayFrameError(
            f"header_len={header_len}, expected {HEADER_LENGTH}"
        )

    expected_len = header_len + payload_len
    if len(datagram) != expected_len:
        raise GatewayFrameError(
            f"frame length mismatch: got {len(datagram)} B, "
            f"expected {expected_len} B"
        )

    payload = datagram[header_len:expected_len]
    if len(payload) not in {11, 17}:
        raise GatewayFrameError(
            f"micro:bit payload must be 11 B or 17 B, got {len(payload)} B"
        )

    return GatewayFrame(
        gateway_sequence=gateway_sequence,
        esp_rx_micros=esp_rx_micros,
        conn_index=conn_index,
        ble_rssi=ble_rssi,
        flags=flags,
        payload=payload,
    )

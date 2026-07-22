"""Send one demo ESP32 gateway UDP frame to a receiver."""

from __future__ import annotations

import argparse
import socket
import struct
import time


def build_sensor_payload(hand: int) -> bytes:
    header = 0x01 | ((hand & 0x01) << 2)
    return struct.pack(
        "<BHIhhhhh",
        header,
        1,
        int(time.monotonic() * 1000) & 0xFFFFFFFF,
        32,
        176,
        -1040,
        9,
        1,
    )


def build_gateway_frame(payload: bytes) -> bytes:
    return struct.pack(
        "<4sBBBBIIBb",
        b"MBGW",
        1,
        18,
        len(payload),
        0,
        1,
        int(time.monotonic() * 1_000_000) & 0xFFFFFFFF,
        0,
        -42,
    ) + payload


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=17778)
    parser.add_argument("--hand", choices=("left", "right"), default="left")
    args = parser.parse_args()

    hand = 0 if args.hand == "left" else 1
    datagram = build_gateway_frame(build_sensor_payload(hand))
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.sendto(datagram, (args.host, args.port))


if __name__ == "__main__":
    main()

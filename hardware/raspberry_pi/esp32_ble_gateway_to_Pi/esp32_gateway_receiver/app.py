"""UDP receiver for ESP32 BLE-to-Wi-Fi micro:bit gateway."""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
import time
from pathlib import Path
from typing import Any

from microbit_receiver.protocol import (
    ControlEvent,
    Hand,
    ProtocolError,
    SensorState,
    decode_header,
    parse_packet,
)
from microbit_receiver.tracking import EventDeduplicator, SequenceTracker

from .gateway_frame import GatewayFrame, GatewayFrameError, parse_gateway_frame


LOGGER = logging.getLogger(__name__)


class GatewayDatagramProtocol(asyncio.DatagramProtocol):
    def __init__(self, receiver: "GatewayReceiver") -> None:
        self.receiver = receiver

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.receiver.handle_datagram(data, addr)

    def error_received(self, exc: Exception) -> None:
        LOGGER.warning("UDP socket error: %s", exc)


class GatewayReceiver:
    def __init__(
        self,
        *,
        allowed_hands: set[Hand],
        event_dedup_ttl_seconds: float,
        emit_gateway_metadata: bool,
    ) -> None:
        self.allowed_hands = allowed_hands
        self.emit_gateway_metadata = emit_gateway_metadata
        self.sequence_tracker = SequenceTracker()
        self.event_deduplicator = EventDeduplicator(event_dedup_ttl_seconds)

    def handle_datagram(self, data: bytes, addr: tuple[str, int]) -> None:
        pi_udp_rx_monotonic_ns = time.monotonic_ns()
        try:
            frame = parse_gateway_frame(data)
            message_type, hand = decode_header(frame.payload[0])
            if hand not in self.allowed_hands:
                raise ProtocolError(f"hand {hand.label!r} is not enabled")
            packet = parse_packet(
                frame.payload,
                expected_hand=hand,
                pi_rx_monotonic_ns=pi_udp_rx_monotonic_ns,
            )
            item = self._route_packet(packet)
            if item is None:
                return
            if self.emit_gateway_metadata:
                item["transport"] = "esp32_udp_gateway"
                item["gateway"] = gateway_metadata(frame, addr)
            write_json_line(item)
        except (GatewayFrameError, ProtocolError, ValueError) as exc:
            LOGGER.warning("drop UDP datagram from %s:%d: %s", *addr, exc)

    def _route_packet(
        self,
        packet: SensorState | ControlEvent,
    ) -> dict[str, Any] | None:
        if isinstance(packet, SensorState):
            decision = self.sequence_tracker.observe(packet)
            if not decision.accept:
                LOGGER.debug(
                    "drop %s sensor seq=%d: %s",
                    packet.hand.label,
                    packet.sample_sequence,
                    decision.reason,
                )
                return None

            item = packet.to_dict()
            item["sequence_status"] = decision.reason
            item["missing_sample_count"] = decision.missing_sample_count
            item["device_restarted"] = decision.device_restarted
            if decision.device_restarted:
                self.event_deduplicator.clear(packet.hand)
            return item

        duplicate = self.event_deduplicator.is_duplicate(packet)
        if duplicate:
            LOGGER.debug(
                "ignore duplicate control event %s/%d copy %d",
                packet.hand.label,
                packet.event_sequence,
                packet.repeat_index,
            )
            return None
        return packet.to_dict(duplicate=False)


def gateway_metadata(frame: GatewayFrame, addr: tuple[str, int]) -> dict[str, Any]:
    return {
        "source_ip": addr[0],
        "source_port": addr[1],
        "gateway_sequence": frame.gateway_sequence,
        "esp_rx_micros": frame.esp_rx_micros,
        "conn_index": frame.conn_index,
        "ble_rssi": frame.ble_rssi,
        "flags": frame.flags,
    }


def write_json_line(item: dict[str, Any]) -> None:
    print(json.dumps(item, ensure_ascii=False, separators=(",", ":")), flush=True)


def load_config(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8-sig"))


def parse_allowed_hands(data: dict[str, Any]) -> set[Hand]:
    labels = data.get("allowed_hands", ["left", "right"])
    hands = {Hand.from_label(str(label)) for label in labels}
    if not hands:
        raise ValueError("allowed_hands must not be empty")
    return hands


async def async_main(config_path: Path) -> None:
    data = load_config(config_path)
    receiver = GatewayReceiver(
        allowed_hands=parse_allowed_hands(data),
        event_dedup_ttl_seconds=float(data.get("event_dedup_ttl_seconds", 10.0)),
        emit_gateway_metadata=bool(data.get("emit_gateway_metadata", True)),
    )

    loop = asyncio.get_running_loop()
    stop_event = asyncio.Event()
    for signame in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signame, stop_event.set)
        except NotImplementedError:
            pass

    listen_host = str(data.get("listen_host", "0.0.0.0"))
    listen_port = int(data.get("listen_port", 17778))
    transport, _protocol = await loop.create_datagram_endpoint(
        lambda: GatewayDatagramProtocol(receiver),
        local_addr=(listen_host, listen_port),
    )
    LOGGER.info("listening for ESP32 gateway UDP on %s:%d", listen_host, listen_port)
    try:
        await stop_event.wait()
    finally:
        transport.close()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Receive ESP32 BLE gateway UDP packets as JSON Lines"
    )
    parser.add_argument("--config", type=Path, required=True, help="JSON config")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(async_main(args.config))
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"config error: {exc}")


if __name__ == "__main__":
    main()

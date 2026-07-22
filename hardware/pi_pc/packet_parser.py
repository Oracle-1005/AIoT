"""Binary packet parser for the Microbit_to_Pi_v01 BLE protocol.

The current protocol uses two packet shapes:

  sensor_state:  17 bytes, <B H I h h h h h>
  control_event: 11 bytes, <B H I B B B B>

The first byte is a packed header:
  bits 0..1: message_type, 1=sensor_state, 2=control_event
  bit 2:     hand, 0=left, 1=right
  bits 3..7: reserved, must be 0
"""

from __future__ import annotations

import logging
import struct
from dataclasses import dataclass
from enum import IntEnum

logger = logging.getLogger(__name__)

SENSOR_STATE_FORMAT = "<BHIhhhhh"
CONTROL_EVENT_FORMAT = "<BHIBBBB"
SENSOR_STATE_SIZE = struct.calcsize(SENSOR_STATE_FORMAT)
CONTROL_EVENT_SIZE = struct.calcsize(CONTROL_EVENT_FORMAT)

# Backward-compatible aliases used by existing unit helpers.
PACKET_FORMAT = SENSOR_STATE_FORMAT
PACKET_SIZE = SENSOR_STATE_SIZE

HAND_MAP = {0: "left", 1: "right"}


class MessageType(IntEnum):
    SENSOR_STATE = 1
    CONTROL_EVENT = 2


EVENT_CODE_NAMES = {
    0x01: "A_SHORT_PRESS",
    0x02: "B_SHORT_PRESS",
    0x03: "B_LONG_PRESS",
    0x04: "AB_LONG_PRESS",
}

EVENT_RULES = {
    ("left", 0x01): (40, "start_or_resume"),
    ("left", 0x02): (60, "pause"),
    ("right", 0x01): (20, "style_switch"),
    ("right", 0x03): (100, "emergency_stop"),
    ("left", 0x04): (60, "recalibrate"),
    ("right", 0x04): (60, "recalibrate"),
}


@dataclass
class ParsedPacket:
    """A parsed 17-byte micro:bit sensor_state packet."""

    device_id: str
    hand: str
    version: int
    sequence: int
    device_timestamp_ms: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    pitch_deg: int
    roll_deg: int
    flags: int
    pi_receive_timestamp_ns: int = 0
    message_type: int = int(MessageType.SENSOR_STATE)

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "hand": self.hand,
            "version": self.version,
            "message_type": self.message_type,
            "sequence": self.sequence,
            "sample_sequence": self.sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "ax_mg": self.ax_mg,
            "ay_mg": self.ay_mg,
            "az_mg": self.az_mg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "flags": self.flags,
            "pi_receive_timestamp_ns": self.pi_receive_timestamp_ns,
            "pi_rx_monotonic_ns": self.pi_receive_timestamp_ns,
        }


@dataclass(frozen=True)
class ParsedControlEvent:
    """A parsed 11-byte micro:bit control_event packet."""

    device_id: str
    hand: str
    event_sequence: int
    device_timestamp_ms: int
    event_code: int
    event_name: str
    priority: int
    repeat_index: int
    repeat_total: int
    mapped_candidate: str
    pi_receive_timestamp_ns: int
    message_type: int = int(MessageType.CONTROL_EVENT)

    def to_dict(self, duplicate: bool = False) -> dict:
        return {
            "type": "microbit_control_event",
            "source": self.hand,
            "device_id": self.device_id,
            "message_type": self.message_type,
            "event_sequence": self.event_sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "pi_rx_monotonic_ns": self.pi_receive_timestamp_ns,
            "event_code": self.event_name,
            "priority": self.priority,
            "repeat_index": self.repeat_index,
            "repeat_total": self.repeat_total,
            "duplicate": duplicate,
            "mapped_candidate": self.mapped_candidate,
            "time_alignment": None,
        }


class PacketParser:
    """Parses Microbit_to_Pi_v01 binary BLE notification payloads."""

    EXPECTED_VERSION = 1

    @staticmethod
    def parse(
        device_id: str,
        expected_hand: str,
        raw_data: bytes | bytearray,
        pi_receive_ns: int,
    ) -> ParsedPacket | ParsedControlEvent | None:
        if not raw_data:
            logger.warning("[%s] Empty packet. Discarding.", device_id)
            return None

        try:
            message_type, packet_hand = _decode_header(raw_data[0])
        except ValueError as exc:
            logger.warning("[%s] Bad header 0x%02x: %s", device_id, raw_data[0], exc)
            return None

        expected = expected_hand.lower()
        if packet_hand != expected:
            logger.warning(
                "[%s] Hand mismatch: packet says '%s', config says '%s'. Discarding.",
                device_id,
                packet_hand,
                expected,
            )
            return None

        if message_type is MessageType.SENSOR_STATE:
            return PacketParser._parse_sensor_state(
                device_id, packet_hand, raw_data, pi_receive_ns
            )
        if message_type is MessageType.CONTROL_EVENT:
            return PacketParser._parse_control_event(
                device_id, packet_hand, raw_data, pi_receive_ns
            )

        logger.warning("[%s] Unsupported message type: %s", device_id, message_type)
        return None

    @staticmethod
    def _parse_sensor_state(
        device_id: str,
        hand: str,
        raw_data: bytes | bytearray,
        pi_receive_ns: int,
    ) -> ParsedPacket | None:
        if len(raw_data) != SENSOR_STATE_SIZE:
            logger.warning(
                "[%s] Bad sensor_state length: expected %d, got %d bytes. Discarding.",
                device_id,
                SENSOR_STATE_SIZE,
                len(raw_data),
            )
            return None

        try:
            (
                _header,
                sequence,
                device_timestamp_ms,
                ax_mg,
                ay_mg,
                az_mg,
                pitch_deg,
                roll_deg,
            ) = struct.unpack(SENSOR_STATE_FORMAT, bytes(raw_data))
        except struct.error as exc:
            logger.warning("[%s] sensor_state unpack failed: %s", device_id, exc)
            return None

        if any(not -8000 <= value <= 8000 for value in (ax_mg, ay_mg, az_mg)):
            logger.warning(
                "[%s] Accelerometer out of range: %s",
                device_id,
                (ax_mg, ay_mg, az_mg),
            )
            return None
        if not -180 <= pitch_deg <= 180 or not -180 <= roll_deg <= 180:
            logger.warning(
                "[%s] Orientation out of range: pitch=%d roll=%d",
                device_id,
                pitch_deg,
                roll_deg,
            )
            return None

        return ParsedPacket(
            device_id=device_id,
            hand=hand,
            version=PacketParser.EXPECTED_VERSION,
            sequence=sequence,
            device_timestamp_ms=device_timestamp_ms,
            ax_mg=ax_mg,
            ay_mg=ay_mg,
            az_mg=az_mg,
            pitch_deg=pitch_deg,
            roll_deg=roll_deg,
            flags=0,
            pi_receive_timestamp_ns=pi_receive_ns,
        )

    @staticmethod
    def _parse_control_event(
        device_id: str,
        hand: str,
        raw_data: bytes | bytearray,
        pi_receive_ns: int,
    ) -> ParsedControlEvent | None:
        if len(raw_data) != CONTROL_EVENT_SIZE:
            logger.warning(
                "[%s] Bad control_event length: expected %d, got %d bytes. Discarding.",
                device_id,
                CONTROL_EVENT_SIZE,
                len(raw_data),
            )
            return None

        try:
            (
                _header,
                event_sequence,
                device_timestamp_ms,
                event_code,
                priority,
                repeat_index,
                repeat_total,
            ) = struct.unpack(CONTROL_EVENT_FORMAT, bytes(raw_data))
        except struct.error as exc:
            logger.warning("[%s] control_event unpack failed: %s", device_id, exc)
            return None

        event_name = EVENT_CODE_NAMES.get(event_code)
        if event_name is None:
            logger.warning("[%s] Unknown event_code: 0x%02x", device_id, event_code)
            return None

        rule = EVENT_RULES.get((hand, event_code))
        if rule is None:
            logger.warning(
                "[%s] Event %s is not allowed for %s hand.",
                device_id,
                event_name,
                hand,
            )
            return None

        expected_priority, mapped_candidate = rule
        if priority != expected_priority:
            logger.warning(
                "[%s] Wrong priority for %s/%s: expected %d, got %d.",
                device_id,
                hand,
                event_name,
                expected_priority,
                priority,
            )
            return None
        if repeat_total <= 0 or repeat_index >= repeat_total:
            logger.warning(
                "[%s] Bad repeat fields: repeat_index=%d repeat_total=%d.",
                device_id,
                repeat_index,
                repeat_total,
            )
            return None

        return ParsedControlEvent(
            device_id=device_id,
            hand=hand,
            event_sequence=event_sequence,
            device_timestamp_ms=device_timestamp_ms,
            event_code=event_code,
            event_name=event_name,
            priority=priority,
            repeat_index=repeat_index,
            repeat_total=repeat_total,
            mapped_candidate=mapped_candidate,
            pi_receive_timestamp_ns=pi_receive_ns,
        )

    @staticmethod
    def build_command_packet(command: str) -> bytes:
        return (command + "\r\n").encode("utf-8")


def _decode_header(header: int) -> tuple[MessageType, str]:
    if header & 0b1111_1000:
        raise ValueError("reserved bits must be 0")

    raw_type = header & 0x03
    try:
        message_type = MessageType(raw_type)
    except ValueError as exc:
        raise ValueError(f"unsupported message_type {raw_type}") from exc

    hand = HAND_MAP[(header >> 2) & 0x01]
    return message_type, hand

"""Binary packet parser for micro:bit BLE data — docs/Microbit_to_Pi _v01.md.

Two packet types share a 1-byte header:
  bits 0–1: message_type (1 = sensor_state, 2 = control_event)
  bit 2:    hand (0 = left, 1 = right)
  bits 3–7: reserved (must be 0)

sensor_state (17 B, 25–50 Hz):
  uint8   header           (1B)  — message_type=1 + hand bit
  uint16  sample_sequence  (2B)  — LE, increments on every sample
  uint32  device_timestamp_ms (4B) — LE, micro:bit input.runningTime()
  int16   ax_mg            (2B)  — LE, X acceleration in milli-g
  int16   ay_mg            (2B)  — LE, Y acceleration in milli-g
  int16   az_mg            (2B)  — LE, Z acceleration in milli-g
  int16   pitch_deg        (2B)  — LE, pitch angle in degrees
  int16   roll_deg         (2B)  — LE, roll angle in degrees

control_event (11 B, event-driven):
  uint8   header           (1B)  — message_type=2 + hand bit
  uint16  event_sequence   (2B)  — LE, increments on each new event
  uint32  device_timestamp_ms (4B) — LE, event confirmation time
  uint8   event_code       (1B)  — A_SHORT_PRESS=0x01, B_SHORT_PRESS=0x02, …
  uint8   priority         (1B)
  uint8   repeat_index     (1B)
  uint8   repeat_total     (1B)
"""

import struct
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# ---- Header bit layout ----
HEADER_MESSAGE_TYPE_MASK = 0x03   # bits 0–1
HEADER_HAND_MASK        = 0x04   # bit 2
HEADER_HAND_SHIFT       = 2

MESSAGE_TYPE_SENSOR  = 1
MESSAGE_TYPE_CONTROL = 2
HAND_MAP = {0: "left", 1: "right"}

# ---- Struct formats (little-endian) ----
# sensor_state: header(1) + seq(2) + ts(4) + ax(2) + ay(2) + az(2) + pitch(2) + roll(2)
SENSOR_STATE_FORMAT = "<BHIhhhhh"
SENSOR_STATE_SIZE   = struct.calcsize(SENSOR_STATE_FORMAT)   # 17

# control_event: header(1) + seq(2) + ts(4) + event_code(1) + priority(1) + repeat_idx(1) + repeat_total(1)
CONTROL_EVENT_FORMAT = "<BHIBBBB"
CONTROL_EVENT_SIZE   = struct.calcsize(CONTROL_EVENT_FORMAT)  # 11

# Backward-compatible aliases
PACKET_FORMAT = SENSOR_STATE_FORMAT
PACKET_SIZE   = SENSOR_STATE_SIZE


@dataclass
class ParsedPacket:
    """A parsed micro:bit BLE sensor_state packet."""

    device_id: str
    hand: str
    message_type: int          # 1 = sensor_state, 2 = control_event
    sequence: int
    device_timestamp_ms: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    pitch_deg: int
    roll_deg: int
    pi_receive_timestamp_ns: int = 0

    # Deprecated — kept for backward compat with old callers
    @property
    def version(self) -> int:
        return 1

    @property
    def flags(self) -> int:
        return 0

    def to_dict(self) -> dict:
        """Convert to a plain dict for downstream consumers."""
        return {
            "device_id": self.device_id,
            "hand": self.hand,
            "message_type": self.message_type,
            "sequence": self.sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "ax_mg": self.ax_mg,
            "ay_mg": self.ay_mg,
            "az_mg": self.az_mg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "pi_receive_timestamp_ns": self.pi_receive_timestamp_ns,
        }


def _parse_header(header: int) -> tuple[int, int]:
    """Extract message_type and hand from a 1-byte header.

    Returns (message_type, hand_bit) where hand_bit is 0=left, 1=right.
    """
    msg_type = header & HEADER_MESSAGE_TYPE_MASK
    hand_bit = (header & HEADER_HAND_MASK) >> HEADER_HAND_SHIFT
    return msg_type, hand_bit


class PacketParser:
    """Parses micro:bit BLE binary payloads per docs/Microbit_to_Pi _v01.md.

    Two packet types:
      - sensor_state  (17 B, message_type=1): IMU data at 25–50 Hz
      - control_event (11 B, message_type=2): button events
    """

    # Backward compat
    EXPECTED_VERSION = 1

    @staticmethod
    def parse(
        device_id: str,
        expected_hand: str,
        raw_data: (bytes | bytearray),
        pi_receive_ns: int,
    ) -> ParsedPacket | None:
        """Unpack a sensor_state binary packet (17 B).

        Args:
            device_id: Logical device ID (MB_LEFT, MB_RIGHT, etc.)
            expected_hand: Expected hand label from config ("left"/"right")
            raw_data: Raw bytearray from BLE notification
            pi_receive_ns: Pi monotonic_ns timestamp when notification arrived

        Returns:
            ParsedPacket on success, None on parse failure.
        """
        if len(raw_data) != SENSOR_STATE_SIZE:
            logger.warning(
                "[%s] Bad packet length: expected %d, got %d bytes. Discarding.",
                device_id,
                SENSOR_STATE_SIZE,
                len(raw_data),
            )
            return None

        try:
            (
                header,
                sequence,
                device_timestamp_ms,
                ax_mg,
                ay_mg,
                az_mg,
                pitch_deg,
                roll_deg,
            ) = struct.unpack(SENSOR_STATE_FORMAT, bytes(raw_data))
        except struct.error as e:
            logger.warning("[%s] struct.unpack failed: %s", device_id, e)
            return None

        # Parse header byte
        msg_type, hand_bit = _parse_header(header)

        # Validate message_type
        if msg_type != MESSAGE_TYPE_SENSOR:
            logger.warning(
                "[%s] Expected sensor_state (type=1), got type=%d. "
                "Use parse_control_event() for control_event packets.",
                device_id, msg_type,
            )
            return None

        # Validate reserved bits
        if header & 0xF8:
            logger.debug(
                "[%s] Reserved header bits set: 0x%02X. Processing anyway.",
                device_id, header,
            )

        # Map hand
        hand = HAND_MAP.get(hand_bit, "unknown")
        if hand == "unknown":
            logger.warning(
                "[%s] Unknown hand bit: %d. Defaulting to 'unknown'.", device_id, hand_bit
            )
        elif hand != expected_hand:
            logger.warning(
                "[%s] Hand mismatch: packet says '%s', config says '%s'. Using packet value.",
                device_id, hand, expected_hand,
            )

        return ParsedPacket(
            device_id=device_id,
            hand=hand,
            message_type=msg_type,
            sequence=sequence,
            device_timestamp_ms=device_timestamp_ms,
            ax_mg=ax_mg,
            ay_mg=ay_mg,
            az_mg=az_mg,
            pitch_deg=pitch_deg,
            roll_deg=roll_deg,
            pi_receive_timestamp_ns=pi_receive_ns,
        )

    @staticmethod
    def parse_control_event(
        device_id: str,
        expected_hand: str,
        raw_data: (bytes | bytearray),
        pi_receive_ns: int,
    ) -> dict | None:
        """Unpack a control_event binary packet (11 B).

        Returns a dict with keys: source, hand, event_sequence,
        device_timestamp_ms, event_code, priority, repeat_index,
        repeat_total, pi_rx_monotonic_ns.
        """
        if len(raw_data) != CONTROL_EVENT_SIZE:
            logger.warning(
                "[%s] Bad control_event length: expected %d, got %d.",
                device_id, CONTROL_EVENT_SIZE, len(raw_data),
            )
            return None

        try:
            (header, event_seq, ts_ms, event_code,
             priority, repeat_idx, repeat_total,
            ) = struct.unpack(CONTROL_EVENT_FORMAT, bytes(raw_data))
        except struct.error as e:
            logger.warning("[%s] struct.unpack control_event failed: %s", device_id, e)
            return None

        msg_type, hand_bit = _parse_header(header)
        if msg_type != MESSAGE_TYPE_CONTROL:
            logger.warning("[%s] Expected control_event (type=2), got type=%d.", device_id, msg_type)
            return None

        hand = HAND_MAP.get(hand_bit, "unknown")

        return {
            "type": "microbit_control_event",
            "source": hand,
            "message_type": msg_type,
            "hand": hand_bit,
            "event_sequence": event_seq,
            "device_timestamp_ms": ts_ms,
            "pi_rx_monotonic_ns": pi_receive_ns,
            "event_code": event_code,
            "priority": priority,
            "repeat_index": repeat_idx,
            "repeat_total": repeat_total,
            "duplicate": False,
        }

    @staticmethod
    def build_command_packet(command: str) -> bytes:
        """Build a text command payload for BLE UART TX.

        Commands are sent as text with \\r\\n terminator, matching the
        existing micro:bit UART protocol.

        Args:
            command: Command string, e.g. "SYNC,5" or "START"

        Returns:
            UTF-8 encoded bytes with \\r\\n terminator.
        """
        return (command + "\r\n").encode("utf-8")

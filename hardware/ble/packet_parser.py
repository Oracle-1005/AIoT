"""19-byte binary packet parser for micro:bit BLE data.

Packet format (little-endian, packed):
  uint8   version (1B)
  uint8   hand   (1B) — 0=left, 1=right
  uint16  sequence (2B)
  uint32  device_timestamp_ms (4B)
  int16   ax_mg, ay_mg, az_mg (2B each = 6B)
  int16   pitch_deg, roll_deg (2B each = 4B)
  uint8   flags (1B)
  Total: 19 bytes

Note: The original documentation states 20 bytes but the per-field
specification sums to 19 bytes. This implementation follows the per-field
definition. If actual micro:bit firmware sends 20 bytes, adjust PACKET_SIZE
and the struct format accordingly (likely a reserved/padding byte at the end).
"""

import struct
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Binary format (little-endian):
#   uint8   version            (1B)
#   uint8   hand               (1B, 0=left, 1=right)
#   uint16  sequence           (2B)
#   uint32  device_timestamp_ms (4B, from input.runningTime())
#   int16   ax_mg              (2B)
#   int16   ay_mg              (2B)
#   int16   az_mg              (2B)
#   int16   pitch_deg          (2B)
#   int16   roll_deg           (2B)
#   uint8   flags              (1B)
PACKET_FORMAT = "<BBH I hhh hh B"
PACKET_SIZE = struct.calcsize(PACKET_FORMAT)  # 20 bytes

HAND_MAP = {0: "left", 1: "right"}


@dataclass
class ParsedPacket:
    """A parsed micro:bit BLE sensor packet."""

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

    def to_dict(self) -> dict:
        """Convert to a plain dict for downstream consumers."""
        return {
            "device_id": self.device_id,
            "hand": self.hand,
            "version": self.version,
            "sequence": self.sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "ax_mg": self.ax_mg,
            "ay_mg": self.ay_mg,
            "az_mg": self.az_mg,
            "pitch_deg": self.pitch_deg,
            "roll_deg": self.roll_deg,
            "flags": self.flags,
            "pi_receive_timestamp_ns": self.pi_receive_timestamp_ns,
        }


class PacketParser:
    """Parses 20-byte binary BLE notification payloads from micro:bit."""

    EXPECTED_VERSION = 1

    @staticmethod
    def parse(
        device_id: str,
        expected_hand: str,
        raw_data: (bytes | bytearray),
        pi_receive_ns: int,
    ) -> ParsedPacket | None:
        """Unpack a 20-byte binary packet.

        Args:
            device_id: Logical device ID (MB_LEFT, MB_RIGHT, etc.)
            expected_hand: Expected hand label from config ("left"/"right")
            raw_data: Raw bytearray from BLE notification
            pi_receive_ns: Pi monotonic_ns timestamp when notification arrived

        Returns:
            ParsedPacket on success, None on parse failure.
        """
        if len(raw_data) != PACKET_SIZE:
            logger.warning(
                "[%s] Bad packet length: expected %d, got %d bytes. Discarding.",
                device_id,
                PACKET_SIZE,
                len(raw_data),
            )
            return None

        try:
            (
                version,
                hand_byte,
                sequence,
                device_timestamp_ms,
                ax_mg,
                ay_mg,
                az_mg,
                pitch_deg,
                roll_deg,
                flags,
            ) = struct.unpack(PACKET_FORMAT, bytes(raw_data))
        except struct.error as e:
            logger.warning("[%s] struct.unpack failed: %s", device_id, e)
            return None

        # Validate version
        if version != PacketParser.EXPECTED_VERSION:
            logger.warning(
                "[%s] Unexpected packet version %d (expected %d). Processing anyway.",
                device_id,
                version,
                PacketParser.EXPECTED_VERSION,
            )

        # Map hand byte
        hand = HAND_MAP.get(hand_byte, "unknown")
        if hand == "unknown":
            logger.warning(
                "[%s] Unknown hand byte: %d. Defaulting to 'unknown'.", device_id, hand_byte
            )
        elif hand != expected_hand:
            logger.warning(
                "[%s] Hand mismatch: packet says '%s', config says '%s'. Using packet value.",
                device_id,
                hand,
                expected_hand,
            )

        return ParsedPacket(
            device_id=device_id,
            hand=hand,
            version=version,
            sequence=sequence,
            device_timestamp_ms=device_timestamp_ms,
            ax_mg=ax_mg,
            ay_mg=ay_mg,
            az_mg=az_mg,
            pitch_deg=pitch_deg,
            roll_deg=roll_deg,
            flags=flags,
            pi_receive_timestamp_ns=pi_receive_ns,
        )

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

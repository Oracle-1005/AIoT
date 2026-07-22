"""BLE communication layer for micro:bit devices.

Packet parsing and clock sync have moved to pi_pc.  This package now
only exports BleManager (BLE connection management requiring bleak).
"""

# Re-export from pi_pc for backward compatibility
from pi_pc import PacketParser, ParsedPacket
from pi_pc.packet_parser import PACKET_SIZE
from pi_pc import ClockSync, SyncPoint

# ble_manager requires bleak — only import if available
try:
    from .ble_manager import BleManager
except ImportError:
    BleManager = None  # type: ignore

__all__ = [
    "PacketParser",
    "ParsedPacket",
    "PACKET_SIZE",
    "ClockSync",
    "SyncPoint",
    "BleManager",
]

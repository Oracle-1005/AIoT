"""BLE communication layer for micro:bit devices.

Hardware-independent modules (packet_parser, clock_sync) are imported eagerly.
Hardware-dependent modules (ble_manager, requiring bleak) are imported lazily
to allow testing on non-Linux platforms.
"""

from .packet_parser import PacketParser, ParsedPacket, PACKET_SIZE

# clock_sync requires numpy — only import if available
try:
    from .clock_sync import ClockSync, SyncPoint
except ImportError:
    ClockSync = None  # type: ignore
    SyncPoint = None  # type: ignore

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

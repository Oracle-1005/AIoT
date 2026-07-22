"""pi-pc: Raspberry Pi → PC Data Pipeline

Protocol-compliant implementation of the data processing pipeline
defined in docs/PitoPC_DataInterface_Detailed_v01.md and
docs/Microbit_to_Pi _v01.md.

Pipeline stages
---------------
1. Format conversion   — BLE binary packets → structured data
2. Noise processing    — IMU EMA/median + landmark adaptive smoothing
3. Clock synchronisation — device timestamps → Pi monotonic timeline
4. Time alignment      — bracket-search + linear interpolation to camera
5. Fusion              — multi-sensor merged frames
6. Feature extraction  — instant per-frame + sliding-window statistics
7. Message building    — fused_frame / control_event / status JSON
8. Transport           — TCP JSON Lines client to PC (port 9000)

Modules
-------
packet_parser    BLE 17-byte sensor_state binary → ParsedPacket
clock_sync       BLE SYNC/SYNC_ACK → linear regression → pi_aligned_ns
camera_clock     Camera SensorTimestamp → linear regression → pi_aligned_ns
noise_filter     MicrobitNoiseFilter (EMA+median) + LandmarkSmoother
cleaner          Sequence-gap loss detection + linear interpolation
ring_buffer      Time-sorted bounded sample buffer
aligner          Bracket-search + linear interpolation to target timestamp
engine           FusionEngine: orchestrate multi-sensor → fused_frame dict
instant          InstantFeatureComputer: per-frame accel/jerk/energy
window           SlidingWindowComputer: 800ms/100ms window statistics
schemas          JSON schema definitions and message templates
builder          MessageBuilder: add common fields + serialise
tcp_client       TcpJsonlClient: async TCP JSON Lines transport
"""

from .packet_parser import PacketParser, ParsedPacket
from .clock_sync import ClockSync, SyncPoint
from .camera_clock import CameraClockSync
from .noise_filter import (
    MicrobitNoiseFilter,
    FilteredIMUData,
    AdaptiveSmoother,
    LandmarkSmoother,
)
from .cleaner import DataCleaner
from .ring_buffer import RingBuffer, TimestampedSample
from .aligner import TimeAligner, AlignResult
from .engine import FusionEngine
from .instant import InstantFeatureComputer
from .window import SlidingWindowComputer, WindowConfig
from .schemas import (
    MESSAGE_TYPES,
    EVENT_TYPES,
    FUSED_FRAME_TEMPLATE,
    CONTROL_EVENT_TEMPLATE,
    STATUS_TEMPLATE,
)
from .builder import MessageBuilder
from .tcp_client import TcpJsonlClient

__all__ = [
    # Format conversion
    "PacketParser",
    "ParsedPacket",
    # Clock sync
    "ClockSync",
    "SyncPoint",
    "CameraClockSync",
    # Noise processing
    "MicrobitNoiseFilter",
    "FilteredIMUData",
    "AdaptiveSmoother",
    "LandmarkSmoother",
    # Data quality
    "DataCleaner",
    # Buffering & alignment
    "RingBuffer",
    "TimestampedSample",
    "TimeAligner",
    "AlignResult",
    # Fusion
    "FusionEngine",
    # Features
    "InstantFeatureComputer",
    "SlidingWindowComputer",
    "WindowConfig",
    # Messages
    "MESSAGE_TYPES",
    "EVENT_TYPES",
    "FUSED_FRAME_TEMPLATE",
    "CONTROL_EVENT_TEMPLATE",
    "STATUS_TEMPLATE",
    "MessageBuilder",
    # Transport
    "TcpJsonlClient",
]

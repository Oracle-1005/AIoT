"""fusion_pipeline: ESP32 Gateway → Pi multi-sensor fusion pipeline.

Isolated entry point for the micro:bit BLE broadcast → ESP32 UDP gateway →
Raspberry Pi camera + sensor fusion data path, per the technical document:

    hardware/raspberry_pi/MICROBIT_ESP32_CAMERA_DATA_FLOW.md

Three message types are produced and sent to PC via TCP JSON Lines:
  - fused_frame: camera-triggered synchronized sensor fusion
  - microbit_control_event: micro:bit button events (fast path, no fusion)
  - status: system health (1 Hz)
"""

from .fusion_engine import FusionEngine
from .gateway_adapter import GatewayAdapter
from .camera_adapter import CameraAdapter
from .tcp_client import TcpJsonlClient
from .schemas import (
    FUSED_FRAME_TEMPLATE,
    CONTROL_EVENT_TEMPLATE,
    STATUS_TEMPLATE,
)

__all__ = [
    "FusionEngine",
    "GatewayAdapter",
    "CameraAdapter",
    "TcpJsonlClient",
    "FUSED_FRAME_TEMPLATE",
    "CONTROL_EVENT_TEMPLATE",
    "STATUS_TEMPLATE",
]

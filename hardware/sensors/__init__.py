"""Sensor abstraction layer.

  - base.SensorSource: abstract interface
  - camera.CameraSensor: Picamera2 + MediaPipe Hand Landmarker

The old microbit.MicrobitSensor (direct BLE GATT connection) has been
removed.  micro:bit data now arrives via the ESP32 UDP gateway and is
processed by fusion_pipeline/gateway_adapter.py.
"""

from .base import SensorSource

try:
    from .camera import CameraSensor, CameraFrame
except ImportError:
    CameraSensor = None  # type: ignore[assignment]
    CameraFrame = None   # type: ignore[assignment]

__all__ = [
    "SensorSource",
    "CameraSensor",
    "CameraFrame",
]

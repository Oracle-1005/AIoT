"""Sensor abstraction layer with pluggable sensor sources.

Hardware-independent base class is imported eagerly. Hardware-dependent
sensors (BLE, camera) are imported lazily.
"""

from .base import SensorSource

try:
    from .microbit import MicrobitSensor, MicrobitSample
except ImportError:
    MicrobitSensor = None  # type: ignore
    MicrobitSample = None  # type: ignore

try:
    from .camera import CameraSensor, CameraFrame
except ImportError:
    CameraSensor = None  # type: ignore
    CameraFrame = None  # type: ignore

__all__ = [
    "SensorSource",
    "MicrobitSensor",
    "MicrobitSample",
    "CameraSensor",
    "CameraFrame",
]

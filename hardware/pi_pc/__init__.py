"""pi_pc: Retained sensor-processing modules for the fusion pipeline.

These modules are imported by sensors/camera.py and the new fusion_pipeline/:
  - noise_filter: MicrobitNoiseFilter, LandmarkSmoother, AdaptiveSmoother
  - camera_clock: CameraClockSync (SensorTimestamp → Pi monotonic_ns)
  - cleaner: DataCleaner (sequence gap detection)

All old BLE GATT pipeline modules (clock_sync, engine, aligner, etc.)
have been removed.  The new fusion pipeline lives in fusion_pipeline/.
"""

from .noise_filter import (
    MicrobitNoiseFilter,
    FilteredIMUData,
    AdaptiveSmoother,
    LandmarkSmoother,
)
from .camera_clock import CameraClockSync
from .cleaner import DataCleaner

__all__ = [
    "MicrobitNoiseFilter",
    "FilteredIMUData",
    "AdaptiveSmoother",
    "LandmarkSmoother",
    "CameraClockSync",
    "DataCleaner",
]

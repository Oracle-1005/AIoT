from __future__ import annotations

from collections import deque
from statistics import median

from .models import ClockMapping


class CameraClockMapper:
    """Map camera SensorTimestamp values onto the Pi monotonic timeline.

    The initial implementation assumes the camera timestamp and Pi monotonic
    clock run at the same rate and estimates only a robust offset.  The public
    API deliberately exposes offset, residual and readiness so that a later
    linear-regression/drift mapper can replace this class without changing the
    downstream synchronizer interface.
    """

    def __init__(self, window_size: int = 120, min_ready_samples: int = 10) -> None:
        if window_size < 1:
            raise ValueError("window_size must be positive")
        if min_ready_samples < 1:
            raise ValueError("min_ready_samples must be positive")
        self._offset_samples: deque[int] = deque(maxlen=window_size)
        self._min_ready_samples = min_ready_samples
        self._last_media_timestamp_ms = -1

    def update(self, sensor_timestamp_ns: int, pi_received_ns: int) -> ClockMapping:
        observed_offset = pi_received_ns - sensor_timestamp_ns
        self._offset_samples.append(observed_offset)
        offset_ns = int(median(self._offset_samples))
        aligned_ns = sensor_timestamp_ns + offset_ns
        residual_ns = pi_received_ns - aligned_ns
        return ClockMapping(
            pi_aligned_timestamp_ns=aligned_ns,
            offset_ns=offset_ns,
            residual_ns=residual_ns,
            sample_count=len(self._offset_samples),
            ready=len(self._offset_samples) >= self._min_ready_samples,
        )

    def media_timestamp_ms(self, sensor_timestamp_ns: int) -> int:
        """Return a strictly increasing timestamp required by MediaPipe VIDEO mode."""
        candidate = sensor_timestamp_ns // 1_000_000
        if candidate <= self._last_media_timestamp_ms:
            candidate = self._last_media_timestamp_ms + 1
        self._last_media_timestamp_ms = candidate
        return candidate

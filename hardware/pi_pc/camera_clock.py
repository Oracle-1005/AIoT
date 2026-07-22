"""Camera clock synchronization: map SensorTimestamp to Pi monotonic_ns.

Uses the same linear-regression + outlier-rejection pattern as
ble/clock_sync.py ClockSync, adapted for one-way observation:

  At each frame we observe (sensor_ts_ns, pi_receive_ns).
  Model:  pi_ns = a * sensor_ts_ns + b

The sensor timestamp and Pi monotonic clock should run at the same rate
(a ≈ 1.0) — only a constant offset (b) needs to be estimated.  Linear
regression also captures any small drift between the two clock sources.

Outlier rejection uses the observed offset (pi_receive_ns - sensor_ts_ns)
and its Median Absolute Deviation, analogous to the RTT-based outlier
rejection in BLE clock sync.
"""

from __future__ import annotations

import logging
from collections import deque
from statistics import median

import numpy as np

logger = logging.getLogger(__name__)


class CameraClockSync:
    """Map camera SensorTimestamp to Pi monotonic_ns via linear regression.

    Same pattern as ble/clock_sync.py ClockSync:
      1. Collect observation pairs (sensor_ts_ns, pi_receive_ns) per frame.
      2. Reject outliers whose offset deviates too far from the median offset.
      3. Fit linear regression:  pi_ns = a * sensor_ts_ns + b
      4. clock_ready = True after collecting enough valid points.

    Args:
        min_points: Minimum retained points before clock_ready = True.
        max_points: Maximum points to retain (oldest pruned first).
        outlier_offset_factor: Points with |offset - median_offset| >
            factor × MAD are rejected as outliers (default 3.0).
    """

    def __init__(
        self,
        min_points: int = 10,
        max_points: int = 60,
        outlier_offset_factor: float = 3.0,
    ) -> None:
        if min_points < 2:
            raise ValueError("min_points must be >= 2")
        if max_points < min_points:
            raise ValueError("max_points must be >= min_points")

        self._min_points = min_points
        self._max_points = max_points
        self._outlier_factor = outlier_offset_factor

        # Full offset history for MAD computation (bounded)
        self._offsets: deque[int] = deque(maxlen=max_points * 2)

        # Retained (sensor_ts_ns, pi_receive_ns) pairs for linear fit
        self._points: list[tuple[int, int]] = []

        # Fitted parameters: pi_ns = a * sensor_ts_ns + b
        self._a: float = 1.0
        self._b: float = 0.0
        self._ready: bool = False

        # Guard against non-monotonic sensor timestamps
        self._last_sensor_ts_ns: int = 0

        # Timestamp of last update (for should_resync)
        self._last_update_ns: int = 0

    # -- Public properties ------------------------------------------------

    @property
    def clock_ready(self) -> bool:
        """Whether enough valid points have been collected for reliable mapping."""
        return self._ready

    @property
    def slope(self) -> float:
        """Fitted clock scale (a).  pi_ns = a * sensor_ts_ns + b"""
        return self._a

    @property
    def intercept_ns(self) -> float:
        """Fitted clock offset (b) in nanoseconds."""
        return self._b

    @property
    def point_count(self) -> int:
        """Number of retained points used for the current fit."""
        return len(self._points)

    @property
    def latest_offset_ns(self) -> int | None:
        """Most recent observed offset, or None."""
        return self._offsets[-1] if self._offsets else None

    # -- Public methods ---------------------------------------------------

    def add_frame(self, sensor_ts_ns: int, pi_receive_ns: int) -> None:
        """Record one (sensor_timestamp, pi_receive_time) observation.

        Call once per captured frame, passing the raw camera SensorTimestamp
        and the Pi monotonic_ns captured immediately after the frame arrived
        in Python.

        Args:
            sensor_ts_ns: Camera SensorTimestamp from Picamera2 metadata.
            pi_receive_ns: time.monotonic_ns() recorded immediately after
                           the frame was received in Python.
        """
        observed_offset = pi_receive_ns - sensor_ts_ns
        self._offsets.append(observed_offset)

        # Sanity: sensor timestamp must be strictly increasing.
        if sensor_ts_ns <= self._last_sensor_ts_ns:
            logger.debug(
                "CameraClockSync: non-increasing sensor_ts_ns "
                "(%d <= %d), skipping frame.",
                sensor_ts_ns,
                self._last_sensor_ts_ns,
            )
            return
        self._last_sensor_ts_ns = sensor_ts_ns

        self._points.append((sensor_ts_ns, pi_receive_ns))
        self._last_update_ns = pi_receive_ns

        self._prune_oldest()
        self._prune_outliers()
        self._refit()

    def sensor_to_pi_ns(self, sensor_ts_ns: int) -> int:
        """Convert a camera SensorTimestamp to Pi monotonic_ns.

        Uses the fitted linear model when clock_ready, otherwise falls
        back to returning the raw sensor timestamp unchanged.

        Args:
            sensor_ts_ns: Camera SensorTimestamp value.

        Returns:
            Estimated Pi monotonic_ns.
        """
        if self._ready:
            return int(self._a * sensor_ts_ns + self._b)
        # Fallback: raw sensor timestamp (may be in a different clock domain
        # — caller should check clock_ready to decide whether to trust this).
        return sensor_ts_ns

    def should_resync(self, current_time_ns: int, interval_s: float = 30.0) -> bool:
        """Check whether the clock mapping should be refreshed.

        Args:
            current_time_ns: Current Pi monotonic_ns.
            interval_s: Minimum interval between resets.

        Returns:
            True if more than interval_s has passed since the last update.
        """
        if self._last_update_ns == 0:
            return False
        return (current_time_ns - self._last_update_ns) > (interval_s * 1_000_000_000)

    def reset(self) -> None:
        """Clear all observations.  Call on camera disconnect / reconfigure."""
        self._offsets.clear()
        self._points.clear()
        self._a = 1.0
        self._b = 0.0
        self._ready = False
        self._last_sensor_ts_ns = 0
        self._last_update_ns = 0
        logger.info("CameraClockSync reset.")

    # -- Internal ---------------------------------------------------------

    def _prune_oldest(self) -> None:
        """Keep at most max_points, removing oldest first."""
        while len(self._points) > self._max_points:
            self._points.pop(0)

    def _prune_outliers(self) -> None:
        """Remove points whose observed offset deviates too far from the median.

        Same principle as ClockSync's RTT-based outlier rejection:
        |offset - median_offset| > outlier_factor × MAD  →  rejected.
        """
        if len(self._offsets) < self._min_points:
            return

        med = median(self._offsets)
        abs_deviations = [abs(o - med) for o in self._offsets]
        mad = median(abs_deviations) if abs_deviations else 1.0
        if mad == 0:
            mad = 1.0  # avoid division by zero when all offsets are identical

        threshold = self._outlier_factor * mad

        before = len(self._points)
        self._points = [
            (s, p)
            for s, p in self._points
            if abs((p - s) - med) <= threshold
        ]
        removed = before - len(self._points)

        if removed > 0:
            logger.debug(
                "CameraClockSync: pruned %d outlier(s) "
                "(median_offset=%d ns, MAD=%.0f ns, threshold=%.0f ns)",
                removed,
                int(med),
                mad,
                threshold,
            )

    def _refit(self) -> bool:
        """Fit linear regression: pi_ns = a * sensor_ts_ns + b.

        Returns True if the fit succeeded.
        """
        if len(self._points) < 2:
            self._ready = False
            return False

        try:
            x = np.array([p[0] for p in self._points], dtype=np.float64)
            y = np.array([p[1] for p in self._points], dtype=np.float64)

            coeffs = np.polyfit(x, y, 1)
            self._a = float(coeffs[0])
            self._b = float(coeffs[1])

            self._ready = len(self._points) >= self._min_points

            logger.debug(
                "CameraClockSync refit: a=%.9f b=%d ns  points=%d  ready=%s",
                self._a,
                int(self._b),
                len(self._points),
                self._ready,
            )
            return True

        except Exception as exc:
            logger.warning("CameraClockSync linear fit failed: %s", exc)
            self._ready = False
            return False

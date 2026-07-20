"""Sensor noise filtering for micro:bit BLE and camera MediaPipe data.

Provides per-device, per-field noise reduction using:
  - EMA (exponential moving average) for accelerometer and orientation
  - Median filter for spike/outlier removal
  - Temporal smoothing for MediaPipe landmark coordinates
  - One-Euro filter style adaptive smoothing for velocity-dependent signals

All filters maintain per-device state and are applied immediately after
data reception, before the sample enters the ring buffer.
"""

import logging
import math
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ── EMA (Exponential Moving Average) ───────────────────────────────────────

class EMAFilter:
    """Single-pole exponential moving average (low-pass) filter.

    y[n] = alpha * y[n-1] + (1 - alpha) * x[n]

    Args:
        alpha: Smoothing factor in [0, 1]. Higher = more smoothing (slower response).
               Default 0.85 = ~6 sample effective window at 25Hz.
        init_value: Initial filter state (default 0.0).
    """

    def __init__(self, alpha: float = 0.85, init_value: float = 0.0):
        self.alpha = max(0.0, min(1.0, alpha))
        self._value = init_value
        self._initialized = False

    def update(self, value: float) -> float:
        """Apply filter to a new sample.

        Args:
            value: The raw measurement.

        Returns:
            The filtered (smoothed) value.
        """
        if not self._initialized:
            self._value = value
            self._initialized = True
        else:
            self._value = self.alpha * self._value + (1.0 - self.alpha) * value
        return self._value

    def reset(self, value: float = 0.0) -> None:
        """Reset filter state."""
        self._value = value
        self._initialized = False

    @property
    def current(self) -> float:
        return self._value


# ── Median Filter (outlier/spike removal) ──────────────────────────────────

class MedianFilter:
    """Sliding-window median filter for spike/outlier removal.

    Replaces each sample with the median of the last N samples.
    Effective at removing isolated spikes while preserving edges.

    Args:
        window_size: Number of recent samples to use (default 5, must be odd).
    """

    def __init__(self, window_size: int = 5):
        # Ensure odd window size
        self._window_size = max(3, window_size)
        if self._window_size % 2 == 0:
            self._window_size += 1
        self._buffer: deque[float] = deque(maxlen=self._window_size)

    def update(self, value: float) -> float:
        """Apply median filter to a new sample.

        Args:
            value: The raw measurement.

        Returns:
            Median of the current window.
        """
        self._buffer.append(value)
        sorted_vals = sorted(self._buffer)
        mid = len(sorted_vals) // 2
        return sorted_vals[mid]

    def reset(self) -> None:
        """Clear the filter buffer."""
        self._buffer.clear()


# ── Adaptive Smoothing (One-Euro-Filter-inspired) ──────────────────────────

class AdaptiveSmoother:
    """Adaptive temporal smoother for signals with variable rate of change.

    Inspired by the One-Euro filter: uses less smoothing when the signal
    is changing rapidly (high derivative), and more smoothing when the
    signal is near-stationary. This preserves responsiveness to gestures
    while reducing jitter during stillness.

    Args:
        beta: Derivative smoothing factor (default 0.05).
        min_cutoff_hz: Minimum cutoff frequency in Hz (default 1.0).
        speed_coefficient: How much derivative affects cutoff (default 0.5).
    """

    def __init__(
        self,
        beta: float = 0.05,
        min_cutoff_hz: float = 1.0,
        speed_coefficient: float = 0.5,
    ):
        self.beta = beta
        self.min_cutoff = min_cutoff_hz
        self.speed_coeff = speed_coefficient
        self._prev_value: float = 0.0
        self._prev_derivative: float = 0.0
        self._prev_timestamp_s: float = 0.0
        self._initialized = False

    def update(self, value: float, timestamp_s: float) -> float:
        """Apply adaptive smoothing.

        Args:
            value: Raw measurement.
            timestamp_s: Timestamp in seconds (must be monotonically increasing).

        Returns:
            Smoothed value.
        """
        if not self._initialized:
            self._prev_value = value
            self._prev_derivative = 0.0
            self._prev_timestamp_s = timestamp_s
            self._initialized = True
            return value

        dt = timestamp_s - self._prev_timestamp_s
        if dt <= 0:
            return self._prev_value

        # Estimate derivative (velocity of the signal)
        derivative = (value - self._prev_value) / dt

        # Smooth the derivative
        self._prev_derivative = (
            self.beta * derivative + (1.0 - self.beta) * self._prev_derivative
        )

        # Compute adaptive cutoff frequency
        # Higher derivative → higher cutoff → less smoothing
        speed = abs(self._prev_derivative)
        cutoff = self.min_cutoff + self.speed_coeff * speed

        # Compute smoothing factor from cutoff
        # alpha = 1 / (1 + 2*pi*cutoff*dt)
        alpha = 1.0 / (1.0 + 2.0 * math.pi * cutoff * dt)
        alpha = max(0.0, min(1.0, alpha))

        # Apply exponential smoothing with adaptive alpha
        smoothed = alpha * value + (1.0 - alpha) * self._prev_value

        self._prev_value = smoothed
        self._prev_timestamp_s = timestamp_s
        return smoothed

    def reset(self) -> None:
        """Reset smoother state."""
        self._initialized = False


# ── Per-Sensor Noise Filter ────────────────────────────────────────────────

@dataclass
class FilteredIMUData:
    """Noise-filtered IMU sensor values."""

    ax_mg: float
    ay_mg: float
    az_mg: float
    pitch_deg: float
    roll_deg: float
    acceleration_magnitude_mg: float
    # Flags
    outlier_detected: bool = False
    filtered: bool = True


class MicrobitNoiseFilter:
    """Per-device noise filter for micro:bit IMU data.

    Applies:
      - EMA low-pass to each accelerometer axis (removes high-freq vibration)
      - Median filter for outlier spike removal
      - EMA to pitch/roll (orientation changes slowly)

    Args:
        ema_alpha_accel: EMA coefficient for accelerometer (default 0.85).
        ema_alpha_orientation: EMA coefficient for pitch/roll (default 0.9).
        median_window: Window size for outlier detection (default 5).
        outlier_threshold_mg: If a raw value deviates more than this from the
            filtered value, flag it as an outlier. Default 500mg.
    """

    def __init__(
        self,
        device_id: str = "",
        ema_alpha_accel: float = 0.85,
        ema_alpha_orientation: float = 0.90,
        median_window: int = 5,
        outlier_threshold_mg: float = 500.0,
    ):
        self.device_id = device_id

        # Per-axis EMA filters
        self._ema_ax = EMAFilter(alpha=ema_alpha_accel)
        self._ema_ay = EMAFilter(alpha=ema_alpha_accel)
        self._ema_az = EMAFilter(alpha=ema_alpha_accel)

        # Orientation EMA (stronger smoothing — orientation changes slowly)
        self._ema_pitch = EMAFilter(alpha=ema_alpha_orientation)
        self._ema_roll = EMAFilter(alpha=ema_alpha_orientation)

        # Median filters for outlier detection
        self._med_ax = MedianFilter(window_size=median_window)
        self._med_ay = MedianFilter(window_size=median_window)
        self._med_az = MedianFilter(window_size=median_window)

        self._outlier_threshold_mg = outlier_threshold_mg
        self._sample_count = 0
        self._outlier_count = 0

    def filter(
        self, ax_mg: float, ay_mg: float, az_mg: float,
        pitch_deg: float, roll_deg: float,
    ) -> FilteredIMUData:
        """Apply noise filtering to raw IMU readings.

        Args:
            ax_mg, ay_mg, az_mg: Raw accelerometer values in milli-g.
            pitch_deg, roll_deg: Raw orientation angles in degrees.

        Returns:
            FilteredIMUData with smoothed values and outlier flags.
        """
        self._sample_count += 1

        # ── Step 1: Median pre-filter for outlier detection ──────────
        med_ax = self._med_ax.update(ax_mg)
        med_ay = self._med_ay.update(ay_mg)
        med_az = self._med_az.update(az_mg)

        # Check if current value is far from the local median
        outlier = False
        if self._sample_count > self._med_ax._window_size:
            if (abs(ax_mg - med_ax) > self._outlier_threshold_mg or
                    abs(ay_mg - med_ay) > self._outlier_threshold_mg or
                    abs(az_mg - med_az) > self._outlier_threshold_mg):
                outlier = True
                self._outlier_count += 1
                logger.debug(
                    "[%s] IMU outlier detected: ax=%d (med=%.0f), ay=%d (med=%.0f), az=%d (med=%.0f)",
                    self.device_id, ax_mg, med_ax, ay_mg, med_ay, az_mg, med_az,
                )

        # ── Step 2: EMA low-pass filter ──────────────────────────────
        # If outlier detected, use the median value instead of raw
        if outlier:
            filtered_ax = self._ema_ax.update(med_ax)
            filtered_ay = self._ema_ay.update(med_ay)
            filtered_az = self._ema_az.update(med_az)
        else:
            filtered_ax = self._ema_ax.update(ax_mg)
            filtered_ay = self._ema_ay.update(ay_mg)
            filtered_az = self._ema_az.update(az_mg)

        # Orientation filtering
        filtered_pitch = self._ema_pitch.update(pitch_deg)
        filtered_roll = self._ema_roll.update(roll_deg)

        # ── Step 3: Compute magnitude ────────────────────────────────
        accel_magnitude = math.sqrt(filtered_ax**2 + filtered_ay**2 + filtered_az**2)

        return FilteredIMUData(
            ax_mg=round(filtered_ax, 1),
            ay_mg=round(filtered_ay, 1),
            az_mg=round(filtered_az, 1),
            pitch_deg=round(filtered_pitch, 1),
            roll_deg=round(filtered_roll, 1),
            acceleration_magnitude_mg=round(accel_magnitude, 1),
            outlier_detected=outlier,
            filtered=True,
        )

    @property
    def outlier_ratio(self) -> float:
        if self._sample_count == 0:
            return 0.0
        return self._outlier_count / self._sample_count

    def reset(self) -> None:
        """Reset all filter states (on BLE reconnect)."""
        self._ema_ax.reset()
        self._ema_ay.reset()
        self._ema_az.reset()
        self._ema_pitch.reset()
        self._ema_roll.reset()
        self._med_ax.reset()
        self._med_ay.reset()
        self._med_az.reset()
        self._sample_count = 0
        self._outlier_count = 0
        logger.debug("[%s] Noise filter reset.", self.device_id)


# ── MediaPipe Landmark Smoother ────────────────────────────────────────────

class LandmarkSmoother:
    """Temporal smoother for MediaPipe hand landmarks.

    Reduces frame-to-frame jitter in the 21 keypoints using adaptive
    smoothing (One-Euro-filter-inspired). Each landmark coordinate
    (x, y, z) is smoothed independently.

    Args:
        min_cutoff_hz: Minimum cutoff frequency in Hz (default 1.5).
        beta: Derivative smoothing factor (default 0.05).
    """

    def __init__(self, min_cutoff_hz: float = 1.5, beta: float = 0.05):
        self._smoothers: dict[str, list[AdaptiveSmoother]] = {}  # hand_id -> [smoother_x, smoother_y, smoother_z]
        self._min_cutoff = min_cutoff_hz
        self._beta = beta

    def smooth_landmarks(
        self,
        hand_id: str,
        landmarks: list[list[float]],
        timestamp_s: float,
    ) -> list[list[float]]:
        """Apply temporal smoothing to 21 landmark coordinates.

        Args:
            hand_id: Unique hand identifier (e.g., "left-0").
            landmarks: 21 × [x, y, z] normalized coordinates.
            timestamp_s: Frame timestamp in seconds.

        Returns:
            Smoothed landmarks with the same shape.
        """
        if hand_id not in self._smoothers:
            # Initialize smoothers for this hand (21 landmarks × 3 coords each)
            self._smoothers[hand_id] = [
                AdaptiveSmoother(
                    min_cutoff_hz=self._min_cutoff,
                    beta=self._beta,
                )
                for _ in range(len(landmarks) * 3)
            ]

        smoothers = self._smoothers[hand_id]
        smoothed = []

        for i, point in enumerate(landmarks):
            base_idx = i * 3
            smoothed_point = [
                smoothers[base_idx + j].update(
                    point[j] if j < len(point) else 0.0,
                    timestamp_s,
                )
                for j in range(3)
            ]
            smoothed.append(smoothed_point)

        return smoothed

    def reset(self, hand_id: str | None = None) -> None:
        """Reset smoother state for a specific hand or all hands."""
        if hand_id is not None:
            self._smoothers.pop(hand_id, None)
        else:
            self._smoothers.clear()


# ── Factory ────────────────────────────────────────────────────────────────

def create_microbit_filter(device_id: str, cfg: dict | None = None) -> MicrobitNoiseFilter:
    """Factory: create a MicrobitNoiseFilter from config dict.

    Args:
        device_id: Logical device ID.
        cfg: Optional config override dict with keys:
            ema_alpha_accel, ema_alpha_orientation, median_window, outlier_threshold_mg.

    Returns:
        Configured MicrobitNoiseFilter.
    """
    cfg = cfg or {}
    return MicrobitNoiseFilter(
        device_id=device_id,
        ema_alpha_accel=cfg.get("ema_alpha_accel", 0.85),
        ema_alpha_orientation=cfg.get("ema_alpha_orientation", 0.90),
        median_window=cfg.get("median_window", 5),
        outlier_threshold_mg=cfg.get("outlier_threshold_mg", 500.0),
    )

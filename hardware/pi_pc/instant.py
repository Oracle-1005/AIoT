"""Instant (per-frame) feature computation.

Computes derived features from raw sensor data for each fused_frame:
- IMU features: acceleration in g, magnitude, linear acceleration (gravity
  removed), jerk, motion energy
- Camera features: wrist velocity (already computed in CameraSensor),
  acceleration, motion direction
"""

import logging
import math

logger = logging.getLogger(__name__)


class InstantFeatureComputer:
    """Computes per-frame instant features from raw BLE and camera data.

    Maintains per-device history for derivative computation (velocity,
    acceleration, jerk).

    Args:
        gravity_alpha: Low-pass filter coefficient for gravity estimation.
            Higher values = slower adaptation. Default 0.9.
    """

    def __init__(self, gravity_alpha: float = 0.9):
        self._gravity_alpha = gravity_alpha

        # Per-device state for derivative computation
        self._prev_accel: dict[str, list[float]] = {}       # [ax, ay, az] in g
        self._prev_jerk: dict[str, list[float]] = {}
        self._prev_timestamp: dict[str, int] = {}
        self._gravity_estimate: dict[str, list[float]] = {}  # Estimated gravity vector

    def compute_microbit_features(
        self,
        device_id: str,
        sample: dict,
        timestamp_ns: int,
    ) -> dict:
        """Compute instant features from raw micro:bit data.

        Args:
            device_id: Logical device ID.
            sample: Dict with ax_mg, ay_mg, az_mg, pitch_deg, roll_deg.
            timestamp_ns: Pi-aligned timestamp of this sample.

        Returns:
            Dict of instant features for fused_frame.microbits[].instant_features.
        """
        # Convert milli-g to g
        ax_g = sample.get("ax_mg", 0) / 1000.0
        ay_g = sample.get("ay_mg", 0) / 1000.0
        az_g = sample.get("az_mg", 0) / 1000.0

        acceleration_g = [ax_g, ay_g, az_g]

        # Magnitude
        acceleration_magnitude_g = math.sqrt(ax_g**2 + ay_g**2 + az_g**2)

        # Gravity estimation via low-pass filter
        if device_id not in self._gravity_estimate:
            self._gravity_estimate[device_id] = [ax_g, ay_g, az_g]
        else:
            g_est = self._gravity_estimate[device_id]
            alpha = self._gravity_alpha
            self._gravity_estimate[device_id] = [
                alpha * g_est[0] + (1 - alpha) * ax_g,
                alpha * g_est[1] + (1 - alpha) * ay_g,
                alpha * g_est[2] + (1 - alpha) * az_g,
            ]

        # Linear acceleration = raw - gravity
        grav = self._gravity_estimate[device_id]
        linear_acceleration_g = [
            ax_g - grav[0],
            ay_g - grav[1],
            az_g - grav[2],
        ]
        linear_magnitude_g = math.sqrt(
            sum(c**2 for c in linear_acceleration_g)
        )

        # Jerk = da/dt
        jerk_g_s = [0.0, 0.0, 0.0]
        jerk_magnitude_g_s = 0.0

        prev_accel = self._prev_accel.get(device_id)
        prev_ts = self._prev_timestamp.get(device_id)

        if prev_accel is not None and prev_ts is not None:
            dt_s = (timestamp_ns - prev_ts) / 1_000_000_000.0
            if dt_s > 0:
                jerk_g_s = [
                    (acceleration_g[0] - prev_accel[0]) / dt_s,
                    (acceleration_g[1] - prev_accel[1]) / dt_s,
                    (acceleration_g[2] - prev_accel[2]) / dt_s,
                ]
                jerk_magnitude_g_s = math.sqrt(sum(j**2 for j in jerk_g_s))

        # Store state for next frame
        self._prev_accel[device_id] = acceleration_g
        self._prev_jerk[device_id] = jerk_g_s
        self._prev_timestamp[device_id] = timestamp_ns

        # Motion energy (sum of squared linear accelerations, filtered)
        motion_energy = sum(c**2 for c in linear_acceleration_g)

        return {
            "acceleration_g": acceleration_g,
            "acceleration_magnitude_g": round(acceleration_magnitude_g, 4),
            "linear_acceleration_g": [round(c, 4) for c in linear_acceleration_g],
            "linear_acceleration_magnitude_g": round(linear_magnitude_g, 4),
            "jerk_g_s": [round(j, 4) for j in jerk_g_s],
            "jerk_magnitude_g_s": round(jerk_magnitude_g_s, 4),
            "motion_energy": round(motion_energy, 6),
        }

    def reset(self, device_id: str) -> None:
        """Clear history for a device (on BLE reconnect).

        Args:
            device_id: Logical device ID to reset.
        """
        self._prev_accel.pop(device_id, None)
        self._prev_jerk.pop(device_id, None)
        self._prev_timestamp.pop(device_id, None)
        self._gravity_estimate.pop(device_id, None)

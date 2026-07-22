"""Sliding window feature computation.

Aggregates fused_frame data over 800ms windows (100ms hop) and computes
statistical features for dynamic gesture recognition, BPM estimation,
and cross-modal correlation.
"""

import logging
import math
from collections import deque
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class WindowConfig:
    """Sliding window configuration."""

    duration_ms: int = 800
    hop_ms: int = 100

    @property
    def duration_ns(self) -> int:
        return self.duration_ms * 1_000_000

    @property
    def hop_ns(self) -> int:
        return self.hop_ms * 1_000_000


class SlidingWindowComputer:
    """Accumulates fused_frames and emits window_features at the hop rate.

    Maintains a deque of recent fused_frame dicts. When a new frame
    extends the window to >= duration_ms, computes statistics and emits
    a window_features dict.

    Args:
        config: WindowConfig with duration and hop parameters.
    """

    def __init__(self, config: WindowConfig | None = None):
        self._config = config or WindowConfig()
        self._frames: deque[dict] = deque()
        self._window_id = 0
        self._last_emit_end_ns: int = 0
        self._on_window: callable = None

    # ---- Public API ----

    def set_callback(self, callback) -> None:
        """Set callback for emitted window_features dicts.

        Args:
            callback: Callable(window_features_dict).
        """
        self._on_window = callback

    def add_frame(self, fused_frame: dict) -> dict | None:
        """Add a fused_frame and check if a window should be emitted.

        Args:
            fused_frame: A complete fused_frame dict.

        Returns:
            A window_features dict if a full window is available, else None.
        """
        self._frames.append(fused_frame)

        # Get timestamps
        target_ns = fused_frame.get("timestamps", {}).get(
            "fusion_target_timestamp_ns", 0
        )

        # Initialize last_emit on first frame
        if self._last_emit_end_ns == 0:
            self._last_emit_end_ns = target_ns
            return None

        # Check if window span >= duration
        window_start_ns = self._last_emit_end_ns
        window_end_ns = target_ns
        window_span_ns = window_end_ns - window_start_ns

        if window_span_ns < self._config.duration_ns:
            return None

        # Enough data: compute window
        result = self._compute_window(window_start_ns, window_end_ns)
        self._window_id += 1
        self._last_emit_end_ns = window_start_ns + self._config.hop_ns

        # Prune old frames
        self._prune(window_start_ns)

        # Emit via callback
        if self._on_window and result:
            self._on_window(result)

        return result

    # ---- Internal: Window Computation ----

    def _compute_window(self, start_ns: int, end_ns: int) -> dict:
        """Compute all window features for fused frames in [start_ns, end_ns].

        Args:
            start_ns: Window start time (Pi monotonic_ns).
            end_ns: Window end time.

        Returns:
            A window_features dict following the document schema.
        """
        # Filter frames in window
        window_frames = [
            f for f in self._frames
            if start_ns <= f.get("timestamps", {}).get("fusion_target_timestamp_ns", 0) <= end_ns
        ]

        camera_frame_count = len(window_frames)
        expected_camera_count = int(self._config.duration_ms / 1000.0 * 30)  # ~24 at 30fps

        # Source summary
        source_summary = self._compute_source_summary(
            window_frames, camera_frame_count, expected_camera_count
        )

        # Camera features per hand
        camera_features = self._compute_camera_features(window_frames)

        # Micro:bit features per hand
        microbit_features = self._compute_microbit_features(window_frames)

        # Cross-modal features
        cross_modal = self._compute_cross_modal(
            window_frames, camera_features, microbit_features
        )

        # Quality
        quality = self._compute_quality(
            source_summary, camera_frame_count, expected_camera_count
        )

        # Center timestamp
        center_ns = (start_ns + end_ns) // 2

        return {
            "window": {
                "window_id": self._window_id,
                "start_timestamp_ns": start_ns,
                "end_timestamp_ns": end_ns,
                "center_timestamp_ns": center_ns,
                "duration_ms": self._config.duration_ms,
                "hop_ms": self._config.hop_ms,
            },
            "source_summary": source_summary,
            "camera_features": camera_features,
            "microbit_features": microbit_features,
            "cross_modal_features": cross_modal,
            "quality": quality,
        }

    def _compute_source_summary(
        self, frames: list[dict], camera_count: int, expected: int
    ) -> dict:
        """Compute data quality summary for the window."""
        left_ble_count = 0
        right_ble_count = 0
        sync_errors = []

        for f in frames:
            for mb in f.get("microbits", []):
                if mb.get("hand") == "left" and mb.get("valid"):
                    left_ble_count += 1
                elif mb.get("hand") == "right" and mb.get("valid"):
                    right_ble_count += 1

                sync = mb.get("sync", {})
                err = sync.get("nearest_sample_error_ms", 0)
                if err > 0:
                    sync_errors.append(err)

        mean_sync = sum(sync_errors) / len(sync_errors) if sync_errors else 0.0
        max_sync = max(sync_errors) if sync_errors else 0.0

        return {
            "camera_frame_count": camera_count,
            "camera_expected_count": expected,
            "camera_missing_ratio": round(
                1.0 - camera_count / max(expected, 1), 4
            ),
            "left_ble_sample_count": left_ble_count,
            "right_ble_sample_count": right_ble_count,
            "mean_sync_error_ms": round(mean_sync, 1),
            "max_sync_error_ms": round(max_sync, 1),
        }

    def _compute_camera_features(self, frames: list[dict]) -> dict:
        """Compute per-hand camera statistics over the window."""
        per_hand: dict[str, list[dict]] = {}

        # Collect per-hand data
        for f in frames:
            for hand_data in f.get("camera", {}).get("hands", []):
                hand_id = hand_data.get("handedness", "unknown")
                if hand_id not in per_hand:
                    per_hand[hand_id] = []
                per_hand[hand_id].append(hand_data)

        result = {}
        for hand_label in ("left", "right"):
            hand_frames = per_hand.get(hand_label, [])

            if not hand_frames:
                result[f"{hand_label}_hand"] = {
                    "trajectory_length": 0.0,
                    "displacement": 0.0,
                    "mean_wrist_speed": 0.0,
                    "max_wrist_speed": 0.0,
                    "mean_wrist_acceleration": 0.0,
                    "vertical_range": 0.0,
                    "horizontal_range": 0.0,
                    "direction_changes": 0,
                    "mean_openness": 0.0,
                    "openness_change": 0.0,
                }
                continue

            # Wrist positions over time
            wrist_positions = []
            for hf in hand_frames:
                feat = hf.get("features", {})
                wp = feat.get("wrist_position")
                if wp and len(wp) >= 2:
                    wrist_positions.append((wp[0], wp[1]))

            # Wrist speeds
            speeds = []
            velocities = []
            for hf in hand_frames:
                feat = hf.get("features", {})
                v = feat.get("wrist_velocity", [0, 0, 0])
                if isinstance(v, list) and len(v) >= 2:
                    speed = math.sqrt(v[0]**2 + v[1]**2)
                    speeds.append(speed)
                    velocities.append(v)

            # Trajectory length
            traj_len = 0.0
            for i in range(1, len(wrist_positions)):
                dx = wrist_positions[i][0] - wrist_positions[i-1][0]
                dy = wrist_positions[i][1] - wrist_positions[i-1][1]
                traj_len += math.sqrt(dx**2 + dy**2)

            # Displacement (net)
            displacement = 0.0
            if len(wrist_positions) >= 2:
                dx = wrist_positions[-1][0] - wrist_positions[0][0]
                dy = wrist_positions[-1][1] - wrist_positions[0][1]
                displacement = math.sqrt(dx**2 + dy**2)

            # Vertical/horizontal range
            if wrist_positions:
                x_vals = [p[0] for p in wrist_positions]
                y_vals = [p[1] for p in wrist_positions]
                horizontal_range = max(x_vals) - min(x_vals)
                vertical_range = max(y_vals) - min(y_vals)
            else:
                horizontal_range = 0.0
                vertical_range = 0.0

            # Direction changes
            dir_changes = 0
            if len(velocities) >= 2:
                for i in range(1, len(velocities)):
                    dot = (
                        velocities[i][0] * velocities[i-1][0]
                        + velocities[i][1] * velocities[i-1][1]
                    )
                    # Sign change in dot product indicates direction reversal
                    speed_i = math.sqrt(velocities[i][0]**2 + velocities[i][1]**2)
                    speed_prev = math.sqrt(velocities[i-1][0]**2 + velocities[i-1][1]**2)
                    if speed_i > 0.01 and speed_prev > 0.01 and dot < 0:
                        dir_changes += 1

            # Openness
            openness_vals = [
                hf.get("features", {}).get("openness", 0)
                for hf in hand_frames
            ]

            result[f"{hand_label}_hand"] = {
                "trajectory_length": round(traj_len, 4),
                "displacement": round(displacement, 4),
                "mean_wrist_speed": round(sum(speeds) / len(speeds), 4) if speeds else 0.0,
                "max_wrist_speed": round(max(speeds), 4) if speeds else 0.0,
                "mean_wrist_acceleration": 0.0,  # Computed from velocity diffs if needed
                "vertical_range": round(vertical_range, 4),
                "horizontal_range": round(horizontal_range, 4),
                "direction_changes": dir_changes,
                "mean_openness": (
                    round(sum(openness_vals) / len(openness_vals), 4)
                    if openness_vals else 0.0
                ),
                "openness_change": (
                    round(openness_vals[-1] - openness_vals[0], 4)
                    if len(openness_vals) >= 2 else 0.0
                ),
            }

        return result

    def _compute_microbit_features(self, frames: list[dict]) -> dict:
        """Compute per-hand micro:bit statistics over the window."""
        per_hand: dict[str, list[dict]] = {}

        for f in frames:
            for mb in f.get("microbits", []):
                if not mb.get("valid"):
                    continue
                hand = mb.get("hand", "unknown")
                if hand not in per_hand:
                    per_hand[hand] = []
                per_hand[hand].append(mb)

        result = {}
        for hand_label in ("left", "right"):
            mb_frames = per_hand.get(hand_label, [])

            if not mb_frames:
                result[f"{hand_label}_hand"] = self._empty_microbit_features()
                continue

            # Collect instant features
            accel_mags = []
            linear_mags = []
            jerk_mags = []
            motion_energies = []
            pitch_vals = []
            roll_vals = []
            timestamps = []

            for mb_f in mb_frames:
                feat = mb_f.get("instant_features", {})
                accel_mags.append(feat.get("acceleration_magnitude_g", 0))
                linear_mags.append(feat.get("linear_acceleration_magnitude_g", 0))
                jerk_mags.append(feat.get("jerk_magnitude_g_s", 0))
                motion_energies.append(feat.get("motion_energy", 0))

                raw = mb_f.get("raw_interpolated", {})
                pitch_vals.append(raw.get("pitch_deg", 0))
                roll_vals.append(raw.get("roll_deg", 0))
                timestamps.append(
                    mb_f.get("timestamps", {}).get("pi_aligned_timestamp_ns", 0)
                )

            n = len(accel_mags)

            # Peak detection
            peaks = self._detect_peaks(accel_mags, timestamps, min_height=0.3, min_distance_ms=200)

            # Dominant frequency via zero-crossing rate
            dom_freq = self._dominant_frequency(accel_mags) if n >= 5 else 0.0

            result[f"{hand_label}_hand"] = {
                "mean_acceleration_magnitude_g": round(sum(accel_mags) / n, 4),
                "std_acceleration_magnitude_g": round(self._std(accel_mags), 4),
                "max_acceleration_magnitude_g": round(max(accel_mags), 4),
                "mean_linear_magnitude_g": round(sum(linear_mags) / n, 4),
                "max_linear_magnitude_g": round(max(linear_mags), 4) if linear_mags else 0.0,
                "rms_linear_magnitude_g": round(
                    math.sqrt(sum(x**2 for x in linear_mags) / n), 4
                ) if n > 0 else 0.0,
                "motion_energy": round(sum(motion_energies), 6),
                "mean_jerk_g_s": round(sum(jerk_mags) / n, 4),
                "max_jerk_g_s": round(max(jerk_mags), 4) if jerk_mags else 0.0,
                "peak_count": len(peaks),
                "peak_timestamps_ns": peaks,
                "dominant_frequency_hz": round(dom_freq, 2),
                "mean_pitch_deg": round(sum(pitch_vals) / n, 2),
                "std_pitch_deg": round(self._std(pitch_vals), 2),
                "mean_roll_deg": round(sum(roll_vals) / n, 2),
                "std_roll_deg": round(self._std(roll_vals), 2),
            }

        return result

    def _compute_cross_modal(
        self,
        frames: list[dict],
        camera_features: dict,
        microbit_features: dict,
    ) -> dict:
        """Compute cross-modal correlation features."""
        # Collect vision speed and IMU magnitude pairs per hand
        left_vision = []
        left_imu = []
        right_vision = []
        right_imu = []

        for f in frames:
            for hand_data in f.get("camera", {}).get("hands", []):
                h = hand_data.get("handedness", "")
                feat = hand_data.get("features", {})
                v = feat.get("wrist_velocity", [0, 0, 0])
                speed = math.sqrt(v[0]**2 + v[1]**2) if isinstance(v, list) and len(v) >= 2 else 0
                if h == "left":
                    left_vision.append(speed)
                elif h == "right":
                    right_vision.append(speed)

            for mb in f.get("microbits", []):
                if not mb.get("valid"):
                    continue
                h = mb.get("hand", "")
                feat = mb.get("instant_features", {})
                mag = feat.get("linear_acceleration_magnitude_g", 0)
                if h == "left":
                    left_imu.append(mag)
                elif h == "right":
                    right_imu.append(mag)

        # Compute per-hand correlations
        left_corr = self._pearson_r(left_vision, left_imu)
        right_corr = self._pearson_r(right_vision, right_imu)
        left_right_corr = self._pearson_r(left_imu, right_imu)

        # BPM estimation from peak intervals
        all_peaks = []
        for f in frames:
            for mb in f.get("microbits", []):
                feat = mb.get("instant_features", {})
                if feat.get("jerk_magnitude_g_s", 0) > 5.0:
                    ts = mb.get("timestamps", {}).get("pi_aligned_timestamp_ns", 0)
                    all_peaks.append(ts)

        estimated_bpm = 0.0
        if len(all_peaks) >= 2:
            all_peaks.sort()
            intervals_ms = [
                (all_peaks[i] - all_peaks[i-1]) / 1_000_000.0
                for i in range(1, len(all_peaks))
            ]
            if intervals_ms:
                mean_interval = sum(intervals_ms) / len(intervals_ms)
                if mean_interval > 0:
                    estimated_bpm = 60000.0 / mean_interval

        # Combined motion intensity
        left_intensity = microbit_features.get("left_hand", {}).get("motion_energy", 0)
        right_intensity = microbit_features.get("right_hand", {}).get("motion_energy", 0)
        combined_intensity = left_intensity + right_intensity

        return {
            "left_visual_imu_correlation": round(left_corr, 4),
            "right_visual_imu_correlation": round(right_corr, 4),
            "left_right_motion_correlation": round(left_right_corr, 4),
            "visual_imu_peak_offset_ms": 0.0,
            "beat_interval_ms": 0.0,
            "estimated_bpm": round(estimated_bpm, 1),
            "combined_motion_intensity": round(combined_intensity, 4),
        }

    def _compute_quality(
        self, source_summary: dict, actual: int, expected: int
    ) -> dict:
        """Compute window quality metrics."""
        coverage = actual / max(expected, 1)
        valid = coverage >= 0.8

        reason = None
        if not valid:
            if coverage < 0.8:
                reason = "camera_missing"
            elif source_summary.get("mean_sync_error_ms", 0) > 50:
                reason = "sync_error_too_large"
            else:
                reason = "insufficient_samples"

        return {
            "valid": valid,
            "window_coverage_ratio": round(coverage, 4),
            "reason": reason,
        }

    # ---- Internal: Statistics Helpers ----

    @staticmethod
    def _std(values: list[float]) -> float:
        """Compute population standard deviation."""
        if len(values) < 2:
            return 0.0
        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        return math.sqrt(variance)

    @staticmethod
    def _pearson_r(x: list[float], y: list[float]) -> float:
        """Compute Pearson correlation coefficient.

        Truncates the longer list to match the shorter one.
        """
        n = min(len(x), len(y))
        if n < 3:
            return 0.0

        x = x[:n]
        y = y[:n]

        mean_x = sum(x) / n
        mean_y = sum(y) / n

        cov = sum((x[i] - mean_x) * (y[i] - mean_y) for i in range(n))
        std_x = math.sqrt(sum((xi - mean_x) ** 2 for xi in x))
        std_y = math.sqrt(sum((yi - mean_y) ** 2 for yi in y))

        if std_x == 0 or std_y == 0:
            return 0.0

        return cov / (std_x * std_y)

    @staticmethod
    def _detect_peaks(
        values: list[float],
        timestamps: list[int],
        min_height: float = 0.3,
        min_distance_ms: float = 200,
    ) -> list[int]:
        """Simple local-maximum peak detection.

        Args:
            values: Signal values.
            timestamps: Corresponding timestamps in ns.
            min_height: Minimum peak height.
            min_distance_ms: Minimum distance between peaks in ms.

        Returns:
            List of timestamps (ns) for detected peaks.
        """
        if len(values) < 3:
            return []

        min_distance_ns = min_distance_ms * 1_000_000
        peaks = []

        for i in range(1, len(values) - 1):
            if values[i] > values[i - 1] and values[i] > values[i + 1]:
                if values[i] >= min_height:
                    # Check minimum distance from last peak
                    ts = timestamps[i] if i < len(timestamps) else 0
                    if not peaks or (ts - peaks[-1] >= min_distance_ns):
                        peaks.append(ts)

        return peaks

    @staticmethod
    def _dominant_frequency(values: list[float]) -> float:
        """Estimate dominant frequency via zero-crossing rate.

        Args:
            values: Signal values.

        Returns:
            Estimated frequency in Hz, or 0 if insufficient data.
        """
        if len(values) < 3:
            return 0.0

        # Remove mean
        mean = sum(values) / len(values)
        centered = [v - mean for v in values]

        # Count zero crossings
        crossings = 0
        for i in range(1, len(centered)):
            if centered[i - 1] * centered[i] < 0:
                crossings += 1

        # Frequency = crossings / (2 * duration)
        # Assuming 25Hz sample rate for the window
        if crossings < 2:
            return 0.0

        # Approximate: for N samples at 25Hz, duration = N/25 sec
        # Frequency = crossings / (2 * duration) = crossings * 25 / (2 * N)
        return (crossings * 25.0) / (2.0 * len(centered))

    # ---- Internal: Helpers ----

    def _empty_microbit_features(self) -> dict:
        """Return an empty microbit features dict."""
        return {
            "mean_acceleration_magnitude_g": 0.0,
            "std_acceleration_magnitude_g": 0.0,
            "max_acceleration_magnitude_g": 0.0,
            "mean_linear_magnitude_g": 0.0,
            "max_linear_magnitude_g": 0.0,
            "rms_linear_magnitude_g": 0.0,
            "motion_energy": 0.0,
            "mean_jerk_g_s": 0.0,
            "max_jerk_g_s": 0.0,
            "peak_count": 0,
            "peak_timestamps_ns": [],
            "dominant_frequency_hz": 0.0,
            "mean_pitch_deg": 0.0,
            "std_pitch_deg": 0.0,
            "mean_roll_deg": 0.0,
            "std_roll_deg": 0.0,
        }

    def _prune(self, before_ns: int) -> int:
        """Remove frames older than before_ns."""
        count = 0
        while self._frames:
            ts = self._frames[0].get("timestamps", {}).get("fusion_target_timestamp_ns", 0)
            if ts < before_ns:
                self._frames.popleft()
                count += 1
            else:
                break
        return count

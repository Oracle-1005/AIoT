"""
Camera Feature Extractor
========================
Extracts conducting-relevant features from MediaPipe Hand Landmarks.

Input:  List of landmark frames (21 keypoints × 3 coords per frame)
Output: Feature vector per sliding window

Features (25 dimensions):
  Position (6):  centroid_x_mean, centroid_x_std, centroid_y_mean, centroid_y_std,
                 centroid_z_mean, centroid_z_std
  Motion (4):    velocity_x_mean, velocity_y_mean, velocity_std,
                 acceleration_mean
  Shape (4):     spread_mean, spread_std, thumb_index_dist_mean, thumb_index_dist_std
  Vertical (3):  vertical_range, vertical_travel, vertical_speed
  Temporal (3):  hand_presence_ratio, num_hands_avg, num_hands_max
  Direction (3): dir_change_count, palm_x_mean, palm_y_mean
  Rhythm (2):    beat_phase, peak_count
"""

import math
import numpy as np
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class CameraFeatureVector:
    """Extracted camera features for one window"""
    # Position (6)
    centroid_x_mean: float = 0.0
    centroid_x_std: float = 0.0
    centroid_y_mean: float = 0.0
    centroid_y_std: float = 0.0
    centroid_z_mean: float = 0.0
    centroid_z_std: float = 0.0

    # Motion (4)
    velocity_x_mean: float = 0.0
    velocity_y_mean: float = 0.0
    velocity_std: float = 0.0
    acceleration_mean: float = 0.0

    # Shape (4)
    spread_mean: float = 0.0
    spread_std: float = 0.0
    thumb_index_dist_mean: float = 0.0
    thumb_index_dist_std: float = 0.0

    # Vertical (3)
    vertical_range: float = 0.0
    vertical_travel: float = 0.0
    vertical_speed: float = 0.0

    # Temporal (3)
    hand_presence_ratio: float = 0.0
    num_hands_avg: float = 0.0
    num_hands_max: int = 0

    # Direction (3)
    dir_change_count: int = 0
    palm_x_mean: float = 0.0
    palm_y_mean: float = 0.0

    # Rhythm (2)
    beat_phase: float = 0.0
    peak_count: int = 0

    def to_list(self) -> list[float]:
        """Flatten to feature vector"""
        return [
            self.centroid_x_mean, self.centroid_x_std,
            self.centroid_y_mean, self.centroid_y_std,
            self.centroid_z_mean, self.centroid_z_std,
            self.velocity_x_mean, self.velocity_y_mean,
            self.velocity_std, self.acceleration_mean,
            self.spread_mean, self.spread_std,
            self.thumb_index_dist_mean, self.thumb_index_dist_std,
            self.vertical_range, self.vertical_travel,
            self.vertical_speed,
            self.hand_presence_ratio,
            self.num_hands_avg, float(self.num_hands_max),
            float(self.dir_change_count),
            self.palm_x_mean, self.palm_y_mean,
            self.beat_phase, float(self.peak_count),
        ]

    @staticmethod
    def feature_names() -> list[str]:
        return [
            'cam_centroid_x_mean', 'cam_centroid_x_std',
            'cam_centroid_y_mean', 'cam_centroid_y_std',
            'cam_centroid_z_mean', 'cam_centroid_z_std',
            'cam_velocity_x_mean', 'cam_velocity_y_mean',
            'cam_velocity_std', 'cam_acceleration_mean',
            'cam_spread_mean', 'cam_spread_std',
            'cam_thumb_index_dist_mean', 'cam_thumb_index_dist_std',
            'cam_vertical_range', 'cam_vertical_travel',
            'cam_vertical_speed',
            'cam_hand_presence_ratio',
            'cam_num_hands_avg', 'cam_num_hands_max',
            'cam_dir_change_count',
            'cam_palm_x_mean', 'cam_palm_y_mean',
            'cam_beat_phase', 'cam_peak_count',
        ]


class CameraFeatureExtractor:
    """Extract conducting features from MediaPipe hand landmark frames"""

    def __init__(self):
        self.reset()

    def reset(self):
        self._centroids: list[tuple] = []
        self._velocities: list[tuple] = []
        self._spreads: list[float] = []
        self._thumb_index_dists: list[float] = []
        self._num_hands: list[int] = []
        self._palm_positions: list[tuple] = []
        self._prev_centroid: Optional[tuple] = None
        self._prev_velocity: Optional[tuple] = None

    @staticmethod
    def _hand_centroid(landmarks) -> tuple:
        """Calculate hand centroid from flattened landmarks [x0,y0,z0, x1,y1,z1, ...]"""
        n = len(landmarks) // 3
        if n == 0:
            return (0.0, 0.0, 0.0)
        xs = landmarks[0::3]
        ys = landmarks[1::3]
        zs = landmarks[2::3]
        return (sum(xs) / n, sum(ys) / n, sum(zs) / n)

    @staticmethod
    def _hand_spread(landmarks) -> float:
        """Calculate finger spread (average distance from centroid)"""
        cx, cy, cz = CameraFeatureExtractor._hand_centroid(landmarks)
        n = len(landmarks) // 3
        if n == 0:
            return 0.0
        dists = []
        for i in range(n):
            dx = landmarks[i*3] - cx
            dy = landmarks[i*3+1] - cy
            dists.append(math.sqrt(dx*dx + dy*dy))
        return sum(dists) / n

    @staticmethod
    def _thumb_index_distance(landmarks) -> float:
        """Distance between thumb tip (4) and index finger tip (8)"""
        n = len(landmarks) // 3
        if n < 9:
            return 0.0
        t4_x, t4_y = landmarks[12], landmarks[13]
        t8_x, t8_y = landmarks[24], landmarks[25]
        return math.sqrt((t4_x - t8_x)**2 + (t4_y - t8_y)**2)

    @staticmethod
    def _palm_center(landmarks) -> tuple:
        """Palm center (wrist + middle finger base midpoint)"""
        n = len(landmarks) // 3
        if n < 1:
            return (0.0, 0.0)
        wrist_x = landmarks[0]
        wrist_y = landmarks[1]
        if n > 9:
            mf_x = landmarks[27]
            mf_y = landmarks[28]
            return ((wrist_x + mf_x) / 2, (wrist_y + mf_y) / 2)
        return (wrist_x, wrist_y)

    def add_frame(self, hands: list[list[float]]):
        """Process one frame of hand landmarks (list of hand landmark lists)"""
        if not hands:
            # No hands detected
            self._num_hands.append(0)
            self._prev_centroid = None
            self._prev_velocity = None
            return

        # Use the first (largest/most confident) hand
        landmarks = hands[0]
        self._num_hands.append(len(hands))

        # Centroid
        centroid = self._hand_centroid(landmarks)
        self._centroids.append(centroid)

        # Velocity
        if self._prev_centroid is not None:
            vx = centroid[0] - self._prev_centroid[0]
            vy = centroid[1] - self._prev_centroid[1]
            self._velocities.append((vx, vy))
        self._prev_centroid = centroid

        # Spread
        self._spreads.append(self._hand_spread(landmarks))

        # Thumb-index distance
        self._thumb_index_dists.append(self._thumb_index_distance(landmarks))

        # Palm position
        self._palm_positions.append(self._palm_center(landmarks))

    def extract(self, fps: float = 30.0) -> CameraFeatureVector:
        """Extract features from accumulated frames"""
        fv = CameraFeatureVector()
        n = len(self._centroids)

        if n == 0:
            return fv

        centroids_x = [c[0] for c in self._centroids]
        centroids_y = [c[1] for c in self._centroids]
        centroids_z = [c[2] for c in self._centroids]

        # Position features
        fv.centroid_x_mean = float(np.mean(centroids_x))
        fv.centroid_x_std = float(np.std(centroids_x))
        fv.centroid_y_mean = float(np.mean(centroids_y))
        fv.centroid_y_std = float(np.std(centroids_y))
        fv.centroid_z_mean = float(np.mean(centroids_z))
        fv.centroid_z_std = float(np.std(centroids_z))

        # Motion features
        if self._velocities:
            vx = [v[0] for v in self._velocities]
            vy = [v[1] for v in self._velocities]
            fv.velocity_x_mean = float(np.mean(vx))
            fv.velocity_y_mean = float(np.mean(vy))

            # Velocity magnitude
            v_mag = [math.sqrt(v[0]**2 + v[1]**2) for v in self._velocities]
            fv.velocity_std = float(np.std(v_mag))

            # Acceleration (derivative of velocity)
            if len(v_mag) >= 2:
                acc = [v_mag[i+1] - v_mag[i] for i in range(len(v_mag)-1)]
                fv.acceleration_mean = float(np.mean([abs(a) for a in acc]))
            else:
                fv.acceleration_mean = 0.0
        else:
            fv.velocity_std = 0.0
            fv.acceleration_mean = 0.0

        # Shape features
        if self._spreads:
            fv.spread_mean = float(np.mean(self._spreads))
            fv.spread_std = float(np.std(self._spreads))
        if self._thumb_index_dists:
            fv.thumb_index_dist_mean = float(np.mean(self._thumb_index_dists))
            fv.thumb_index_dist_std = float(np.std(self._thumb_index_dists))

        # Vertical features (y-axis in mediapipe, 0=top, 1=bottom)
        if centroids_y:
            fv.vertical_range = float(max(centroids_y) - min(centroids_y))
            fv.vertical_travel = float(sum(abs(centroids_y[i+1] - centroids_y[i])
                                        for i in range(len(centroids_y)-1)))
            fv.vertical_speed = fv.vertical_travel / (n / fps) if fps > 0 else 0.0

        # Temporal features
        if self._num_hands:
            fv.hand_presence_ratio = sum(1 for h in self._num_hands if h > 0) / len(self._num_hands)
            fv.num_hands_avg = float(np.mean(self._num_hands))
            fv.num_hands_max = max(self._num_hands)

        # Direction features
        if self._velocities:
            vx_arr = [v[0] for v in self._velocities]
            # Count direction changes (sign flips in velocity_x)
            signs = [1 if x > 0 else (-1 if x < 0 else 0) for x in vx_arr]
            signs = [s for s in signs if s != 0]
            if len(signs) >= 2:
                fv.dir_change_count = sum(1 for i in range(len(signs)-1) if signs[i] != signs[i+1])

        # Palm features
        if self._palm_positions:
            fv.palm_x_mean = float(np.mean([p[0] for p in self._palm_positions]))
            fv.palm_y_mean = float(np.mean([p[1] for p in self._palm_positions]))

        # Rhythm: beat_phase (normalized vertical position in beat cycle)
        if centroids_y:
            y_range = max(centroids_y) - min(centroids_y)
            if y_range > 0.001:
                fv.beat_phase = (centroids_y[-1] - min(centroids_y)) / y_range

        # Peak count: significant direction reversals in y-axis
        if len(centroids_y) >= 3:
            peaks = 0
            for i in range(1, len(centroids_y) - 1):
                if (centroids_y[i] > centroids_y[i-1] and centroids_y[i] > centroids_y[i+1]) or \
                   (centroids_y[i] < centroids_y[i-1] and centroids_y[i] < centroids_y[i+1]):
                    peaks += 1
            fv.peak_count = peaks

        return fv

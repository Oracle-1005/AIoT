"""
Accelerometer Feature Extractor
===============================
Extracts conducting-relevant features from Micro:bit accelerometer data.

Input:  List of AccelSample objects for one sliding window
Output: Feature vector

Features (18 dimensions):
  Magnitude (4):  acc_norm_mean, acc_norm_std, acc_norm_min, acc_norm_max
  Per-axis (6):   acc_x_mean/std, acc_y_mean/std, acc_z_mean/std
  Jerk (2):       mean_jerk, max_jerk
  Orientation (2): dominant_axis, tilt_angle
  Energy (2):     signal_energy, rms
  Rhythm (2):     peak_count, zero_crossing_rate
"""

import math
import numpy as np
from dataclasses import dataclass
from typing import Optional
from microbit_receiver import AccelSample


@dataclass
class AccelFeatureVector:
    """Extracted accelerometer features for one window"""

    # Magnitude (4)
    acc_norm_mean: float = 0.0
    acc_norm_std: float = 0.0
    acc_norm_min: float = 0.0
    acc_norm_max: float = 0.0

    # Per-axis (6)
    acc_x_mean: float = 0.0
    acc_x_std: float = 0.0
    acc_y_mean: float = 0.0
    acc_y_std: float = 0.0
    acc_z_mean: float = 0.0
    acc_z_std: float = 0.0

    # Jerk (2) — derivative of acceleration
    mean_jerk: float = 0.0
    max_jerk: float = 0.0

    # Orientation (2)
    dominant_axis: int = 0    # 0=x, 1=y, 2=z
    tilt_angle: float = 0.0   # tilt from vertical (degrees)

    # Energy (2)
    signal_energy: float = 0.0
    rms: float = 0.0

    # Rhythm (2)
    peak_count: int = 0
    zero_crossing_rate: float = 0.0

    @staticmethod
    def feature_names() -> list[str]:
        return [
            'acc_norm_mean', 'acc_norm_std', 'acc_norm_min', 'acc_norm_max',
            'acc_x_mean', 'acc_x_std', 'acc_y_mean', 'acc_y_std',
            'acc_z_mean', 'acc_z_std',
            'acc_mean_jerk', 'acc_max_jerk',
            'acc_dominant_axis', 'acc_tilt_angle',
            'acc_signal_energy', 'acc_rms',
            'acc_peak_count', 'acc_zero_crossing_rate',
        ]

    def to_list(self) -> list[float]:
        return [
            self.acc_norm_mean, self.acc_norm_std,
            self.acc_norm_min, self.acc_norm_max,
            self.acc_x_mean, self.acc_x_std,
            self.acc_y_mean, self.acc_y_std,
            self.acc_z_mean, self.acc_z_std,
            self.mean_jerk, self.max_jerk,
            float(self.dominant_axis),
            self.tilt_angle,
            self.signal_energy, self.rms,
            float(self.peak_count),
            self.zero_crossing_rate,
        ]


class AccelFeatureExtractor:
    """Extract conducting features from Micro:bit accelerometer data"""

    def __init__(self):
        self.reset()

    def reset(self):
        self._samples: list[AccelSample] = []

    def add_sample(self, sample: AccelSample):
        self._samples.append(sample)

    def add_samples(self, samples: list[AccelSample]):
        self._samples.extend(samples)

    def extract(self) -> AccelFeatureVector:
        """Extract features from accumulated samples"""
        fv = AccelFeatureVector()
        n = len(self._samples)

        if n == 0:
            return fv

        # Raw arrays
        x_arr = np.array([s.acc_x for s in self._samples])
        y_arr = np.array([s.acc_y for s in self._samples])
        z_arr = np.array([s.acc_z for s in self._samples])
        norm_arr = np.array([s.acc_norm for s in self._samples])

        # Magnitude features
        fv.acc_norm_mean = float(np.mean(norm_arr))
        fv.acc_norm_std = float(np.std(norm_arr))
        fv.acc_norm_min = float(np.min(norm_arr))
        fv.acc_norm_max = float(np.max(norm_arr))

        # Per-axis features
        fv.acc_x_mean = float(np.mean(x_arr))
        fv.acc_x_std = float(np.std(x_arr))
        fv.acc_y_mean = float(np.mean(y_arr))
        fv.acc_y_std = float(np.std(y_arr))
        fv.acc_z_mean = float(np.mean(z_arr))
        fv.acc_z_std = float(np.std(z_arr))

        # Jerk — difference of norm between consecutive samples
        if n >= 2:
            jerk = np.abs(np.diff(norm_arr))
            fv.mean_jerk = float(np.mean(jerk))
            fv.max_jerk = float(np.max(jerk))

        # Dominant axis — which axis has the highest variance
        variances = [np.var(x_arr), np.var(y_arr), np.var(z_arr)]
        fv.dominant_axis = int(np.argmax(variances))

        # Tilt angle from vertical (z-axis)
        mean_x, mean_y, mean_z = fv.acc_x_mean, fv.acc_y_mean, fv.acc_z_mean
        # Angle between acceleration vector and vertical (0,0,1000)
        vertical_norm = 1000.0  # 1g in mg
        acc_mag = math.sqrt(mean_x**2 + mean_y**2 + mean_z**2)
        if acc_mag > 0:
            cos_theta = mean_z / acc_mag
            cos_theta = max(-1.0, min(1.0, cos_theta))
            fv.tilt_angle = float(math.degrees(math.acos(cos_theta)))

        # Energy
        fv.signal_energy = float(np.sum(norm_arr ** 2))
        fv.rms = float(math.sqrt(np.mean(norm_arr ** 2)))

        # Peak count — significant local maxima in norm (threshold: mean + 0.5*std)
        threshold = fv.acc_norm_mean + 0.5 * fv.acc_norm_std
        if n >= 3:
            peaks = 0
            for i in range(1, n - 1):
                if norm_arr[i] > threshold and \
                   norm_arr[i] > norm_arr[i-1] and \
                   norm_arr[i] > norm_arr[i+1]:
                    peaks += 1
            fv.peak_count = peaks

        # Zero-crossing rate of de-meaned norm
        demeaned = norm_arr - fv.acc_norm_mean
        if n >= 2:
            crossings = sum(1 for i in range(n - 1)
                          if (demeaned[i] >= 0) != (demeaned[i+1] >= 0))
            fv.zero_crossing_rate = crossings / (n - 1)

        return fv

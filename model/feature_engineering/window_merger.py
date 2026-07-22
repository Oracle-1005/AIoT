"""
Sliding Window Feature Merger
==============================
Merges camera landmarks + accelerometer data into joint feature vectors
using a sliding window approach.

Each window:
  - Camera: ~0.5s of MediaPipe landmarks (~15 frames @ 30fps)
  - Accel:  ~0.5s of Micro:bit samples (~25 samples @ 50Hz)
  - Output: 25 (camera) + 18 (accel) = 43-dimensional feature vector + label
"""

import math
from typing import Optional
from dataclasses import dataclass, field
from collections import deque

import numpy as np

from feature_engineering.camera_features import CameraFeatureExtractor, CameraFeatureVector
from feature_engineering.accel_features import AccelFeatureExtractor, AccelFeatureVector
from microbit_receiver import AccelSample


@dataclass
class JointFeatureVector:
    """Combined camera + accelerometer feature vector for one window"""
    camera: CameraFeatureVector = field(default_factory=CameraFeatureVector)
    accel: AccelFeatureVector = field(default_factory=AccelFeatureVector)
    label: Optional[str] = None
    window_start_ts: float = 0.0
    window_end_ts: float = 0.0

    def to_list(self) -> list[float]:
        """Flatten to single feature vector"""
        return self.camera.to_list() + self.accel.to_list()

    @staticmethod
    def feature_names() -> list[str]:
        return CameraFeatureVector.feature_names() + AccelFeatureVector.feature_names()

    @property
    def dimension(self) -> int:
        return len(self.to_list())


class SlidingWindowMerger:
    """
    Accumulates camera landmark frames and accelerometer samples,
    then produces JointFeatureVectors on demand using sliding windows.

    Usage:
        merger = SlidingWindowMerger(window_ms=500, stride_ms=250)
        for frame in camera_frames:
            merger.add_camera_frame(frame['hands'], frame['timestamp'])
        for sample in accel_samples:
            merger.add_accel_sample(sample)
        vectors = merger.extract_windows()
    """

    def __init__(self, window_ms: float = 500, stride_ms: float = 250,
                 camera_fps: float = 30.0, accel_hz: float = 50.0):
        self.window_ms = window_ms
        self.stride_ms = stride_ms
        self.camera_fps = camera_fps
        self.accel_hz = accel_hz

        # Ring buffers: (timestamp, data)
        self._camera_buffer: deque = deque()  # (ts, hands_list)
        self._accel_buffer: deque = deque()   # AccelSample

        # Track last extraction point to avoid duplicates
        self._last_extract_ts: float = 0.0

    def add_camera_frame(self, hands: list, timestamp: float):
        """Add a camera frame with hand landmarks"""
        self._camera_buffer.append((timestamp, hands))
        # Keep buffer size ~2× window
        while len(self._camera_buffer) > 100:
            self._camera_buffer.popleft()

    def add_accel_sample(self, sample: AccelSample):
        """Add an accelerometer sample"""
        self._accel_buffer.append(sample)
        while len(self._accel_buffer) > 200:
            self._accel_buffer.popleft()

    @property
    def latest_camera_ts(self) -> float:
        return self._camera_buffer[-1][0] if self._camera_buffer else 0.0

    @property
    def latest_accel_ts(self) -> float:
        return self._accel_buffer[-1].pc_timestamp if self._accel_buffer else 0.0

    def can_extract(self) -> bool:
        """Check if we have enough data for at least one window"""
        if not self._camera_buffer or not self._accel_buffer:
            return False
        earliest = max(self._camera_buffer[0][0], self._accel_buffer[0].pc_timestamp)
        latest = min(self.latest_camera_ts, self.latest_accel_ts)
        return (latest - earliest) * 1000 >= self.window_ms

    def extract_windows(self, label: Optional[str] = None) -> list[JointFeatureVector]:
        """
        Extract all available sliding windows from the buffer.
        Uses stride-based sliding window approach.
        """
        if not self.can_extract():
            return []

        # Find overlapping time range
        cam_start = self._camera_buffer[0][0]
        accel_start = self._accel_buffer[0].pc_timestamp
        cam_end = self.latest_camera_ts
        accel_end = self.latest_accel_ts

        window_start = max(cam_start, accel_start)
        window_end = min(cam_end, accel_end)

        if (window_end - window_start) * 1000 < self.window_ms:
            return []

        results = []
        current_start = max(window_start, self._last_extract_ts)

        while (window_end - current_start) * 1000 >= self.window_ms:
            current_end = current_start + self.window_ms / 1000.0

            # Filter camera frames in window
            cam_frames = [hands for ts, hands in self._camera_buffer
                         if current_start <= ts <= current_end]

            # Filter accel samples in window
            accel_samples = [s for s in self._accel_buffer
                           if current_start <= s.pc_timestamp <= current_end]

            if len(cam_frames) >= 5 and len(accel_samples) >= 5:
                # Extract camera features
                cam_extractor = CameraFeatureExtractor()
                for hands in cam_frames:
                    cam_extractor.add_frame(hands)
                cam_fv = cam_extractor.extract(fps=self.camera_fps)

                # Extract accel features
                accel_extractor = AccelFeatureExtractor()
                accel_extractor.add_samples(accel_samples)
                accel_fv = accel_extractor.extract()

                jfv = JointFeatureVector(
                    camera=cam_fv,
                    accel=accel_fv,
                    label=label,
                    window_start_ts=current_start,
                    window_end_ts=current_end,
                )
                results.append(jfv)

            current_start += self.stride_ms / 1000.0

        self._last_extract_ts = current_start
        return results

    def extract_latest(self, label: Optional[str] = None) -> Optional[JointFeatureVector]:
        """Extract only the most recent complete window"""
        windows = self.extract_windows(label)
        return windows[-1] if windows else None

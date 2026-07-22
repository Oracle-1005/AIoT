from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import numpy as np


@dataclass(slots=True, frozen=True)
class Landmark3D:
    x: float
    y: float
    z: float

    def to_dict(self) -> dict[str, float]:
        return {"x": self.x, "y": self.y, "z": self.z}


@dataclass(slots=True)
class CameraMetadata:
    exposure_time_us: int | None = None
    analogue_gain: float | None = None
    frame_duration_us: int | None = None

    def to_dict(self) -> dict[str, int | float | None]:
        return {
            "exposure_time_us": self.exposure_time_us,
            "analogue_gain": self.analogue_gain,
            "frame_duration_us": self.frame_duration_us,
        }


@dataclass(slots=True)
class CameraFrame:
    frame_sequence: int
    sensor_timestamp_ns: int
    pi_frame_received_ns: int
    width: int
    height: int
    pixel_format: str
    image: np.ndarray
    metadata: CameraMetadata


@dataclass(slots=True)
class RawHandObservation:
    hand_label: str
    handedness_score: float
    image_landmarks: list[Landmark3D]
    world_landmarks: list[Landmark3D]


@dataclass(slots=True)
class HandLandmarkObservation:
    hand_label: str
    handedness_score: float
    image_landmarks: list[Landmark3D]
    world_landmarks: list[Landmark3D]
    detection_valid: bool
    quality_score: float
    quality_flags: list[str] = field(default_factory=list)
    source: str = "detected"
    missing_frames: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "hand_label": self.hand_label,
            "handedness_score": self.handedness_score,
            "image_landmarks": [point.to_dict() for point in self.image_landmarks],
            "world_landmarks": [point.to_dict() for point in self.world_landmarks],
            "detection_valid": self.detection_valid,
            "quality_score": self.quality_score,
            "quality_flags": list(self.quality_flags),
            "source": self.source,
            "missing_frames": self.missing_frames,
        }


@dataclass(slots=True)
class ClockMapping:
    pi_aligned_timestamp_ns: int
    offset_ns: int
    residual_ns: int
    sample_count: int
    ready: bool

    def to_dict(self) -> dict[str, int | bool]:
        return {
            "pi_aligned_timestamp_ns": self.pi_aligned_timestamp_ns,
            "offset_ns": self.offset_ns,
            "residual_ns": self.residual_ns,
            "sample_count": self.sample_count,
            "ready": self.ready,
        }


@dataclass(slots=True)
class CameraLandmarkFrame:
    frame_sequence: int
    sensor_timestamp_ns: int
    pi_frame_received_ns: int
    media_timestamp_ms: int
    width: int
    height: int
    pixel_format: str
    metadata: CameraMetadata
    hands: list[HandLandmarkObservation]
    clock: ClockMapping
    processing_finished_ns: int
    dropped_capture_frames: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "camera_landmark_frame",
            "schema_version": "1.0",
            "frame_sequence": self.frame_sequence,
            "sensor_timestamp_ns": self.sensor_timestamp_ns,
            "pi_frame_received_ns": self.pi_frame_received_ns,
            "pi_aligned_timestamp_ns": self.clock.pi_aligned_timestamp_ns,
            "media_timestamp_ms": self.media_timestamp_ms,
            "processing_finished_ns": self.processing_finished_ns,
            "capture_to_output_latency_ns": max(
                0, self.processing_finished_ns - self.pi_frame_received_ns
            ),
            "width": self.width,
            "height": self.height,
            "pixel_format": self.pixel_format,
            "metadata": self.metadata.to_dict(),
            "clock_mapping": self.clock.to_dict(),
            "dropped_capture_frames": self.dropped_capture_frames,
            "camera": {
                "hands_detected": sum(1 for hand in self.hands if hand.source == "detected"),
                "hands_output": len(self.hands),
                "hands": [hand.to_dict() for hand in self.hands],
            },
        }

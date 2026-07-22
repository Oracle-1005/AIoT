from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .models import Landmark3D, RawHandObservation


@dataclass(slots=True)
class HandDetectorConfig:
    model_path: str
    num_hands: int = 2
    min_hand_detection_confidence: float = 0.5
    min_hand_presence_confidence: float = 0.5
    min_tracking_confidence: float = 0.5
    input_array_order: str = "BGR"
    swap_handedness_labels: bool = False


class MediaPipeHandDetector:
    def __init__(self, config: HandDetectorConfig) -> None:
        model_path = Path(config.model_path)
        if not model_path.is_file():
            raise FileNotFoundError(
                f"MediaPipe model not found: {model_path}. Run ./download_model.sh first."
            )
        self.config = config

        import mediapipe as mp

        self._mp = mp
        options = mp.tasks.vision.HandLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path.resolve())),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_hands=config.num_hands,
            min_hand_detection_confidence=config.min_hand_detection_confidence,
            min_hand_presence_confidence=config.min_hand_presence_confidence,
            min_tracking_confidence=config.min_tracking_confidence,
        )
        self._landmarker = mp.tasks.vision.HandLandmarker.create_from_options(options)

    def close(self) -> None:
        self._landmarker.close()

    def detect(self, image: np.ndarray, timestamp_ms: int) -> list[RawHandObservation]:
        rgb = self._to_rgb(image)
        mp_image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(mp_image, timestamp_ms)

        observations: list[RawHandObservation] = []
        count = min(
            len(result.handedness),
            len(result.hand_landmarks),
            len(result.hand_world_landmarks),
        )
        for index in range(count):
            categories = result.handedness[index]
            category = categories[0] if categories else None
            label = (category.category_name if category is not None else "unknown").lower()
            score = float(category.score if category is not None else 0.0)
            if self.config.swap_handedness_labels:
                label = {"left": "right", "right": "left"}.get(label, label)

            observations.append(
                RawHandObservation(
                    hand_label=label,
                    handedness_score=score,
                    image_landmarks=[
                        Landmark3D(float(p.x), float(p.y), float(p.z))
                        for p in result.hand_landmarks[index]
                    ],
                    world_landmarks=[
                        Landmark3D(float(p.x), float(p.y), float(p.z))
                        for p in result.hand_world_landmarks[index]
                    ],
                )
            )
        return observations

    def _to_rgb(self, image: np.ndarray) -> np.ndarray:
        order = self.config.input_array_order.upper()
        if order == "RGB":
            return np.ascontiguousarray(image)
        if order == "BGR":
            return np.ascontiguousarray(image[:, :, ::-1])
        raise ValueError(f"unsupported input_array_order: {self.config.input_array_order}")

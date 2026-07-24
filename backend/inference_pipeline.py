"""Thread-safe bridge from Pi uplink windows to the in-process model.

Camera observations are the primary 30 FPS stream. Micro:bit observations are
an optional sparse auxiliary stream and are deduplicated by sample_sequence.
The backend deliberately does not calculate model features; it packages raw
window data using the camera_features / microbit_features /
cross_modal_features contract for model.inference.GestureClassifier.
"""
from __future__ import annotations

import copy
import os
import threading
from collections import deque
from typing import Any

from integration import run_prediction
from model_service import model_service

WINDOW_SIZE = max(1, int(os.getenv("AIOT_INFER_WINDOW_SIZE", "30")))
MIN_CAMERA_FRAMES = max(1, int(os.getenv("AIOT_INFER_MIN_CAMERA_FRAMES", "15")))
INFER_EVERY_N_FRAMES = max(1, int(os.getenv("AIOT_INFER_EVERY_N_FRAMES", "3")))
AUTO_INFER_WINDOW_FEATURES = os.getenv(
    "AIOT_AUTO_INFER_WINDOW_FEATURES", "1"
).lower() in {"1", "true", "yes", "on"}
HANDS = ("left", "right")


def _hand_name(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in HANDS:
        return normalized
    return None


def _camera_hands(camera: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return at most one camera observation per hand for the current frame."""
    routed: dict[str, dict[str, Any]] = {}
    hands = camera.get("hands", [])
    if not isinstance(hands, list):
        return routed

    for hand_data in hands:
        if not isinstance(hand_data, dict):
            continue
        hand = _hand_name(
            hand_data.get("hand", hand_data.get("handedness", hand_data.get("label")))
        )
        if hand is not None:
            routed[hand] = copy.deepcopy(hand_data)
    return routed


def _zero_microbit_sample(hand: str) -> dict[str, Any]:
    return {
        "hand": hand,
        "acc_x": 0.0,
        "acc_y": 0.0,
        "acc_z": 0.0,
        "available": False,
    }


class InferencePipeline:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._camera_samples = {
            hand: deque(maxlen=WINDOW_SIZE) for hand in HANDS
        }
        self._microbit_samples = {
            hand: deque(maxlen=WINDOW_SIZE) for hand in HANDS
        }
        self._last_sequence: dict[str, Any] = {hand: None for hand in HANDS}
        self._camera_frame_count = 0
        self._last_error: str | None = None
        self._predictions = 0
        self._duplicates_dropped = 0

    def process_fused_frame(
        self, payload: dict[str, Any], received_at: float
    ) -> dict[str, Any] | None:
        """Add one camera frame and only novel micro:bit samples.

        Inference cadence is driven exclusively by camera frames. This prevents
        sparse 6.7 Hz micro:bit data from throttling the primary camera model.
        """
        with self._lock:
            camera = payload.get("camera", {})
            if not isinstance(camera, dict):
                camera = {}

            frame_id = camera.get("frame_id", payload.get("frame_id"))
            camera_by_hand = _camera_hands(camera)
            for hand, hand_data in camera_by_hand.items():
                self._camera_samples[hand].append({
                    "frame_id": frame_id,
                    "timestamp": camera.get(
                        "pi_ts", camera.get("timestamp", received_at)
                    ),
                    "received_at": received_at,
                    "hand": hand,
                    "data": hand_data,
                })

            # A fused frame is a camera tick even when no hand is detected.
            self._camera_frame_count += 1

            microbits = payload.get("microbits", [])
            if isinstance(microbits, list):
                for sample in microbits:
                    if not isinstance(sample, dict):
                        continue
                    hand = _hand_name(sample.get("hand", sample.get("device_id")))
                    if hand is None:
                        # Also accept the common L/R device identifiers.
                        device_id = str(sample.get("device_id", "")).upper()
                        hand = "left" if device_id == "L" else "right" if device_id == "R" else None
                    if hand is None:
                        continue

                    sequence = sample.get("sample_sequence", sample.get("sequence"))
                    if sequence is not None and sequence == self._last_sequence[hand]:
                        self._duplicates_dropped += 1
                        continue
                    if sequence is not None:
                        self._last_sequence[hand] = sequence

                    item = copy.deepcopy(sample)
                    item["hand"] = hand
                    item["available"] = True
                    item["received_at"] = received_at
                    self._microbit_samples[hand].append(item)

            if not model_service.loaded:
                return None
            if self._camera_frame_count % INFER_EVERY_N_FRAMES != 0:
                return None
            if max(len(values) for values in self._camera_samples.values()) < MIN_CAMERA_FRAMES:
                return None

            model_input = self._build_model_input(payload, received_at)

        return self._predict(model_input)

    def _build_model_input(
        self, payload: dict[str, Any], received_at: float
    ) -> dict[str, Any]:
        camera_windows = {
            hand: list(values) for hand, values in self._camera_samples.items()
        }
        microbit_windows: dict[str, dict[str, Any]] = {}
        for hand, values in self._microbit_samples.items():
            samples = list(values)
            microbit_windows[hand] = {
                "available": bool(samples),
                "samples": samples if samples else [_zero_microbit_sample(hand)],
                "last_sample_sequence": self._last_sequence[hand],
            }

        return {
            "source": "fused_frame",
            "received_at": received_at,
            # These contain raw windows; feature calculation belongs to model side.
            "camera_features": {
                "primary": True,
                "fps": 30,
                "window_size": WINDOW_SIZE,
                "hands": camera_windows,
            },
            "microbit_features": {
                "primary": False,
                "nominal_hz": 6.7,
                "hands": microbit_windows,
            },
            "cross_modal_features": {
                "fusion": copy.deepcopy(payload.get("fusion", {})),
                "timestamps": copy.deepcopy(payload.get("timestamps", {})),
                "frame_id": payload.get("frame_id", payload.get("camera", {}).get("frame_id") if isinstance(payload.get("camera"), dict) else None),
            },
        }

    def process_window_features(self, payload: dict[str, Any]) -> dict[str, Any] | None:
        """Compatibility route for a producer that already emits model windows."""
        if not AUTO_INFER_WINDOW_FEATURES or not model_service.loaded:
            return None
        if not isinstance(payload, dict):
            raise ValueError("window_features payload must be a JSON object")
        return self._predict(copy.deepcopy(payload))

    def _predict(self, window: dict[str, Any]) -> dict[str, Any] | None:
        try:
            result = run_prediction(window)
        except (RuntimeError, TypeError, ValueError) as exc:
            with self._lock:
                self._last_error = str(exc)
            return None
        with self._lock:
            self._predictions += 1
            self._last_error = None
        return result

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "window_size": WINDOW_SIZE,
                "min_camera_frames": MIN_CAMERA_FRAMES,
                "infer_every_n_frames": INFER_EVERY_N_FRAMES,
                "camera_samples": {
                    hand: len(values) for hand, values in self._camera_samples.items()
                },
                "microbit_samples": {
                    hand: len(values) for hand, values in self._microbit_samples.items()
                },
                # Kept for clients that consumed the previous additive status field.
                "samples": {
                    hand: len(self._camera_samples[hand]) for hand in HANDS
                },
                "last_sequences": dict(self._last_sequence),
                "duplicates_dropped": self._duplicates_dropped,
                "camera_frames_seen": self._camera_frame_count,
                "predictions": self._predictions,
                "last_error": self._last_error,
                "window_features_auto_infer": AUTO_INFER_WINDOW_FEATURES,
            }


inference_pipeline = InferencePipeline()

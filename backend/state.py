"""Thread-safe in-memory live state.

The database stores history; this module stores only the latest values needed
by high-frequency REST polling.
"""

from __future__ import annotations

import copy
import threading
import time
from typing import Any


GESTURES = (
    "idle",
    "downbeat",
    "crescendo",
    "decrescendo",
    "cutoff",
    "style_switch",
    "tempo_up",
    "tempo_down",
)


class LiveState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.camera_connected = False
        self.microbit_left_connected = False
        self.microbit_right_connected = False

        self.current_prediction: dict[str, Any] = {
            "gesture": "idle",
            "confidence": 0.0,
            "gesture_id": 0,
            "timestamp": 0.0,
            "features_used": 0,
            "all_probs": {gesture: (1.0 if gesture == "idle" else 0.0) for gesture in GESTURES},
        }

        self.sensor_state: dict[str, Any] = {
            "microbit_left": {"acc_x": 0.0, "acc_y": 0.0, "acc_z": 0.0},
            "microbit_right": {"acc_x": 0.0, "acc_y": 0.0, "acc_z": 0.0},
            "hand_detected": False,
            "hand_count": 0,
            "timestamp": 0.0,
        }

        self.music_state: dict[str, Any] = {
            "playing": False,
            "bpm": 120,
            "volume": 0.8,
            "style": "piano",
            "current_gesture": "idle",
        }

    def uptime_seconds(self) -> int:
        return max(0, int(time.time() - self.started_at))

    def get_prediction(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.current_prediction)

    def set_prediction(self, result: dict[str, Any]) -> None:
        with self._lock:
            self.current_prediction = copy.deepcopy(result)
            self._apply_music_effect(str(result["gesture"]))

    def get_sensors(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.sensor_state)

    def update_sensors(
        self,
        *,
        microbit_left: dict[str, float] | None = None,
        microbit_right: dict[str, float] | None = None,
        hand_detected: bool | None = None,
        hand_count: int | None = None,
        timestamp: float | None = None,
    ) -> None:
        with self._lock:
            if microbit_left is not None:
                self.sensor_state["microbit_left"] = dict(microbit_left)
                self.microbit_left_connected = True
            if microbit_right is not None:
                self.sensor_state["microbit_right"] = dict(microbit_right)
                self.microbit_right_connected = True
            if hand_detected is not None:
                self.sensor_state["hand_detected"] = bool(hand_detected)
                self.camera_connected = True
            if hand_count is not None:
                self.sensor_state["hand_count"] = max(0, int(hand_count))
            self.sensor_state["timestamp"] = float(timestamp if timestamp is not None else time.time())

    def get_music(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.music_state)

    def _apply_music_effect(self, gesture: str) -> None:
        self.music_state["current_gesture"] = gesture

        if gesture == "downbeat":
            self.music_state["playing"] = True
        elif gesture == "cutoff":
            self.music_state["playing"] = False
        elif gesture == "crescendo":
            self.music_state["volume"] = min(1.0, round(self.music_state["volume"] + 0.05, 2))
        elif gesture == "decrescendo":
            self.music_state["volume"] = max(0.0, round(self.music_state["volume"] - 0.05, 2))
        elif gesture == "tempo_up":
            self.music_state["bpm"] = min(220, self.music_state["bpm"] + 5)
        elif gesture == "tempo_down":
            self.music_state["bpm"] = max(40, self.music_state["bpm"] - 5)
        elif gesture == "style_switch":
            styles = ("piano", "strings", "brass")
            current = self.music_state["style"]
            self.music_state["style"] = styles[(styles.index(current) + 1) % len(styles)]


live_state = LiveState()

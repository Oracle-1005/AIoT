"""Thread-safe live state for REST polling and future WebSocket publishing."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

GESTURES = ("idle", "downbeat", "crescendo", "decrescendo", "cutoff",
            "style_switch", "tempo_up", "tempo_down")


class LiveState:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self.started_at = time.time()
        self.camera_connected = False
        self.microbit_left_connected = False
        self.microbit_right_connected = False
        self.current_prediction: dict[str, Any] = {
            "gesture": "idle", "confidence": 0.0, "gesture_id": 0,
            "timestamp": 0.0, "features_used": 0,
            "all_probs": {gesture: (1.0 if gesture == "idle" else 0.0) for gesture in GESTURES},
        }
        self.sensor_state: dict[str, Any] = {
            "microbit_left": {}, "microbit_right": {}, "camera": {},
            "hand_detected": False, "hand_count": 0, "timestamp": 0.0,
        }
        self.music_state: dict[str, Any] = {
            "playing": False, "bpm": 120, "volume": 0.8,
            "style": "piano", "current_gesture": "idle",
        }
        self.pi_state: dict[str, Any] = {
            "last_message_type": None, "last_message_at": None,
            "message_counts": {name: 0 for name in ("fused_frame", "window_features", "control_event", "status")},
            "status": {}, "last_control_event": None,
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

    def get_pi_state(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.pi_state)

    def record_pi_message(self, message: dict[str, Any]) -> None:
        with self._lock:
            message_type = str(message["message_type"])
            self.pi_state["last_message_type"] = message_type
            self.pi_state["last_message_at"] = message["received_at"]
            counts = self.pi_state["message_counts"]
            counts[message_type] = int(counts.get(message_type, 0)) + 1

    def apply_pi_status(self, payload: dict[str, Any]) -> None:
        with self._lock:
            self.pi_state["status"] = copy.deepcopy(payload)
            devices = payload.get("devices", payload)
            if isinstance(devices, dict):
                self.camera_connected = _online(devices.get("camera", self.camera_connected))
                self.microbit_left_connected = _online(
                    devices.get("microbit_left", devices.get("left_microbit", self.microbit_left_connected))
                )
                self.microbit_right_connected = _online(
                    devices.get("microbit_right", devices.get("right_microbit", self.microbit_right_connected))
                )

    def apply_fused_frame(self, payload: dict[str, Any], received_at: float) -> None:
        with self._lock:
            self.sensor_state["timestamp"] = received_at
            camera = payload.get("camera", payload.get("vision"))
            if isinstance(camera, dict):
                self.sensor_state["camera"] = copy.deepcopy(camera)
                self.camera_connected = True
                hands = camera.get("hands")
                if isinstance(hands, list):
                    self.sensor_state["hand_count"] = len(hands)
                    self.sensor_state["hand_detected"] = bool(hands)
            for destination, keys in (
                ("microbit_left", ("microbit_left", "left", "left_hand")),
                ("microbit_right", ("microbit_right", "right", "right_hand")),
            ):
                sample = next((payload.get(key) for key in keys if isinstance(payload.get(key), dict)), None)
                if sample is not None:
                    self.sensor_state[destination] = copy.deepcopy(sample)
                    if destination == "microbit_left":
                        self.microbit_left_connected = True
                    else:
                        self.microbit_right_connected = True

    def apply_control_event(self, payload: dict[str, Any], received_at: float) -> None:
        with self._lock:
            self.pi_state["last_control_event"] = {"received_at": received_at, "payload": copy.deepcopy(payload)}

    def update_sensors(self, *, microbit_left: dict[str, float] | None = None,
                       microbit_right: dict[str, float] | None = None,
                       hand_detected: bool | None = None, hand_count: int | None = None,
                       timestamp: float | None = None) -> None:
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
        if gesture == "downbeat": self.music_state["playing"] = True
        elif gesture == "cutoff": self.music_state["playing"] = False
        elif gesture == "crescendo": self.music_state["volume"] = min(1.0, round(self.music_state["volume"] + 0.05, 2))
        elif gesture == "decrescendo": self.music_state["volume"] = max(0.0, round(self.music_state["volume"] - 0.05, 2))
        elif gesture == "tempo_up": self.music_state["bpm"] = min(220, self.music_state["bpm"] + 5)
        elif gesture == "tempo_down": self.music_state["bpm"] = max(40, self.music_state["bpm"] - 5)
        elif gesture == "style_switch":
            styles = ("piano", "strings", "brass")
            current = self.music_state["style"]
            self.music_state["style"] = styles[(styles.index(current) + 1) % len(styles)]


def _online(value: Any) -> bool:
    if isinstance(value, bool): return value
    if isinstance(value, str): return value.lower() in {"online", "connected", "ok", "true", "1"}
    return bool(value)


live_state = LiveState()

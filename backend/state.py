"""Thread-safe live state for REST polling and future WebSocket publishing."""

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
    # Hardware-detected event types
    "left_wrist_strike",
    "right_wrist_strike",
    "bilateral_strike",
    "gesture_start",
    "gesture_end",
    "stop",
    "resume",
)

SONIC_PI_TRACK_TITLE = "Ode to Joy Conductor Mix"
SONIC_PI_TRACK_KEY = "C Major"
SONIC_PI_TRACK_TOTAL_BARS = 8
SONIC_PI_BEATS_PER_BAR = 4


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
            "all_probs": {
                gesture: (1.0 if gesture == "idle" else 0.0)
                for gesture in GESTURES
            },
        }

        self.sensor_state: dict[str, Any] = {
            "microbit_left": {},
            "microbit_right": {},
            "camera": {},
            "hand_detected": False,
            "hand_count": 0,
            "timestamp": 0.0,
        }

        self.music_state: dict[str, Any] = {
            "title": SONIC_PI_TRACK_TITLE,
            "key": SONIC_PI_TRACK_KEY,
            "playing": False,
            "bpm": 120,
            "volume": 0.8,
            "style": "sonic_pi",
            "engine": "sonic_pi",
            "energy": 0.62,
            "section": "main",
            "total_bars": SONIC_PI_TRACK_TOTAL_BARS,
            "beats_per_bar": SONIC_PI_BEATS_PER_BAR,
            "duration_seconds": _loop_duration_seconds(120),
            "elapsed_seconds": 0.0,
            "performance_elapsed_seconds": 0.0,
            "progress": 0,
            "current_gesture": "idle",
            "sonic_pi_connected": False,
            "last_beat": None,
            "last_bar": None,
            "beat_strength": 0.0,
            "last_sonic_pi_feedback_at": None,
            "last_sonic_pi_ack": None,
            "last_sonic_pi_error": None,
        }

        self.pi_state: dict[str, Any] = {
            "last_message_type": None,
            "last_message_at": None,
            "message_counts": {
                name: 0
                for name in ("fused_frame", "control_event", "status")
            },
            "status": {},
            "last_control_event": None,
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

            camera = payload.get("camera", {})
            if isinstance(camera, dict):
                self.camera_connected = _online(
                    camera.get("connected", self.camera_connected)
                )

            microbits = payload.get("microbits", {})
            if isinstance(microbits, dict):
                left_microbit = microbits.get("left", {})
                right_microbit = microbits.get("right", {})

                if isinstance(left_microbit, dict):
                    self.microbit_left_connected = _online(
                        left_microbit.get(
                            "connected",
                            self.microbit_left_connected,
                        )
                    )

                if isinstance(right_microbit, dict):
                    self.microbit_right_connected = _online(
                        right_microbit.get(
                            "connected",
                            self.microbit_right_connected,
                        )
                    )

    def apply_fused_frame(
        self,
        payload: dict[str, Any],
        received_at: float,
    ) -> None:
        with self._lock:
            self.sensor_state["timestamp"] = received_at

            camera = payload.get("camera")
            if isinstance(camera, dict):
                self.sensor_state["camera"] = copy.deepcopy(camera)
                self.camera_connected = True

                hands = camera.get("hands")
                if isinstance(hands, list):
                    self.sensor_state["hand_count"] = len(hands)
                    self.sensor_state["hand_detected"] = bool(hands)

            microbits = payload.get("microbits", [])
            if isinstance(microbits, list):
                for microbit in microbits:
                    if not isinstance(microbit, dict):
                        continue

                    hand = str(microbit.get("hand", "")).lower()

                    if hand == "left":
                        self.sensor_state["microbit_left"] = copy.deepcopy(
                            microbit
                        )
                        self.microbit_left_connected = True

                    elif hand == "right":
                        self.sensor_state["microbit_right"] = copy.deepcopy(
                            microbit
                        )
                        self.microbit_right_connected = True

    def apply_control_event(
        self,
        payload: dict[str, Any],
        received_at: float,
    ) -> None:
        with self._lock:
            self.pi_state["last_control_event"] = {
                "received_at": received_at,
                "payload": copy.deepcopy(payload),
            }

            event = payload.get("event", {})
            music_control = payload.get("music_control", {})

            if isinstance(event, dict):
                gesture = str(event.get("type", "")).strip()

                if gesture:
                    self.music_state["current_gesture"] = gesture

                    if gesture in {
                        "downbeat",
                        "left_wrist_strike",
                        "right_wrist_strike",
                        "bilateral_strike",
                        "resume",
                        "gesture_start",
                    }:
                        self.music_state["playing"] = True

                    elif gesture in {
                        "stop",
                        "cutoff",
                        "gesture_end",
                    }:
                        self.music_state["playing"] = False

            if isinstance(music_control, dict):
                estimated_bpm = music_control.get("estimated_bpm")
                if estimated_bpm is not None:
                    try:
                        bpm = int(round(float(estimated_bpm)))
                        self.music_state["bpm"] = min(220, max(40, bpm))
                    except (TypeError, ValueError):
                        pass

                volume = music_control.get("volume")
                if volume is not None:
                    try:
                        normalized_volume = round(float(volume), 2)
                        self.music_state["volume"] = min(
                            1.0,
                            max(0.0, normalized_volume),
                        )
                    except (TypeError, ValueError):
                        pass

                intensity = music_control.get("intensity", music_control.get("energy"))
                if intensity is not None:
                    try:
                        normalized_energy = round(float(intensity), 2)
                        self.music_state["energy"] = min(
                            1.0,
                            max(0.0, normalized_energy),
                        )
                    except (TypeError, ValueError):
                        pass

                style = music_control.get("style")
                if style:
                    self.music_state["style"] = str(style)

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

            self.sensor_state["timestamp"] = float(
                timestamp if timestamp is not None else time.time()
            )

    def get_music(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.music_state)

    def apply_sonic_pi_state(
        self,
        *,
        playing: Any,
        bpm: Any,
        section: Any,
        energy: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            self.music_state["playing"] = _truthy(playing)
            self.music_state["bpm"] = _bounded_int(bpm, 40, 220, self.music_state["bpm"])
            self.music_state["section"] = str(section)
            self.music_state["energy"] = _bounded_float(
                energy,
                0.0,
                1.0,
                self.music_state["energy"],
            )
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at
            self._update_music_timing_locked()

    def apply_sonic_pi_beat(
        self,
        *,
        bar: Any,
        beat: Any,
        bpm: Any,
        beat_strength: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            self.music_state["last_bar"] = _bounded_int(bar, 0, 999999, 0)
            self.music_state["last_beat"] = _bounded_int(beat, 1, 16, 1)
            self.music_state["bpm"] = _bounded_int(bpm, 40, 220, self.music_state["bpm"])
            self.music_state["beat_strength"] = _bounded_float(
                beat_strength,
                0.0,
                1.2,
                0.0,
            )
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at
            self._update_music_timing_locked()

    def apply_sonic_pi_bar(
        self,
        *,
        bar: Any,
        section: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            self.music_state["last_bar"] = _bounded_int(bar, 0, 999999, 0)
            self.music_state["section"] = str(section)
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at
            self._update_music_timing_locked()

    def apply_sonic_pi_ack(
        self,
        *,
        command_id: Any,
        result: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            self.music_state["last_sonic_pi_ack"] = {
                "command_id": str(command_id),
                "result": str(result),
                "received_at": received_at,
            }
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at

    def apply_sonic_pi_error(
        self,
        *,
        code: Any,
        message: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            self.music_state["last_sonic_pi_error"] = {
                "code": str(code),
                "message": str(message),
                "received_at": received_at,
            }
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at

    def _update_music_timing_locked(self) -> None:
        bpm = _bounded_float(self.music_state["bpm"], 40.0, 220.0, 120.0)
        bar = _bounded_int(self.music_state.get("last_bar"), 0, 999999, 0)
        beat = _bounded_int(self.music_state.get("last_beat"), 1, SONIC_PI_BEATS_PER_BAR, 1)

        total_beats = SONIC_PI_TRACK_TOTAL_BARS * SONIC_PI_BEATS_PER_BAR
        absolute_beat = max(0, bar * SONIC_PI_BEATS_PER_BAR + (beat - 1))
        loop_beat = absolute_beat % total_beats
        seconds_per_beat = 60.0 / bpm

        self.music_state["duration_seconds"] = round(total_beats * seconds_per_beat, 1)
        self.music_state["elapsed_seconds"] = round(loop_beat * seconds_per_beat, 1)
        self.music_state["performance_elapsed_seconds"] = round(absolute_beat * seconds_per_beat, 1)
        self.music_state["progress"] = int(round((loop_beat / total_beats) * 100))

    def _apply_music_effect(self, gesture: str) -> None:
        self.music_state["current_gesture"] = gesture

        if gesture == "downbeat":
            self.music_state["playing"] = True

        elif gesture == "cutoff":
            self.music_state["playing"] = False

        elif gesture == "crescendo":
            self.music_state["volume"] = min(
                1.0,
                round(self.music_state["volume"] + 0.05, 2),
            )

        elif gesture == "decrescendo":
            self.music_state["volume"] = max(
                0.0,
                round(self.music_state["volume"] - 0.05, 2),
            )

        elif gesture == "tempo_up":
            self.music_state["bpm"] = min(
                220,
                self.music_state["bpm"] + 5,
            )

        elif gesture == "tempo_down":
            self.music_state["bpm"] = max(
                40,
                self.music_state["bpm"] - 5,
            )

        elif gesture == "style_switch":
            styles = ("piano", "strings", "brass")
            current = self.music_state["style"]

            if current not in styles:
                current = styles[0]

            self.music_state["style"] = styles[
                (styles.index(current) + 1) % len(styles)
            ]


def _online(value: Any) -> bool:
    if isinstance(value, bool):
        return value

    if isinstance(value, str):
        return value.lower() in {
            "online",
            "connected",
            "ok",
            "true",
            "1",
        }

    return bool(value)


def _truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "playing", "play"}
    return bool(value)


def _bounded_int(value: Any, low: int, high: int, default: int) -> int:
    try:
        number = int(round(float(value)))
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _bounded_float(value: Any, low: float, high: float, default: float) -> float:
    try:
        number = round(float(value), 2)
    except (TypeError, ValueError):
        return default
    return min(high, max(low, number))


def _loop_duration_seconds(bpm: float) -> float:
    total_beats = SONIC_PI_TRACK_TOTAL_BARS * SONIC_PI_BEATS_PER_BAR
    return round(total_beats * 60.0 / max(1.0, float(bpm)), 1)


live_state = LiveState()

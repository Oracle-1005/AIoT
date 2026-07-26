"""Thread-safe live state for REST polling and future WebSocket publishing."""

from __future__ import annotations

import copy
import threading
import time
from typing import Any

GESTURES = (
    "idle",
    "downbeat",
    "upbeat",
    "crescendo",
    "decrescendo",
    "left_cue",
    "right_cue",
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

SONIC_PI_TRACKS = {
    "shape_of_you": {
        "title": "Shape of You (Ed Sheeran)",
        "key": "C# Minor",
        "bpm": 96,
        "total_bars": 93,
        "beats_per_bar": 4,
    },
    "world_is_mine": {
        "title": "World is Mine (Hatsune Miku)",
        "key": "Unknown",
        "bpm": 132,
        "total_bars": 140,
        "beats_per_bar": 4,
    },
}
SONIC_PI_TRACK_ORDER = ("shape_of_you", "world_is_mine")
SONIC_PI_DEFAULT_TRACK_ID = SONIC_PI_TRACK_ORDER[0]
SONIC_PI_TRACK_TITLE = SONIC_PI_TRACKS[SONIC_PI_DEFAULT_TRACK_ID]["title"]
SONIC_PI_TRACK_KEY = SONIC_PI_TRACKS[SONIC_PI_DEFAULT_TRACK_ID]["key"]
SONIC_PI_TRACK_TOTAL_BARS = SONIC_PI_TRACKS[SONIC_PI_DEFAULT_TRACK_ID]["total_bars"]
SONIC_PI_BEATS_PER_BAR = SONIC_PI_TRACKS[SONIC_PI_DEFAULT_TRACK_ID]["beats_per_bar"]

# 可硬切的四个声部（区域手势自上而下：melody → harmony → bass → drums）
MUSIC_LAYERS = ("melody", "harmony", "bass", "drums")


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
            "track_id": SONIC_PI_DEFAULT_TRACK_ID,
            "track_index": 0,
            "track_count": len(SONIC_PI_TRACK_ORDER),
            "title": SONIC_PI_TRACK_TITLE,
            "key": SONIC_PI_TRACK_KEY,
            "playing": False,
            "bpm": 108,
            "default_bpm": 108,
            "volume": 0.8,
            "style": "sonic_pi",
            "engine": "sonic_pi",
            "energy": 0.62,
            "section": "main",
            "total_bars": SONIC_PI_TRACK_TOTAL_BARS,
            "beats_per_bar": SONIC_PI_BEATS_PER_BAR,
            "duration_seconds": _loop_duration_seconds(108),
            "elapsed_seconds": 0.0,
            "performance_elapsed_seconds": 0.0,
            "progress": 0,
            "current_gesture": "idle",
            # 声部硬切门：后端持有意图，rb 侧 /conductor/layer 翻转播放门；
            # 与 *_amp 推导独立，不会被 /conductor/state 冲掉
            "layers": {name: True for name in MUSIC_LAYERS},
            "sonic_pi_connected": False,
            "last_beat": None,
            "last_bar": None,
            "last_beat_feedback_at": None,
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
                for name in ("fused_frame", "window_features", "control_event", "status")
            },
            "status": {},
            "last_control_event": None,
        }

    def uptime_seconds(self) -> int:
        return max(0, int(time.time() - self.started_at))

    def get_prediction(self) -> dict[str, Any]:
        with self._lock:
            return copy.deepcopy(self.current_prediction)

    def set_prediction(self, result: dict[str, Any], apply_music: bool = True) -> None:
        with self._lock:
            self.current_prediction = copy.deepcopy(result)
            if apply_music:
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
                    age_ms = left_microbit.get("age_ms")
                    self.microbit_left_connected = (
                        float(age_ms) < 1000 if isinstance(age_ms, (int, float))
                        else _online(left_microbit.get("connected", self.microbit_left_connected))
                    )

                if isinstance(right_microbit, dict):
                    age_ms = right_microbit.get("age_ms")
                    self.microbit_right_connected = (
                        float(age_ms) < 1000 if isinstance(age_ms, (int, float))
                        else _online(right_microbit.get("connected", self.microbit_right_connected))
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
    "upbeat",
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

                    elif gesture == "style_switch":
                        # 右手 A 短按：复用预测路径的风格循环
                        # （piano → strings → brass），下次 /conductor/state
                        # 会把新 style 带给 Sonic Pi
                        self._apply_music_effect(gesture)

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

    def set_music_layer(self, layer: str, enabled: bool) -> bool:
        """硬切一个声部（melody/harmony/bass/drums）。未知声部返回 False。"""
        name = str(layer).strip()
        if name not in MUSIC_LAYERS:
            return False
        with self._lock:
            self.music_state["layers"][name] = bool(enabled)
        return True

    def apply_sonic_pi_layers(
        self,
        *,
        melody: Any,
        harmony: Any,
        bass: Any,
        drums: Any,
        received_at: float,
    ) -> None:
        """rb 侧 /music/layers 周期反馈 —— 以 rb 门状态为准同步。"""
        with self._lock:
            self.music_state["layers"] = {
                "melody": _online(melody),
                "harmony": _online(harmony),
                "bass": _online(bass),
                "drums": _online(drums),
            }
            self.music_state["last_sonic_pi_feedback_at"] = received_at

    def apply_sonic_pi_style(self, style: Any, received_at: float) -> None:
        """rb 侧 /music/style 反馈（Shape of You 三风格预设）—— 以 rb 为准。"""
        style_text = str(style).strip()
        if not style_text:
            return
        with self._lock:
            self.music_state["style"] = style_text
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at

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
            self._update_music_timing_locked(now=time.time())
            return copy.deepcopy(self.music_state)

    def apply_sonic_pi_transport_intent(self, action: Any, requested_at: float) -> None:
        action_text = str(action).strip().lower()
        with self._lock:
            if action_text in {"start", "resume", "play"}:
                self.music_state["playing"] = True
                if self.music_state.get("last_bar") is None:
                    self.music_state["last_bar"] = 0
                if self.music_state.get("last_beat") is None:
                    self.music_state["last_beat"] = 1
                self.music_state["last_beat_feedback_at"] = requested_at
            elif action_text in {"pause", "stop", "cutoff"}:
                self.music_state["playing"] = False
            elif action_text == "reset":
                self.music_state["playing"] = True
                self._apply_track_locked(
                    str(self.music_state.get("track_id")),
                    reset_timing=False,
                )
                self.music_state["last_bar"] = 0
                self.music_state["last_beat"] = 1
                self.music_state["last_beat_feedback_at"] = requested_at
            elif action_text in {"next", "next_track"}:
                self._select_relative_track_locked(1, requested_at)
            elif action_text in {"previous", "prev", "previous_track"}:
                self._select_relative_track_locked(-1, requested_at)
            self._update_music_timing_locked(now=requested_at)

    def apply_sonic_pi_track(
        self,
        *,
        piece_id: Any,
        title: Any,
        key: Any,
        total_bars: Any,
        beats_per_bar: Any,
        default_bpm: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            track_id = _normalize_track_id(piece_id)
            previous_track_id = str(self.music_state.get("track_id", ""))
            track_changed = bool(track_id and track_id != previous_track_id)

            self._apply_track_locked(
                track_id or previous_track_id,
                reset_timing=track_changed,
                reset_bpm=track_changed,
            )

            title_text = str(title).strip()
            key_text = str(key).strip()
            if title_text:
                self.music_state["title"] = title_text
            if key_text:
                self.music_state["key"] = key_text

            self.music_state["total_bars"] = _bounded_int(
                total_bars,
                1,
                512,
                self.music_state["total_bars"],
            )
            self.music_state["beats_per_bar"] = _bounded_int(
                beats_per_bar,
                1,
                16,
                self.music_state["beats_per_bar"],
            )
            self.music_state["default_bpm"] = _bounded_int(
                default_bpm,
                40,
                220,
                self.music_state["default_bpm"],
            )
            if track_changed:
                self.music_state["bpm"] = self.music_state["default_bpm"]

            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at
            self._update_music_timing_locked(received_at)

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
            self.music_state["last_beat_feedback_at"] = received_at
            self._update_music_timing_locked()

    def apply_sonic_pi_bar(
        self,
        *,
        bar: Any,
        section: Any,
        received_at: float,
    ) -> None:
        with self._lock:
            # Beat messages are the single timing source. Bar messages can
            # arrive between beats, so using them for timing causes visible
            # progress regressions in the frontend.
            self.music_state["section"] = str(section)
            self.music_state["sonic_pi_connected"] = True
            self.music_state["last_sonic_pi_feedback_at"] = received_at

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

    def _update_music_timing_locked(self, now: float | None = None) -> None:
        bpm = _bounded_float(self.music_state["bpm"], 40.0, 220.0, 120.0)
        beats_per_bar = _bounded_int(
            self.music_state.get("beats_per_bar"),
            1,
            16,
            SONIC_PI_BEATS_PER_BAR,
        )
        total_bars = _bounded_int(
            self.music_state.get("total_bars"),
            1,
            512,
            SONIC_PI_TRACK_TOTAL_BARS,
        )
        bar = _bounded_int(self.music_state.get("last_bar"), 0, 999999, 0)
        beat = _bounded_int(self.music_state.get("last_beat"), 1, beats_per_bar, 1)

        total_beats = total_bars * beats_per_bar
        absolute_beat = max(0, bar * beats_per_bar + (beat - 1))
        seconds_per_beat = 60.0 / bpm
        duration_seconds = total_beats * seconds_per_beat
        absolute_seconds = absolute_beat * seconds_per_beat

        last_beat_feedback_at = self.music_state.get("last_beat_feedback_at")
        if (
            now is not None
            and self.music_state.get("playing")
            and isinstance(last_beat_feedback_at, (int, float))
        ):
            absolute_seconds += max(0.0, min(seconds_per_beat * 1.25, now - last_beat_feedback_at))

        elapsed_seconds = absolute_seconds % duration_seconds if duration_seconds else 0.0
        self.music_state["duration_seconds"] = round(duration_seconds, 1)
        self.music_state["elapsed_seconds"] = round(elapsed_seconds, 1)
        self.music_state["performance_elapsed_seconds"] = round(absolute_seconds, 1)
        self.music_state["progress"] = int(round((elapsed_seconds / duration_seconds) * 100)) if duration_seconds else 0

    def _apply_track_locked(
        self,
        track_id: str,
        *,
        reset_timing: bool,
        reset_bpm: bool = True,
    ) -> None:
        normalized_track_id = _normalize_track_id(track_id) or SONIC_PI_DEFAULT_TRACK_ID
        metadata = SONIC_PI_TRACKS.get(normalized_track_id)
        if metadata is None:
            normalized_track_id = SONIC_PI_DEFAULT_TRACK_ID
            metadata = SONIC_PI_TRACKS[normalized_track_id]

        self.music_state["track_id"] = normalized_track_id
        self.music_state["track_index"] = SONIC_PI_TRACK_ORDER.index(normalized_track_id)
        self.music_state["track_count"] = len(SONIC_PI_TRACK_ORDER)
        self.music_state["title"] = metadata["title"]
        self.music_state["key"] = metadata["key"]
        self.music_state["default_bpm"] = metadata["bpm"]
        if reset_bpm:
            self.music_state["bpm"] = metadata["bpm"]
        self.music_state["total_bars"] = metadata["total_bars"]
        self.music_state["beats_per_bar"] = metadata["beats_per_bar"]

        if reset_timing:
            self.music_state["last_bar"] = 0
            self.music_state["last_beat"] = 1
            self.music_state["elapsed_seconds"] = 0.0
            self.music_state["performance_elapsed_seconds"] = 0.0
            self.music_state["progress"] = 0

    def _select_relative_track_locked(self, delta: int, requested_at: float) -> None:
        current_track_id = _normalize_track_id(
            self.music_state.get("track_id"),
        ) or SONIC_PI_DEFAULT_TRACK_ID
        if current_track_id not in SONIC_PI_TRACK_ORDER:
            current_track_id = SONIC_PI_DEFAULT_TRACK_ID
        current_index = SONIC_PI_TRACK_ORDER.index(current_track_id)
        next_index = (current_index + delta) % len(SONIC_PI_TRACK_ORDER)

        self.music_state["playing"] = True
        self._apply_track_locked(SONIC_PI_TRACK_ORDER[next_index], reset_timing=True)
        self.music_state["last_beat_feedback_at"] = requested_at

    def _apply_music_effect(self, gesture: str) -> None:
        self.music_state["current_gesture"] = gesture

        if gesture in {"downbeat", "upbeat", "left_cue", "right_cue", "gesture_start"}:
            self.music_state["playing"] = True

        elif gesture in {"cutoff", "stop"}:
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


def _normalize_track_id(value: Any) -> str:
    text = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
    aliases = {
        "ode": "ode_to_joy",
        "ode_to_joy_conductor_mix": "ode_to_joy",
        "joy": "ode_to_joy",
        "canon": "canon_in_d",
        "canon_d": "canon_in_d",
        "canon_in_d_conductor_mix": "canon_in_d",
    }
    return aliases.get(text, text)


live_state = LiveState()

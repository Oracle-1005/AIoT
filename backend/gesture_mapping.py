"""Canonical mapping from RF model labels to backend event types."""
from __future__ import annotations
from typing import Any

CANONICAL_GESTURES = (
    "idle", "gesture_start", "stop", "downbeat", "upbeat",
    "crescendo", "decrescendo", "left_cue", "right_cue",
    "cutoff", "style_switch", "tempo_up", "tempo_down",
    "bpm_up", "bpm_down", "vol_up", "vol_down",
    "zone_on", "zone_off", "style",
)

_LABEL_ALIASES = {
    "idle": "idle", "still": "idle", "static": "idle", "静止": "idle",
    "start": "gesture_start", "gesture_start": "gesture_start", "开始": "gesture_start",
    "stop": "stop", "cutoff": "stop", "停止": "stop",
    "strong_beat": "downbeat", "downbeat": "downbeat", "强拍": "downbeat",
    "weak_beat": "upbeat", "upbeat": "upbeat", "弱拍": "upbeat",
    "crescendo": "crescendo", "渐强": "crescendo",
    "decrescendo": "decrescendo", "diminuendo": "decrescendo", "渐弱": "decrescendo",
    "left_cue": "left_cue", "left_prompt": "left_cue", "左手提示": "left_cue",
    "right_cue": "right_cue", "right_prompt": "right_cue", "右手提示": "right_cue",
    "gesture_end": "stop", "pause": "stop",
    "tempo_up": "tempo_up", "bpm_up": "bpm_up", "speed_up": "tempo_up",
    "tempo_down": "tempo_down", "bpm_down": "bpm_down", "speed_down": "tempo_down",
    "vol_up": "vol_up", "volume_up": "vol_up", "louder": "vol_up",
    "vol_down": "vol_down", "volume_down": "vol_down", "quieter": "vol_down",
    "style_switch": "style_switch", "style": "style", "style_next": "style_switch",
    "style_prev": "style_switch", "style_previous": "style_switch",
    "zone_on": "zone_on", "layer_on": "zone_on",
    "zone_off": "zone_off", "layer_off": "zone_off",
}
GESTURE_IDS = {name: index for index, name in enumerate(CANONICAL_GESTURES)}


def map_gesture_label(label: Any) -> str:
    text = str(label).strip()
    return _LABEL_ALIASES.get(text, _LABEL_ALIASES.get(text.lower(), text.lower()))


def normalize_prediction(result: dict[str, Any]) -> dict[str, Any]:
    normalized = dict(result)
    raw_label = normalized.get("gesture", "idle")
    gesture = map_gesture_label(raw_label)
    normalized["raw_gesture"] = str(raw_label)
    normalized["gesture"] = gesture
    normalized["gesture_id"] = GESTURE_IDS.get(gesture, int(normalized.get("gesture_id", -1)))

    probabilities = normalized.get("all_probs", {})
    if isinstance(probabilities, dict):
        mapped: dict[str, float] = {}
        for label, probability in probabilities.items():
            key = map_gesture_label(label)
            try:
                mapped[key] = mapped.get(key, 0.0) + float(probability)
            except (TypeError, ValueError):
                continue
        normalized["all_probs"] = mapped
    return normalized

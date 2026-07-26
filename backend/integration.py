"""Integration helpers for the PC-side model and legacy local test pipelines."""

from __future__ import annotations

import os
import threading
import time
from typing import Any

from database import insert_prediction, insert_sensor_record
from model_service import model_service
from gesture_mapping import normalize_prediction
from pi_gateway import pi_gateway
from sonic_pi import sonic_pi_adapter
from state import live_state

# ── 预测自动联动 LED（默认关；AIOT_LED_AUTO_* 环境变量控制）────────────────
# 推理步长 3 帧 ≈ 每秒最多 ~10 次预测。触发节流分两层：
#   1) 同一手势重复触发：COOLDOWN_S 内抑制（防同一动作被连续预测刷屏）；
#   2) 不同手势：PREEMPT_MIN_S 后即可立即打断前一个灯效（新动作优先，
#      防频闪下限）。Pi 侧 led_consumer 收到新命令即抢占当前灯效。
# 只有真正发出去才占用冷却（Pi 离线时 send 返回 False，下个预测周期自动重试）。
# GESTURE_MIN：按手势单独提高置信度门槛（"gesture:0.8,other:0.7"），
# 右拳 gesture_start 易误触发，默认单独抬到 0.75。
def _parse_gesture_min_map(raw: str) -> dict[str, float]:
    """解析 "gesture:0.8,other:0.7" 为 {手势: 置信度门槛}（钳到 0..1）。"""
    overrides: dict[str, float] = {}
    for item in raw.split(","):
        name, sep, value = item.partition(":")
        if not sep or not name.strip():
            continue
        try:
            overrides[name.strip()] = max(0.0, min(1.0, float(value)))
        except ValueError:
            continue
    return overrides


LED_AUTO_ENABLED = os.getenv("AIOT_LED_AUTO_ENABLED", "0").lower() in {
    "1", "true", "yes", "on",
}
LED_AUTO_MIN_CONFIDENCE = float(os.getenv("AIOT_LED_AUTO_MIN_CONFIDENCE", "0.6"))
LED_AUTO_GESTURE_MIN = _parse_gesture_min_map(
    os.getenv("AIOT_LED_AUTO_GESTURE_MIN", "gesture_start:0.75")
)
LED_AUTO_COOLDOWN_S = float(os.getenv("AIOT_LED_AUTO_COOLDOWN_S", "1.0"))
LED_AUTO_PREEMPT_MIN_S = float(os.getenv("AIOT_LED_AUTO_PREEMPT_MIN_S", "0.5"))
LED_AUTO_BRIGHTNESS = max(0.0, min(1.0, float(os.getenv("AIOT_LED_AUTO_BRIGHTNESS", "0.5"))))
LED_AUTO_DURATION_MS = max(0, int(os.getenv("AIOT_LED_AUTO_DURATION_MS", "3000")))
LED_AUTO_SKIP_GESTURES = frozenset(
    g.strip()
    for g in os.getenv("AIOT_LED_AUTO_SKIP_GESTURES", "idle").split(",")
    if g.strip()
)
_led_auto_lock = threading.Lock()
_led_auto_last = {"at": 0.0, "gesture": None}

# ── 预测自动联动音乐（OSC → Sonic Pi，默认开；AIOT_MUSIC_AUTO_* 环境变量）────
# 与 LED 双层节流同构，解决"保持一个动作时音乐调整/accent 连发"的问题：
#   事件类手势（start/stop/downbeat/upbeat/cue）：边缘语义——同手势
#       EVENT_COOLDOWN_S 冷却、异手势 PREEMPT_MIN_S 后可抢占（同 LED）；
#   连续类手势（渐强/渐弱，CONT_GESTURES）：斜坡语义——同手势每
#       CONT_RATE_S 才应用一次 ±0.05（全量程约 5 s），异手势同受抢占下限。
# 未通过节流的预测仍更新 current_prediction（Dashboard 可见），但不应用
# 音乐副作用、不推 OSC。
MUSIC_AUTO_ENABLED = os.getenv("AIOT_MUSIC_AUTO_ENABLED", "1").lower() in {
    "1", "true", "yes", "on",
}
MUSIC_AUTO_MIN_CONFIDENCE = float(os.getenv("AIOT_MUSIC_AUTO_MIN_CONFIDENCE", "0.5"))
MUSIC_AUTO_GESTURE_MIN = _parse_gesture_min_map(
    os.getenv("AIOT_MUSIC_AUTO_GESTURE_MIN", "gesture_start:0.8")
)
MUSIC_AUTO_EVENT_COOLDOWN_S = float(os.getenv("AIOT_MUSIC_AUTO_EVENT_COOLDOWN_S", "1.0"))
MUSIC_AUTO_PREEMPT_MIN_S = float(os.getenv("AIOT_MUSIC_AUTO_PREEMPT_MIN_S", "0.5"))
MUSIC_AUTO_CONT_RATE_S = float(os.getenv("AIOT_MUSIC_AUTO_CONT_RATE_S", "0.5"))
MUSIC_AUTO_CONT_GESTURES = frozenset(
    g.strip()
    for g in os.getenv("AIOT_MUSIC_AUTO_CONT_GESTURES", "crescendo,decrescendo").split(",")
    if g.strip()
)
MUSIC_AUTO_SKIP_GESTURES = frozenset(
    g.strip()
    for g in os.getenv("AIOT_MUSIC_AUTO_SKIP_GESTURES", "idle").split(",")
    if g.strip()
)
_music_auto_lock = threading.Lock()
_music_auto_last = {"at": 0.0, "gesture": None}


def run_prediction(window_data: Any) -> dict[str, Any]:
    result = normalize_prediction(model_service.predict(window_data))
    accept_prediction(result)
    return result


def accept_prediction(result: dict[str, Any]) -> None:
    insert_prediction(result, latency_ms=result.get("latency_ms"))
    if not _maybe_publish_music(result):
        # 未通过音乐节流：仍更新 Dashboard 预测，但不应用音乐副作用
        live_state.set_prediction(result, apply_music=False)
    _maybe_send_led(result)


def _maybe_publish_music(result: dict[str, Any]) -> bool:
    """预测达标且通过节流时：应用音乐副作用并推 OSC；否则静默跳过。"""
    if not MUSIC_AUTO_ENABLED:
        return False
    gesture = result.get("gesture")
    if not gesture or gesture in MUSIC_AUTO_SKIP_GESTURES:
        return False
    try:
        confidence = float(result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False
    if confidence < MUSIC_AUTO_GESTURE_MIN.get(gesture, MUSIC_AUTO_MIN_CONFIDENCE):
        return False
    now = time.time()
    with _music_auto_lock:
        dt = now - _music_auto_last["at"]
        if gesture == _music_auto_last["gesture"]:
            # 同手势：事件类走冷却，连续类走限速斜坡
            interval = (
                MUSIC_AUTO_CONT_RATE_S
                if gesture in MUSIC_AUTO_CONT_GESTURES
                else MUSIC_AUTO_EVENT_COOLDOWN_S
            )
            if dt < interval:
                return False
        elif dt < MUSIC_AUTO_PREEMPT_MIN_S:
            return False  # 不同手势：守住防频闪下限
        live_state.set_prediction(result, apply_music=True)
        sonic_pi_adapter.publish_prediction(result, live_state.get_music())
        _music_auto_last["at"] = now
        _music_auto_last["gesture"] = gesture
    return True


def _maybe_send_led(result: dict[str, Any]) -> bool:
    """预测达标时自动下发 led_command；各种过滤不满足时静默跳过。"""
    if not LED_AUTO_ENABLED:
        return False
    gesture = result.get("gesture")
    if not gesture or gesture in LED_AUTO_SKIP_GESTURES:
        return False
    try:
        confidence = float(result.get("confidence") or 0.0)
    except (TypeError, ValueError):
        return False
    if confidence < LED_AUTO_GESTURE_MIN.get(gesture, LED_AUTO_MIN_CONFIDENCE):
        return False
    now = time.time()
    with _led_auto_lock:
        dt = now - _led_auto_last["at"]
        if gesture == _led_auto_last["gesture"]:
            if dt < LED_AUTO_COOLDOWN_S:
                return False  # 同一手势重复触发：冷却防刷屏
        elif dt < LED_AUTO_PREEMPT_MIN_S:
            return False  # 不同手势：允许打断，但守住防频闪下限
        sent = send_pi_command("led_command", {
            "effect": gesture,
            "brightness": LED_AUTO_BRIGHTNESS,
            "duration_ms": LED_AUTO_DURATION_MS,
            "source": "backend-auto",
        })
        if sent:
            _led_auto_last["at"] = now
            _led_auto_last["gesture"] = gesture
    return sent


def send_pi_command(message_type: str, payload: dict[str, Any], **metadata: Any) -> bool:
    """Send a downlink command over the existing Pi TCP connection."""
    allowed = {"led_command", "led_state", "led_config", "system_command", "time_sync",
               "music_beat", "music_state"}
    if message_type not in allowed:
        raise ValueError(f"message_type must be one of {sorted(allowed)}")
    message = {"message_type": message_type, "payload": payload, **metadata}
    return pi_gateway.send(message)


def update_microbit(device_id: str, *, acc_x: float, acc_y: float, acc_z: float,
                    pc_ts: float | None = None) -> None:
    device = device_id.upper()
    if device not in {"L", "R"}: raise ValueError("device_id must be 'L' or 'R'")
    timestamp = float(pc_ts if pc_ts is not None else time.time())
    sample = {"acc_x": float(acc_x), "acc_y": float(acc_y), "acc_z": float(acc_z)}
    insert_sensor_record(pc_ts=timestamp, device_id=device, **sample)
    if device == "L": live_state.update_sensors(microbit_left=sample, timestamp=timestamp)
    else: live_state.update_sensors(microbit_right=sample, timestamp=timestamp)


def update_camera(hand_data: dict[str, Any] | list[Any], *, hand_count: int,
                  pc_ts: float | None = None) -> None:
    timestamp = float(pc_ts if pc_ts is not None else time.time())
    insert_sensor_record(pc_ts=timestamp, device_id="camera", hand_data=hand_data)
    live_state.update_sensors(hand_detected=hand_count > 0, hand_count=hand_count, timestamp=timestamp)

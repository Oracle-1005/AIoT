"""坐标手势识别器 —— 规则化、纯后端、Pi 零改动（session-summary §8.0-8.3）。

逐帧消费 fused_frame.camera.hands[]（~16Hz），几何判断（手型×左右×高度
×方向），不走 ML 窗口。手势集（用户定稿 8.0）：

  动态 6: 左拳=停止  右拳=开始  左掌上推=音量+  右掌下推=音量−
          左拳上推=BPM+  右拳下推=BPM−
  静态 2: 双手拳 左高右低=上一个风格 / 右高左低=下一个风格
  区域 8: 双手掌同处一带=开对应声部 / 双手拳同处一带=关对应声部
          带 Z1..Z4（高→低）= melody→harmony→bass→drums，带间死区迟滞

约定：y 向下 [0,1]（小=高）；vy>0 = 向下；计时用 received_at（实测 dt，
不假设帧率）；双手手势优先于单手；检测缺帧容缺（0.30s 内视为仍在）。
切曲不做（前端鼠标，已现成）。

动作出口：sonic_pi_adapter（OSC）+ live_state（意图同步）；测试可注入
假 action_sink 与假时钟。
"""

from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Any, Callable

from sonic_pi import sonic_pi_adapter
from state import live_state

logger = logging.getLogger(__name__)

# ── 配置（env 可调） ──────────────────────────────────────────────────────
def _flag(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() in {"1", "true", "yes", "on"}


ENABLED = _flag("AIOT_COORD_ENABLED", "1")
SWAP_HANDS = _flag("AIOT_COORD_SWAP_HANDS", "0")

# 手型分类（openness 0=拳 1=掌；finger_states 五指 1=伸 0=屈）
OPENNESS_FIST_MAX = float(os.getenv("AIOT_COORD_OPENNESS_FIST", "0.40"))
OPENNESS_PALM_MIN = float(os.getenv("AIOT_COORD_OPENNESS_PALM", "0.55"))
FIST_MAX_EXTENDED = int(os.getenv("AIOT_COORD_FIST_EXT", "1"))
PALM_MIN_EXTENDED = int(os.getenv("AIOT_COORD_PALM_EXT", "4"))

# 平滑（openness 基于原始点偏噪，后端自行 EMA——8.2 #3）
EMA_OPENNESS = 0.4
EMA_POSITION = 0.5
EMA_VELOCITY = 0.5

# 区域带（含死区）：四带之间/外侧留不激活间隔（8.3 死区拍板）
# Z1..Z4 高→低；层映射 高→低 = melody→harmony→bass→drums（8.3 声部顺序）
ZONE_BANDS = ((0.03, 0.22), (0.28, 0.47), (0.53, 0.72), (0.78, 0.97))
ZONE_LAYERS = ("melody", "harmony", "bass", "drums")

# 触发窗口（帧数，~16Hz：5≈0.3s 8≈0.5s 10≈0.6s）
HOLD_FRAMES_ZONE = int(os.getenv("AIOT_COORD_HOLD_ZONE", "5"))
HOLD_FRAMES_STYLE = int(os.getenv("AIOT_COORD_HOLD_STYLE", "8"))
HOLD_FRAMES_TRANSPORT = int(os.getenv("AIOT_COORD_HOLD_TRANSPORT", "10"))
HOLD_FRAMES_PUSH = int(os.getenv("AIOT_COORD_HOLD_PUSH", "4"))

# 速度阈值（归一化单位/秒，y 向下）
PUSH_VELOCITY = float(os.getenv("AIOT_COORD_PUSH_VEL", "0.5"))
STILL_VELOCITY = float(os.getenv("AIOT_COORD_STILL_VEL", "0.15"))

# 双手拳高度差（风格切换）
STYLE_SEPARATION = float(os.getenv("AIOT_COORD_STYLE_SEP", "0.18"))
STYLE_SEPARATION_RESET = float(os.getenv("AIOT_COORD_STYLE_SEP_RESET", "0.10"))

# 冷却/重复
REPEAT_INTERVAL_PUSH = float(os.getenv("AIOT_COORD_REPEAT_PUSH", "0.45"))
COOLDOWN_ZONE = float(os.getenv("AIOT_COORD_COOLDOWN_ZONE", "1.0"))
COOLDOWN_STYLE = float(os.getenv("AIOT_COORD_COOLDOWN_STYLE", "1.5"))
REARM_FRAMES = 5          # 手型消失多少帧后重新武装 start/stop
HAND_TIMEOUT_S = 0.30     # 超过视为手已离开（8.2 #7 容缺）

BPM_STEP = float(os.getenv("AIOT_COORD_BPM_STEP", "4"))
BPM_MIN, BPM_MAX = 72.0, 148.0   # 与后端 send_bpm / rb clamp 一致
VOLUME_STEP = float(os.getenv("AIOT_COORD_VOLUME_STEP", "0.06"))

LAYER_ENABLE = True
LAYER_DISABLE = False


def zone_for_y(y: float) -> int | None:
    """y → 带号 0..3；落在死区返回 None。"""
    for idx, (lo, hi) in enumerate(ZONE_BANDS):
        if lo <= y <= hi:
            return idx
    return None


class _HandTrack:
    """单只手的逐帧跟踪态（EMA 平滑 + 手型迟滞分类）。"""

    __slots__ = (
        "present", "last_seen", "openness", "y", "vy",
        "label", "label_missing",
    )

    def __init__(self) -> None:
        self.present = False
        self.last_seen = 0.0
        self.openness = 0.0
        self.y = 0.5
        self.vy = 0.0
        self.label = "unknown"      # fist / palm / unknown
        self.label_missing = 0      # 连续非当前手型帧数（供 re-arm）

    def update(self, openness: float, y: float, vy: float,
               extended: int, at: float) -> None:
        if not self.present:
            self.openness = openness
            self.y = y
            self.vy = vy
        else:
            self.openness += (openness - self.openness) * EMA_OPENNESS
            self.y += (y - self.y) * EMA_POSITION
            self.vy += (vy - self.vy) * EMA_VELOCITY
        self.present = True
        self.last_seen = at

        fist = (
            self.openness < OPENNESS_FIST_MAX
            and extended <= FIST_MAX_EXTENDED
        )
        palm = (
            self.openness > OPENNESS_PALM_MIN
            and extended >= PALM_MIN_EXTENDED
        )
        if fist and not palm:
            new_label = "fist"
        elif palm and not fist:
            new_label = "palm"
        else:
            new_label = self.label    # 迟滞：证据不足保持上次
        if new_label != self.label:
            self.label = new_label
            self.label_missing = 0

    def expire_if_stale(self, at: float) -> bool:
        """超时判离；本帧刚过期返回 True（供识别器即时 re-arm）。"""
        if self.present and at - self.last_seen > HAND_TIMEOUT_S:
            self.present = False
            self.label = "unknown"
            return True
        return False


class CoordinateRecognizer:
    """逐帧规则识别器。线程安全由调用方（单线程路由）保证。"""

    def __init__(
        self,
        *,
        action_sink: Callable[[str, dict[str, Any]], None] | None = None,
        enabled: bool | None = None,
        swap_hands: bool = SWAP_HANDS,
    ) -> None:
        self.enabled = ENABLED if enabled is None else enabled
        self.swap_hands = swap_hands
        self._action_sink = action_sink or self._default_action_sink
        self._hands = {"left": _HandTrack(), "right": _HandTrack()}
        self._counters: dict[str, int] = {}
        self._last_fired: dict[str, float] = {}
        self._armed: dict[str, bool] = {}
        self._last_actions: deque[dict[str, Any]] = deque(maxlen=10)
        self._frames = 0
        self._fps = 0.0
        self._last_frame_at: float | None = None

    # ── 主入口 ──────────────────────────────────────────────────────────
    def process_frame(
        self,
        payload: dict[str, Any],
        received_at: float | None = None,
    ) -> None:
        at = time.time() if received_at is None else received_at
        if self._last_frame_at is not None:
            dt = at - self._last_frame_at
            if dt > 0:
                instant = 1.0 / dt
                self._fps = instant if self._fps == 0 else (
                    self._fps * 0.9 + instant * 0.1
                )
        self._last_frame_at = at

        if not self.enabled:
            if self._frames == 0:
                self._publish_status(at)
            self._frames += 1
            return

        for hand in self._ingest(payload, at):
            track = self._hands[hand["side"]]
            track.update(
                hand["openness"], hand["y"], hand["vy"],
                hand["extended"], at,
            )
        for side, track in self._hands.items():
            # 手真正离开 = 该侧拳势结束：立即 re-arm（start=右拳 stop=左拳）
            if track.expire_if_stale(at):
                self._armed["start" if side == "right" else "stop"] = True

        self._evaluate(at)
        self._frames += 1
        self._publish_status(at)

    # ── 帧解析 ──────────────────────────────────────────────────────────
    def _ingest(
        self,
        payload: dict[str, Any],
        at: float,
    ) -> list[dict[str, Any]]:
        camera = payload.get("camera")
        if not isinstance(camera, dict):
            return []
        hands = camera.get("hands")
        if not isinstance(hands, list):
            return []

        out: list[dict[str, Any]] = []
        seen_sides: set[str] = set()
        for hand in hands:
            if not isinstance(hand, dict):
                continue
            side = str(hand.get("handedness", "")).lower()
            if side not in {"left", "right"}:
                continue
            if self.swap_hands:
                side = "right" if side == "left" else "left"
            if side in seen_sides:      # 同侧多手（未知 id 重复）取第一个
                continue
            seen_sides.add(side)

            features = hand.get("features")
            if not isinstance(features, dict):
                features = {}
            openness = _as_float(features.get("openness"), 0.0)
            finger_states = features.get("finger_states")
            extended = 0
            if isinstance(finger_states, list):
                extended = sum(1 for s in finger_states if s == 1)
            wrist = features.get("wrist_position")
            y = _as_float(wrist[1], 0.5) if (
                isinstance(wrist, (list, tuple)) and len(wrist) >= 2
            ) else 0.5
            velocity = features.get("wrist_velocity")
            vy = _as_float(velocity[1], 0.0) if (
                isinstance(velocity, (list, tuple)) and len(velocity) >= 2
            ) else 0.0

            out.append({
                "side": side,
                "openness": _clamp(openness, 0.0, 1.0),
                "y": _clamp(y, 0.0, 1.0),
                "vy": _clamp(vy, -5.0, 5.0),
                "extended": extended,
            })
        return out

    # ── 状态机 ──────────────────────────────────────────────────────────
    def _evaluate(self, at: float) -> None:
        left = self._hands["left"]
        right = self._hands["right"]

        both_fists = (
            left.present and right.present
            and left.label == "fist" and right.label == "fist"
        )
        both_palms = (
            left.present and right.present
            and left.label == "palm" and right.label == "palm"
        )

        handled = False
        if both_fists:
            handled = self._eval_two_fists(left, right, at)
        elif both_palms:
            handled = self._eval_two_palms(left, right, at)

        if not handled:
            self._reset("zone_on")
            self._reset("zone_off")
            self._reset("style")
            self._eval_single_hand(left, right, at)
        else:
            self._reset("stop")
            self._reset("start")
            self._reset("bpm_up")
            self._reset("bpm_down")
            self._reset("vol_up")
            self._reset("vol_down")

    # 双手拳：高度差→风格；同带→关声部
    def _eval_two_fists(
        self,
        left: _HandTrack,
        right: _HandTrack,
        at: float,
    ) -> bool:
        separation = abs(left.y - right.y)
        if separation >= STYLE_SEPARATION:
            self._reset("zone_off")   # 高度差明显走风格，不累计区域关计数
            direction = "previous" if left.y < right.y else "next"
            if self._armed.get("style", True):
                if self._sustain("style", HOLD_FRAMES_STYLE):
                    self._fire("style", at, direction=direction)
                    self._armed["style"] = False
            return True

        if separation < STYLE_SEPARATION_RESET:
            self._armed["style"] = True
            self._reset("style")

        left_zone = zone_for_y(left.y)
        right_zone = zone_for_y(right.y)
        if left_zone is not None and left_zone == right_zone:
            key = "zone_off"
            if self._armed.get(key, True):
                if self._sustain(key, HOLD_FRAMES_ZONE):
                    self._fire(
                        key, at,
                        layer=ZONE_LAYERS[left_zone], enabled=LAYER_DISABLE,
                    )
                    self._armed[key] = False
        else:
            # 死区/异带：重置计数并重新武装（8.3 死区迟滞）
            self._reset("zone_off")
            self._armed["zone_off"] = True
        return True

    # 双手掌：同带→开声部
    def _eval_two_palms(
        self,
        left: _HandTrack,
        right: _HandTrack,
        at: float,
    ) -> bool:
        left_zone = zone_for_y(left.y)
        right_zone = zone_for_y(right.y)
        if left_zone is not None and left_zone == right_zone:
            key = "zone_on"
            if self._armed.get(key, True):
                if self._sustain(key, HOLD_FRAMES_ZONE):
                    self._fire(
                        key, at,
                        layer=ZONE_LAYERS[left_zone], enabled=LAYER_ENABLE,
                    )
                    self._armed[key] = False
        else:
            self._reset("zone_on")
            self._armed["zone_on"] = True
        return True

    # 单手：左拳停/右拳开；左拳上推 BPM+；右拳下推 BPM−；掌推音量
    def _eval_single_hand(
        self,
        left: _HandTrack,
        right: _HandTrack,
        at: float,
    ) -> None:
        left_fist = left.present and left.label == "fist"
        right_fist = right.present and right.label == "fist"
        left_palm = left.present and left.label == "palm"
        right_palm = right.present and right.label == "palm"

        # 左拳：上推 BPM+；静置 STOP（对侧不得也是拳，否则走双手逻辑）
        if left_fist and not right_fist:
            if left.vy <= -PUSH_VELOCITY:
                self._reset("stop")
                if self._push_repeat("bpm_up", at):
                    self._fire("bpm_up", at)
            elif abs(left.vy) <= STILL_VELOCITY:
                self._reset("bpm_up")
                if self._armed.get("stop", True):
                    if self._sustain("stop", HOLD_FRAMES_TRANSPORT):
                        self._fire("stop", at)
                        self._armed["stop"] = False
            else:
                self._reset("stop")
                self._reset("bpm_up")
        else:
            self._reset("stop")
            self._reset("bpm_up")

        if not left_fist:
            self._track_rearm("stop", left, REARM_FRAMES)

        # 右拳：下推 BPM−；静置 START
        if right_fist and not left_fist:
            if right.vy >= PUSH_VELOCITY:
                self._reset("start")
                if self._push_repeat("bpm_down", at):
                    self._fire("bpm_down", at)
            elif abs(right.vy) <= STILL_VELOCITY:
                self._reset("bpm_down")
                if self._armed.get("start", True):
                    if self._sustain("start", HOLD_FRAMES_TRANSPORT):
                        self._fire("start", at)
                        self._armed["start"] = False
            else:
                self._reset("start")
                self._reset("bpm_down")
        else:
            self._reset("start")
            self._reset("bpm_down")

        if not right_fist:
            self._track_rearm("start", right, REARM_FRAMES)

        # 单掌推音量（对侧不得为掌/拳冲突）
        if left_palm and not right_palm and not right_fist:
            if left.vy <= -PUSH_VELOCITY:
                if self._push_repeat("vol_up", at):
                    self._fire("vol_up", at)
            else:
                self._reset("vol_up")
        else:
            self._reset("vol_up")

        if right_palm and not left_palm and not left_fist:
            if right.vy >= PUSH_VELOCITY:
                if self._push_repeat("vol_down", at):
                    self._fire("vol_down", at)
            else:
                self._reset("vol_down")
        else:
            self._reset("vol_down")

    # ── 计数/触发工具 ───────────────────────────────────────────────────
    def _sustain(self, key: str, frames: int) -> bool:
        """条件为真的帧调用一次；累计达标那一帧返回 True（边沿）。"""
        count = self._counters.get(key, 0) + 1
        self._counters[key] = count
        return count == frames

    def _push_repeat(self, key: str, at: float) -> bool:
        """推移动作：保持 HOLD_FRAMES_PUSH 后首发，之后按间隔重复。"""
        count = self._counters.get(key, 0) + 1
        self._counters[key] = count
        if count < HOLD_FRAMES_PUSH:
            return False
        last = self._last_fired.get(key, 0.0)
        return at - last >= REPEAT_INTERVAL_PUSH

    def _reset(self, key: str) -> None:
        self._counters[key] = 0

    def _track_rearm(self, key: str, track: _HandTrack, frames: int) -> None:
        """手型离开 N 帧后重新武装（对 start/stop 的每拳一次）。"""
        track.label_missing += 1
        if track.label_missing >= frames:
            self._armed[key] = True

    def _fire(self, name: str, at: float, **detail: Any) -> None:
        if name in {"zone_on", "zone_off", "style"}:
            cooldown = COOLDOWN_STYLE if name == "style" else COOLDOWN_ZONE
            if at - self._last_fired.get(name, 0.0) < cooldown:
                return
        self._last_fired[name] = at
        event = {"name": name, "at": at, **detail}
        self._last_actions.append(event)
        logger.info("coordinate gesture fired: %s", event)
        try:
            self._action_sink(name, detail)
        except Exception:
            logger.exception("coordinate action failed for %s", name)

    # ── 默认动作出口 ────────────────────────────────────────────────────
    @staticmethod
    def _default_action_sink(name: str, detail: dict[str, Any]) -> None:
        now = time.time()
        if name == "start":
            live_state.apply_sonic_pi_transport_intent("start", now)
            sonic_pi_adapter.send_transport("start")
        elif name == "stop":
            live_state.apply_sonic_pi_transport_intent("stop", now)
            sonic_pi_adapter.send_transport("stop")
        elif name == "bpm_up":
            _send_bpm_delta(+BPM_STEP)
        elif name == "bpm_down":
            _send_bpm_delta(-BPM_STEP)
        elif name == "vol_up":
            _send_volume_delta(+VOLUME_STEP)
        elif name == "vol_down":
            _send_volume_delta(-VOLUME_STEP)
        elif name == "style":
            sonic_pi_adapter.send_style(str(detail.get("direction", "next")))
        elif name in {"zone_on", "zone_off"}:
            layer = str(detail.get("layer", ""))
            enabled = bool(detail.get("enabled"))
            if live_state.set_music_layer(layer, enabled):
                sonic_pi_adapter.send_layer(layer, enabled)

    # ── 状态发布（前端可视化） ──────────────────────────────────────────
    def _publish_status(self, at: float) -> None:
        progress_keys = (
            "stop", "start", "bpm_up", "bpm_down", "vol_up", "vol_down",
            "zone_on", "zone_off", "style",
        )
        needed = {
            "stop": HOLD_FRAMES_TRANSPORT, "start": HOLD_FRAMES_TRANSPORT,
            "bpm_up": HOLD_FRAMES_PUSH, "bpm_down": HOLD_FRAMES_PUSH,
            "vol_up": HOLD_FRAMES_PUSH, "vol_down": HOLD_FRAMES_PUSH,
            "zone_on": HOLD_FRAMES_ZONE, "zone_off": HOLD_FRAMES_ZONE,
            "style": HOLD_FRAMES_STYLE,
        }
        live_state.apply_coordinate_status({
            "enabled": self.enabled,
            "swap_hands": self.swap_hands,
            "fps": round(self._fps, 1),
            "hands": {
                side: {
                    "present": track.present,
                    "label": track.label,
                    "openness": round(track.openness, 3),
                    "y": round(track.y, 3),
                    "vy": round(track.vy, 3),
                    "zone": zone_for_y(track.y) if track.present else None,
                }
                for side, track in self._hands.items()
            },
            "zones": {
                "bands": [list(b) for b in ZONE_BANDS],
                "layers": list(ZONE_LAYERS),
            },
            "progress": {
                key: round(min(self._counters.get(key, 0) / needed[key], 1.0), 2)
                for key in progress_keys
            },
            "last_actions": list(self._last_actions),
            "updated_at": at,
        })


# ── 模块级辅助 ──────────────────────────────────────────────────────────
def _send_bpm_delta(delta: float) -> None:
    current = _as_float(live_state.get_music().get("bpm"), 96.0)
    target = _clamp(current + delta, BPM_MIN, BPM_MAX)
    live_state.set_music_bpm(target)
    sonic_pi_adapter.send_bpm(target)


def _send_volume_delta(delta: float) -> None:
    current = _as_float(live_state.get_music().get("volume"), 0.8)
    target = _clamp(round(current + delta, 2), 0.0, 1.0)
    live_state.set_music_volume(target)
    sonic_pi_adapter.send_volume(target)


def _as_float(value: Any, default: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


coordinate_recognizer = CoordinateRecognizer()

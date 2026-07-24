#!/usr/bin/env python3
"""
GestureClassifier — 手势分类器（摄像头为主，micro:bit 为辅）

交付给 backend 的同进程模型接口（契约：docs/INTERFACE_CONTRACT.md §4.3、
docs/TASK_ASSIGNMENT.md 1.3/1.4 节）：

    from model.inference import GestureClassifier
    clf = GestureClassifier(model_path="model/models/gesture_classifier.pkl")
    result = clf.predict(window_data)   # window_data 见 backend/inference_pipeline.py

两种工作模式：
1. 规则模式（当前默认）：从相机窗口特征（腕部速度/轨迹/张合度趋势）做
   9 手势规则分类。契约 1.5 节官方兜底，训练数据未采集前保证链路可用。
2. 模型模式：gesture_classifier.pkl 内含 feature_version 与本类一致且带
   sklearn 模型时自动启用；数据采集重训后热替换，接口不变。

标签集（与 backend/gesture_mapping.py 的 CANONICAL_GESTURES 一致，与
hardware/raspberry_pi_iot/led/controller.py 的 9 手势动画一一对应）：
    idle / gesture_start / stop / downbeat / upbeat /
    crescendo / decrescendo / left_cue / right_cue
"""

from __future__ import annotations

import math
import os
import pickle
import time
from typing import Any

# 与 backend/gesture_mapping.py 保持一致（顺序即 gesture_id）
CANONICAL_GESTURES = (
    "idle", "gesture_start", "stop", "downbeat", "upbeat",
    "crescendo", "decrescendo", "left_cue", "right_cue",
)
GESTURE_IDS = {name: idx for idx, name in enumerate(CANONICAL_GESTURES)}

FEATURE_VERSION = "camera-v1"   # 训练 bundle 需带相同 feature_version 才启用

# 规则阈值（归一化坐标单位/秒；wrist_position 为 MediaPipe 归一化坐标，
# 图像坐标系 y 向下：+dy = 向下运动）。均为保守初值，采到真实数据后再调。
THRESH = {
    "still_speed": 0.06,     # 低于此速度视为静止
    "active_speed": 0.18,    # 高于此速度视为有效运动
    "strong_speed": 0.45,    # 强运动（拍点类）峰值门槛
    "downbeat_vy": 0.40,     # 强拍向下速度峰值门槛（+dy）
    "upbeat_vy": -0.30,      # 弱拍向上速度峰值门槛（-dy）
    "trend_delta": 0.08,     # 速度包络前后半窗差（渐强/渐弱）
    "rise_dy": -0.04,        # 窗口内手上抬位移（y 减小）
    "drop_dy": 0.04,         # 窗口内手下降位移（y 增大）
    "cue_ratio": 3.0,        # 提示手势的双手活跃度比（一侧明显动/另一侧静）
    "cue_min_speed": 0.20,   # 提示侧最低活跃度
}


# ---------------------------------------------------------------------------
# 窗口数据提取（吃 backend/inference_pipeline.py 的 model_input 格式）
# ---------------------------------------------------------------------------

def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _hand_series(items: list[dict] | None) -> dict:
    """把单只手的相机窗口整理成时间序列（位置/速度/张合度）。

    输入 item 形如 {"timestamp", "received_at", "data": {"features": {...}}}。
    时间戳单位不固定（可能 ns 或 s），速度改用相邻样本差分并按数量级自适应。
    """
    ts, pos, openness = [], [], []
    for it in items or []:
        if not isinstance(it, dict):
            continue
        feats = (it.get("data") or {}).get("features") or {}
        wp = feats.get("wrist_position")
        if not (isinstance(wp, (list, tuple)) and len(wp) >= 2):
            continue
        ts.append(_as_float(it.get("timestamp", it.get("received_at", 0.0))))
        pos.append((_as_float(wp[0]), _as_float(wp[1]),
                    _as_float(wp[2]) if len(wp) > 2 else 0.0))
        op = feats.get("openness")
        openness.append(_as_float(op) if isinstance(op, (int, float)) else None)

    speeds, vys = [], []
    for i in range(1, len(pos)):
        dt = ts[i] - ts[i - 1]
        if dt <= 0:
            continue
        # 时间戳可能是 ns：间隔大于 1e6 视为 ns 并换算
        if dt > 1e6:
            dt /= 1e9
        elif dt > 1e3:
            dt /= 1e3
        if dt <= 0 or dt > 1.0:   # 丢帧大洞不参与速度统计
            continue
        dx = (pos[i][0] - pos[i - 1][0]) / dt
        dy = (pos[i][1] - pos[i - 1][1]) / dt
        dz = (pos[i][2] - pos[i - 1][2]) / dt
        speeds.append(math.sqrt(dx * dx + dy * dy + dz * dz))
        vys.append(dy)

    def _valid_open(values: list[float | None]) -> list[float]:
        return [v for v in values if v is not None]

    return {
        "n": len(pos),
        "speeds": speeds,
        "vys": vys,
        "dy_disp": (pos[-1][1] - pos[0][1]) if len(pos) >= 2 else 0.0,
        "open_first": (sum(v) / len(v)) if (v := _valid_open(openness[:5])) else None,
        "open_last": (sum(v) / len(v)) if (v := _valid_open(openness[-5:])) else None,
    }


def _series_stats(series: dict) -> dict:
    speeds = series["speeds"]          # 保持时间序（start/end/trend 依赖时间序）
    ordered = sorted(speeds)           # 仅 p90 用排序副本
    n = len(speeds)
    half = max(1, n // 2)

    def _mean(values: list[float]) -> float:
        return sum(values) / len(values) if values else 0.0

    return {
        "mean_speed": _mean(speeds),
        "p90_speed": ordered[int(0.9 * (n - 1))] if n else 0.0,
        "start_speed": _mean(speeds[:3]),
        "end_speed": _mean(speeds[-3:]),
        "vy_down_peak": max(series["vys"], default=0.0),      # +dy = 向下
        "vy_up_peak": min(series["vys"], default=0.0),        # -dy = 向上
        "trend": _mean(speeds[half:]) - _mean(speeds[:half]) if n >= 2 else 0.0,
        "dy_disp": series["dy_disp"],
        "open_delta": ((series["open_last"] - series["open_first"])
                       if series["open_first"] is not None
                       and series["open_last"] is not None else 0.0),
    }


def _microbit_summary(hands: dict | None) -> dict:
    """micro:bit 辅助通道摘要（耐稀疏；兼容 ax_mg 与 acc_x 两种键名）。"""
    out = {"left": {"available": False, "mean_mag": 0.0, "jerk_max": 0.0},
           "right": {"available": False, "mean_mag": 0.0, "jerk_max": 0.0}}
    for hand in ("left", "right"):
        info = (hands or {}).get(hand) or {}
        samples = info.get("samples") or []
        mags = []
        for s in samples:
            if not isinstance(s, dict):
                continue
            ax = _as_float(s.get("ax_mg", s.get("acc_x")))
            ay = _as_float(s.get("ay_mg", s.get("acc_y")))
            az = _as_float(s.get("az_mg", s.get("acc_z")))
            mags.append(math.sqrt(ax * ax + ay * ay + az * az))
        if mags:
            jerks = [abs(mags[i] - mags[i - 1]) for i in range(1, len(mags))]
            out[hand] = {
                "available": True,
                "mean_mag": sum(mags) / len(mags),
                "jerk_max": max(jerks, default=0.0),
            }
    return out


# ---------------------------------------------------------------------------
# GestureClassifier
# ---------------------------------------------------------------------------

class GestureClassifier:
    """契约 §4.3 的同进程手势分类器（规则版先行，pkl 可热插拔）。"""

    FEATURE_VERSION = FEATURE_VERSION

    def __init__(self, model_path: str | None = None, **_kwargs: Any) -> None:
        self.model_path = model_path
        self._model = None
        self._model_features: list[str] = []
        self.mode = "rules"
        if model_path:
            self._try_load_model(model_path)

    def _try_load_model(self, model_path: str) -> None:
        """加载训练 bundle；格式不符（如旧的 50Hz micro:bit 模型）则回退规则。"""
        try:
            with open(model_path, "rb") as f:
                bundle = pickle.load(f)  # noqa: S301 — 模型文件为本团队产物
            if (isinstance(bundle, dict)
                    and bundle.get("feature_version") == self.FEATURE_VERSION
                    and hasattr(bundle.get("model"), "predict_proba")):
                self._model = bundle["model"]
                self._model_features = list(bundle.get("feature_names", []))
                self.mode = "model"
        except (OSError, pickle.UnpicklingError, AttributeError,
                ValueError, KeyError, EOFError):
            self._model = None
            self.mode = "rules"

    # -- 契约接口 ----------------------------------------------------------

    def predict(self, window_data: Any) -> dict[str, Any]:
        """六字段契约输出；任何内部异常都回退 idle，绝不抛出。"""
        try:
            return self._predict_inner(window_data)
        except Exception as exc:  # 兜底：链路可用性优先于单帧准确率
            return self._result("idle", 0.0, {g: (1.0 if g == "idle" else 0.0)
                                              for g in CANONICAL_GESTURES},
                                features_used=0, extra={"error": str(exc)})

    # -- 内部实现 ----------------------------------------------------------

    def _predict_inner(self, window_data: Any) -> dict[str, Any]:
        wd = window_data if isinstance(window_data, dict) else {}
        cam_hands = (wd.get("camera_features") or {}).get("hands") or {}
        mb_hands = (wd.get("microbit_features") or {}).get("hands") or {}

        stats = {h: _series_stats(_hand_series(cam_hands.get(h)))
                 for h in ("left", "right")}
        mb = _microbit_summary(mb_hands)

        if self._model is not None:
            probs = self._model_probs(stats, mb)
            extra = {"mode": "model"}
        else:
            probs = self._rule_probs(stats, mb)
            extra = {"mode": "rules"}

        gesture = max(probs, key=probs.get)
        confidence = min(0.95, probs[gesture]) if self._model is None else probs[gesture]
        used = sum(1 for h in ("left", "right") if stats[h]["mean_speed"] > 0) \
            + sum(1 for h in ("left", "right") if mb[h]["available"])
        return self._result(gesture, confidence, probs,
                            features_used=used, extra=extra)

    def _result(self, gesture: str, confidence: float,
                probs: dict[str, float], features_used: int,
                extra: dict | None = None) -> dict[str, Any]:
        confidence = max(0.0, min(1.0, float(confidence)))
        out = {
            "gesture": gesture,
            "confidence": round(confidence, 4),
            "gesture_id": GESTURE_IDS.get(gesture, 0),
            "timestamp": time.time(),
            "features_used": int(features_used),
            "all_probs": {g: round(float(probs.get(g, 0.0)), 4)
                          for g in CANONICAL_GESTURES},
        }
        if extra:
            out.update(extra)
        return out

    # -- 规则模式 ----------------------------------------------------------

    def _rule_probs(self, stats: dict, mb: dict) -> dict[str, float]:
        # 主手 = 活动度更高的一侧（指挥通常单主手）
        dom = "right" if stats["right"]["p90_speed"] >= stats["left"]["p90_speed"] else "left"
        oth = "left" if dom == "right" else "right"
        d, o = stats[dom], stats[oth]
        t = THRESH

        # micro:bit 辅助：有数据且 jerk 明显 → 轻微加信心（不动主分类）
        mb_boost = 1.15 if (mb[dom]["available"] and mb[dom]["jerk_max"] > 150) else 1.0

        scores = {g: 0.05 for g in CANONICAL_GESTURES}

        both_still = (d["p90_speed"] < t["still_speed"]
                      and o["p90_speed"] < t["still_speed"])
        if both_still or d["mean_speed"] < 1e-6:
            scores["idle"] += 2.6

        # 停止/切断：窗内曾运动、末端静止（或双手张合度急收）
        if d["p90_speed"] > t["active_speed"] and d["end_speed"] < t["still_speed"]:
            scores["stop"] += 1.8
        if d["open_delta"] < -0.25 and d["p90_speed"] > t["active_speed"]:
            scores["stop"] += 1.0

        # 开始：起点静止 → 末端运动（静到动的爬升）
        if d["start_speed"] < t["still_speed"] and d["end_speed"] > t["active_speed"]:
            scores["gesture_start"] += 1.8

        # 强拍/弱拍：竖直方向速度峰值主导（图像坐标 +dy 向下）
        if d["vy_down_peak"] > t["downbeat_vy"] and d["p90_speed"] > t["strong_speed"]:
            scores["downbeat"] += 1.6 + min(0.8, d["vy_down_peak"] - t["downbeat_vy"])
        if d["vy_up_peak"] < t["upbeat_vy"] and d["p90_speed"] > t["active_speed"]:
            scores["upbeat"] += 1.3 + min(0.6, abs(d["vy_up_peak"] - t["upbeat_vy"]))

        # 渐强/渐弱：速度包络趋势 + 手位升降（+ 张合度变化辅助）
        if d["trend"] > t["trend_delta"]:
            scores["crescendo"] += 1.2
            if d["dy_disp"] < t["rise_dy"]:
                scores["crescendo"] += 0.5
            if d["open_delta"] > 0.1:
                scores["crescendo"] += 0.3
        if d["trend"] < -t["trend_delta"]:
            scores["decrescendo"] += 1.2
            if d["dy_disp"] > t["drop_dy"]:
                scores["decrescendo"] += 0.5
            if d["open_delta"] < -0.1:
                scores["decrescendo"] += 0.3

        # 左/右手提示：一侧活跃另一侧静止
        if (stats["left"]["p90_speed"] > t["cue_min_speed"]
                and stats["left"]["p90_speed"] > t["cue_ratio"] * max(stats["right"]["p90_speed"], 1e-6)):
            scores["left_cue"] += 1.6
        if (stats["right"]["p90_speed"] > t["cue_min_speed"]
                and stats["right"]["p90_speed"] > t["cue_ratio"] * max(stats["left"]["p90_speed"], 1e-6)):
            scores["right_cue"] += 1.6

        # softmax 归一化（温度 0.9，规则分布别太平）
        exps = {g: math.exp(min(20.0, s * mb_boost) / 0.9) for g, s in scores.items()}
        z = sum(exps.values())
        return {g: v / z for g, v in exps.items()}

    # -- 模型模式（训练 bundle 就绪后启用） ---------------------------------

    def _model_probs(self, stats: dict, mb: dict) -> dict[str, float]:
        vector = self._build_feature_vector(stats, mb)
        raw = self._model.predict_proba([vector])[0]
        labels = list(getattr(self._model, "classes_", CANONICAL_GESTURES))
        probs = {g: 0.0 for g in CANONICAL_GESTURES}
        for label, p in zip(labels, raw):
            if str(label) in probs:
                probs[str(label)] = float(p)
        total = sum(probs.values()) or 1.0
        return {g: p / total for g, p in probs.items()}

    def _build_feature_vector(self, stats: dict, mb: dict) -> list[float]:
        """固定顺序特征向量（训练侧必须用同一份 FEATURE_NAMES 导出 bundle）。"""
        vec: list[float] = []
        for hand in ("left", "right"):
            s = stats[hand]
            vec.extend([
                s["mean_speed"], s["p90_speed"], s["start_speed"], s["end_speed"],
                s["vy_down_peak"], s["vy_up_peak"], s["trend"], s["dy_disp"],
                s["open_delta"],
            ])
            m = mb[hand]
            vec.extend([1.0 if m["available"] else 0.0, m["mean_mag"], m["jerk_max"]])
        return vec


# 训练侧导出 bundle 时应记录的特征名（顺序与 _build_feature_vector 一致）
FEATURE_NAMES = [
    f"{hand}_{name}"
    for hand in ("left", "right")
    for name in ("mean_speed", "p90_speed", "start_speed", "end_speed",
                 "vy_down_peak", "vy_up_peak", "trend", "dy_disp",
                 "open_delta", "mb_available", "mb_mean_mag", "mb_jerk_max")
]

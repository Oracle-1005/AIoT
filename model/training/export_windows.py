#!/usr/bin/env python3
"""export_windows.py — 从后端 SQLite 回放 fused_frame，导出 camera-v1 训练窗口

用法：
  # 1) 管线验证：无标签回放实链数据，与 predictions 表逐窗对比（应 ~100% 一致）
  python model/training/export_windows.py --validate-rules \
      --since "2026-07-24 13:00" --until "2026-07-24 14:00" --source-like "192.168.43.%"

  # 2) 有标签导出（5.2 录制后，配合 record_sessions.py 的 JSONL 打标）
  python model/training/export_windows.py \
      --sessions data/training_sessions.jsonl \
      --out data/processed/gesture_windows.npz

设计约束（勿违反）：
- 窗口化逻辑逐行复刻 backend/inference_pipeline.py（30 帧窗 / ≥15 帧门 /
  每 3 帧一窗 / micro:bit 按 sample_sequence 去重），但不做推理、不写库；
- 特征提取 verbatim 复用 model.inference.gesture_classifier 的
  _hand_series / _series_stats / _microbit_summary / _build_feature_vector。
  任何重写都会造成训练-推理特征漂移（bundle 的 feature_names 推理侧不校验）。
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import tempfile
import time
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable

# 防御：管道/重定向到 GBK 环境时 ⚠ 等字符不让 print 崩（评审实证可复现）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from model.inference.gesture_classifier import (  # noqa: E402
    CANONICAL_GESTURES,
    FEATURE_NAMES,
    FEATURE_VERSION,
    GestureClassifier,
    _hand_series,
    _microbit_summary,
    _series_stats,
)

HANDS = ("left", "right")
DEFAULT_DB = _REPO_ROOT / "data" / "aiot.db"
DEFAULT_OUT = _REPO_ROOT / "data" / "processed" / "gesture_windows.npz"

# 与 inference_pipeline.py 保持一致的窗口参数（线上默认值）
WINDOW_SIZE = 30
MIN_CAMERA_FRAMES = 15
INFER_EVERY_N_FRAMES = 3


# ---------------------------------------------------------------------------
# 窗口化（逐行复刻 backend/inference_pipeline.py 语义；回放侧拥有数据，免 deepcopy）
# ---------------------------------------------------------------------------

def _hand_name(value: Any) -> str | None:
    normalized = str(value or "").strip().lower()
    if normalized in HANDS:
        return normalized
    return None


def _camera_hands(camera: dict[str, Any]) -> dict[str, dict[str, Any]]:
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
            routed[hand] = hand_data
    return routed


def _zero_microbit_sample(hand: str) -> dict[str, Any]:
    return {
        "hand": hand,
        "acc_x": 0.0,
        "acc_y": 0.0,
        "acc_z": 0.0,
        "available": False,
    }


class ReplayWindower:
    """复刻 InferencePipeline 的滑窗状态机（去掉 model_service 门与推理调用）。"""

    def __init__(self, window_size: int = WINDOW_SIZE,
                 min_camera_frames: int = MIN_CAMERA_FRAMES,
                 infer_every: int = INFER_EVERY_N_FRAMES) -> None:
        self.window_size = window_size
        self.min_camera_frames = min_camera_frames
        self.infer_every = infer_every
        self.reset()

    def reset(self) -> None:
        self._camera_samples = {h: deque(maxlen=self.window_size) for h in HANDS}
        self._microbit_samples = {h: deque(maxlen=self.window_size) for h in HANDS}
        self._last_sequence: dict[str, Any] = {h: None for h in HANDS}
        self._camera_frame_count = 0

    def add_frame(self, payload: dict[str, Any],
                  received_at: float) -> dict[str, Any] | None:
        """喂入一帧 fused_frame payload；到达推理节拍时返回 model_input 窗口。"""
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

        # fused_frame 即相机节拍，即使没检测到手
        self._camera_frame_count += 1

        microbits = payload.get("microbits", [])
        if isinstance(microbits, list):
            for sample in microbits:
                if not isinstance(sample, dict):
                    continue
                hand = _hand_name(sample.get("hand", sample.get("device_id")))
                if hand is None:
                    device_id = str(sample.get("device_id", "")).upper()
                    hand = "left" if device_id == "L" else "right" if device_id == "R" else None
                if hand is None:
                    continue

                sequence = sample.get("sample_sequence", sample.get("sequence"))
                if sequence is not None and sequence == self._last_sequence[hand]:
                    continue
                if sequence is not None:
                    self._last_sequence[hand] = sequence

                item = dict(sample)
                item["hand"] = hand
                item["available"] = True
                item["received_at"] = received_at
                self._microbit_samples[hand].append(item)

        if self._camera_frame_count % self.infer_every != 0:
            return None
        if max(len(v) for v in self._camera_samples.values()) < self.min_camera_frames:
            return None

        return self._build_model_input(payload, received_at)

    def _build_model_input(self, payload: dict[str, Any],
                           received_at: float) -> dict[str, Any]:
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
            "camera_features": {
                "primary": True,
                "fps": 30,
                "window_size": self.window_size,
                "hands": camera_windows,
            },
            "microbit_features": {
                "primary": False,
                "nominal_hz": 6.7,
                "hands": microbit_windows,
            },
            "cross_modal_features": {
                "fusion": payload.get("fusion", {}),
                "timestamps": payload.get("timestamps", {}),
                "frame_id": payload.get(
                    "frame_id",
                    payload.get("camera", {}).get("frame_id")
                    if isinstance(payload.get("camera"), dict) else None,
                ),
            },
        }


# ---------------------------------------------------------------------------
# 特征提取（verbatim 复用 classifier 实现，禁止重写）
# ---------------------------------------------------------------------------

_RULES: GestureClassifier | None = None


def _rules() -> GestureClassifier:
    global _RULES
    if _RULES is None:
        _RULES = GestureClassifier()  # 无 model_path → 规则模式
    return _RULES


def window_to_vector(window_data: dict[str, Any]) -> list[float]:
    cam = (window_data.get("camera_features") or {}).get("hands") or {}
    mb_hands = (window_data.get("microbit_features") or {}).get("hands") or {}
    stats = {h: _series_stats(_hand_series(cam.get(h))) for h in HANDS}
    mb = _microbit_summary(mb_hands)
    vec = _rules()._build_feature_vector(stats, mb)  # noqa: SLF001 — 训练侧指定复用
    if len(vec) != len(FEATURE_NAMES):
        raise RuntimeError(f"特征维度漂移：{len(vec)} != {len(FEATURE_NAMES)}")
    return vec


# ---------------------------------------------------------------------------
# DB 流式读取
# ---------------------------------------------------------------------------

def snapshot_db(db_path: Path) -> Path:
    """把活库备份成临时快照再扫描。

    流式游标在整个扫描期间持 SHARED 锁；后端 insert 的 busy timeout 是 10s，
    扫描超过 10s 后每一帧/每一次预测都会静默丢失（评审实证可复现）。
    sqlite backup API 对并发写有重试，后端写入只受秒级以下影响。
    """
    fd, tmp = tempfile.mkstemp(prefix="aiot_export_", suffix=".db")
    os.close(fd)
    src = sqlite3.connect(f"file:{Path(db_path).as_posix()}?mode=ro", uri=True)
    dst = sqlite3.connect(tmp)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    return Path(tmp)


def stream_fused_frames(db_path: Path, since: float | None, until: float | None,
                        source_like: str | None) -> Iterable[tuple[int, float, str]]:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    sql = ("SELECT id, received_at, payload FROM pi_messages "
           "WHERE message_type = 'fused_frame'")
    params: list[Any] = []
    if since is not None:
        sql += " AND received_at >= ?"
        params.append(since)
    if until is not None:
        sql += " AND received_at <= ?"
        params.append(until)
    if source_like:
        sql += " AND source_address LIKE ?"
        params.append(source_like)
    sql += " ORDER BY received_at ASC, id ASC"
    try:
        yield from conn.execute(sql, params)
    finally:
        conn.close()


def load_stored_predictions(db_path: Path, since: float | None,
                            until: float | None) -> list[tuple[float, str]]:
    uri = f"file:{Path(db_path).as_posix()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    sql = "SELECT pc_ts, gesture FROM predictions WHERE 1=1"
    params: list[Any] = []
    if since is not None:
        sql += " AND pc_ts >= ?"
        params.append(since)
    if until is not None:
        sql += " AND pc_ts <= ?"
        params.append(until)
    sql += " ORDER BY pc_ts ASC, id ASC"
    try:
        return [(float(ts), str(g)) for ts, g in conn.execute(sql, params)]
    finally:
        conn.close()


def parse_time(value: str | None) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).timestamp()
        except ValueError:
            continue
    raise SystemExit(
        f"无法解析时间 {value!r}：支持 epoch 秒或 'YYYY-MM-DD HH:MM[:SS]' 本地时间"
    )


# ---------------------------------------------------------------------------
# 模式 1：规则回放验证
# ---------------------------------------------------------------------------

def validate_rules(db: Path, since: float | None, until: float | None,
                   source_like: str | None, min_agreement: float,
                   max_frames: int | None, min_camera_frames: int) -> int:
    windower = ReplayWindower(min_camera_frames=min_camera_frames)
    replay_preds: list[tuple[float, str]] = []
    frames = 0
    zero_feature_windows = 0
    t0 = time.time()

    for _row_id, received_at, payload_text in stream_fused_frames(
            db, since, until, source_like):
        frames += 1
        if max_frames is not None and frames > max_frames:
            break
        payload = json.loads(payload_text)
        window = windower.add_frame(payload, received_at)
        if window is None:
            continue
        result = _rules().predict(window)
        if result.get("features_used", 0) == 0:
            zero_feature_windows += 1
        replay_preds.append((received_at, result["gesture"]))

    stored = load_stored_predictions(db, since, until)

    n = min(len(replay_preds), len(stored))
    matches = sum(
        1 for i in range(n) if replay_preds[i][1] == stored[i][1]
    )
    agreement = (matches / n * 100.0) if n else 0.0

    print("=" * 64)
    print("  规则回放验证（replay vs predictions 表）")
    print("=" * 64)
    print(f"  DB:                {db}")
    print(f"  时间窗:            since={since} until={until} source={source_like!r}")
    print(f"  fused_frame 读入:  {frames}")
    print(f"  回放窗口数:        {len(replay_preds)}（其中零特征窗 {zero_feature_windows}）")
    print(f"  库存预测数:        {len(stored)}")
    print(f"  对齐比较:          {n} 对，一致 {matches}，一致率 {agreement:.2f}%")
    print(f"  耗时:              {time.time() - t0:.1f}s")

    if len(replay_preds) != len(stored):
        print(f"  ⚠ 窗口数与预测数不等（{len(replay_preds)} vs {len(stored)}），"
              f"按前缀 {n} 对比较；若一致率低先检查时间窗是否覆盖单次会话")

    shown = 0
    for i in range(n):
        if replay_preds[i][1] != stored[i][1] and shown < 10:
            ts = replay_preds[i][0]
            print(f"  不符 #{i}: ts={ts:.3f} replay={replay_preds[i][1]} "
                  f"stored={stored[i][1]}")
            shown += 1

    ok = n > 0 and agreement >= min_agreement
    print(f"\n  结果: {'PASS' if ok else 'FAIL'}（阈值 {min_agreement}%）")
    return 0 if ok else 1


# ---------------------------------------------------------------------------
# 模式 2：有标签导出
# ---------------------------------------------------------------------------

def load_sessions(path: Path, edge_trim_s: float) -> list[dict[str, Any]]:
    sessions: list[dict[str, Any]] = []
    for lineno, line in enumerate(
            Path(path).read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line:
            continue
        rec = json.loads(line)
        label = str(rec["label"])
        if label not in CANONICAL_GESTURES:
            raise SystemExit(f"{path}:{lineno} 未知标签 {label!r}（须为 9 个 canonical 之一）")
        start = float(rec["start_ts"]) + edge_trim_s
        end = float(rec["end_ts"]) - edge_trim_s
        if end <= start:
            print(f"  ⚠ {path}:{lineno} 会话过短（修边后 {end - start:.2f}s），跳过")
            continue
        sessions.append({"label": label, "start": start, "end": end})
    sessions.sort(key=lambda s: s["start"])
    for prev, cur in zip(sessions, sessions[1:]):
        if cur["start"] <= prev["end"]:
            raise SystemExit(
                f"会话时间重叠：{prev['label']}@{prev['start']:.1f} 与 "
                f"{cur['label']}@{cur['start']:.1f}，请检查 {path}"
            )
    return sessions


def export_labeled(db: Path, sessions_path: Path, out_path: Path,
                   edge_trim_s: float, since: float | None, until: float | None,
                   source_like: str | None, max_frames: int | None,
                   min_camera_frames: int) -> int:
    import numpy as np  # 仅导出模式需要

    sessions = load_sessions(sessions_path, edge_trim_s)
    if not sessions:
        raise SystemExit(f"{sessions_path} 没有可用会话")

    # DB 查询范围收敛到会话覆盖区间（调用方可再叠加 --since/--until）
    q_since = sessions[0]["start"] if since is None else max(since, sessions[0]["start"])
    q_until = sessions[-1]["end"] if until is None else min(until, sessions[-1]["end"])

    windower = ReplayWindower(min_camera_frames=min_camera_frames)
    X: list[list[float]] = []
    y: list[str] = []
    ts_out: list[float] = []
    rule_preds: list[str] = []
    session_idx: list[int] = []
    frames = 0
    si = 0

    for _row_id, received_at, payload_text in stream_fused_frames(
            db, q_since, q_until, source_like):
        frames += 1
        if max_frames is not None and frames > max_frames:
            break
        while si < len(sessions) and received_at > sessions[si]["end"]:
            si += 1
            windower.reset()  # 会话边界：窗口不得跨标签
        if si >= len(sessions):
            break
        session = sessions[si]
        if received_at < session["start"]:
            continue  # 会话间隙，不喂帧（保持 windower 干净）
        payload = json.loads(payload_text)
        window = windower.add_frame(payload, received_at)
        if window is None:
            continue
        X.append(window_to_vector(window))
        y.append(session["label"])
        ts_out.append(received_at)
        rule_preds.append(_rules().predict(window)["gesture"])
        session_idx.append(si)

    if not X:
        raise SystemExit("没有产出任何窗口：检查会话时间窗与 DB fused_frame 是否重叠")

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        out_path,
        X=np.asarray(X, dtype=np.float32),
        y=np.asarray(y),
        ts=np.asarray(ts_out, dtype=np.float64),
        rule_pred=np.asarray(rule_preds),
        session_idx=np.asarray(session_idx, dtype=np.int32),
        feature_names=np.asarray(FEATURE_NAMES),
        feature_version=FEATURE_VERSION,
        window_params=json.dumps({
            "window_size": WINDOW_SIZE,
            "min_camera_frames": MIN_CAMERA_FRAMES,
            "infer_every_n_frames": INFER_EVERY_N_FRAMES,
            "edge_trim_s": edge_trim_s,
        }),
    )

    counts = {g: y.count(g) for g in CANONICAL_GESTURES}
    missing = [g for g, c in counts.items() if c == 0]
    summary = {
        "db": str(db),
        "sessions_file": str(sessions_path),
        "out": str(out_path),
        "exported_at": time.time(),
        "frames_read": frames,
        "windows": len(X),
        "labels": {g: c for g, c in counts.items() if c},
        "missing_labels": missing,
        "sessions_used": len({*session_idx}),
        "feature_version": FEATURE_VERSION,
    }
    sidecar = out_path.with_suffix(".summary.json")
    sidecar.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                       encoding="utf-8")

    print("=" * 64)
    print("  有标签窗口导出")
    print("=" * 64)
    print(f"  会话:       {len(sessions)} 段（使用 {summary['sessions_used']} 段）")
    print(f"  读帧:       {frames}")
    print(f"  窗口:       {len(X)}")
    for g in CANONICAL_GESTURES:
        c = counts[g]
        if c == 0:
            flag = "  ⚠ 零窗口——不补录的话，模型永远无法预测该手势！"
        elif c < 30:
            flag = "  ⚠ 样本偏少"
        else:
            flag = ""
        print(f"    {g:15s} {c:5d}{flag}")
    if missing:
        print(f"  ⚠ 缺失手势: {', '.join(missing)}")
    print(f"  输出:       {out_path}")
    print(f"  摘要:       {sidecar}")
    return 0


# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(
        description="从后端 SQLite 回放 fused_frame，导出 camera-v1 训练窗口"
    )
    parser.add_argument("--db", type=Path, default=DEFAULT_DB,
                        help=f"SQLite 路径（默认 {DEFAULT_DB}）")
    parser.add_argument("--since", type=str, default=None,
                        help="起始时间：epoch 秒或 'YYYY-MM-DD HH:MM[:SS]' 本地时间")
    parser.add_argument("--until", type=str, default=None, help="结束时间，同上")
    parser.add_argument("--source-like", type=str, default=None,
                        help="source_address LIKE 过滤（如 '192.168.43.%%'，排除本机测试数据）")
    parser.add_argument("--max-frames", type=int, default=None, help="调试：最多读帧数")
    parser.add_argument("--min-camera-frames", type=int, default=MIN_CAMERA_FRAMES,
                        help=f"窗口触发门槛（默认 {MIN_CAMERA_FRAMES}=线上 HEAD；"
                             f"回放 7/24 上午实链数据时用 0——当时后端无此门")

    parser.add_argument("--validate-rules", action="store_true",
                        help="规则回放验证：与 predictions 表逐窗对比")
    parser.add_argument("--min-agreement", type=float, default=99.0,
                        help="验证通过阈值（%%，默认 99）")

    parser.add_argument("--sessions", type=Path, default=None,
                        help="record_sessions.py 的 JSONL 打标文件（有标签导出模式）")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"导出 npz 路径（默认 {DEFAULT_OUT}）")
    parser.add_argument("--edge-trim-s", type=float, default=0.3,
                        help="会话首尾各削去秒数，规避动作过渡污染（默认 0.3）")
    args = parser.parse_args()

    if not args.db.exists():
        raise SystemExit(f"DB 不存在: {args.db}")

    since = parse_time(args.since)
    until = parse_time(args.until)

    snapshot = snapshot_db(args.db)
    print(f"  快照: {args.db} → {snapshot}（活库不受影响）")
    try:
        if args.validate_rules:
            return validate_rules(snapshot, since, until, args.source_like,
                                  args.min_agreement, args.max_frames,
                                  args.min_camera_frames)
        if args.sessions:
            return export_labeled(snapshot, args.sessions, args.out,
                                  args.edge_trim_s, since, until,
                                  args.source_like, args.max_frames,
                                  args.min_camera_frames)
        parser.error("请指定模式：--validate-rules 或 --sessions <jsonl>")
        return 2
    finally:
        snapshot.unlink(missing_ok=True)


if __name__ == "__main__":
    sys.exit(main())

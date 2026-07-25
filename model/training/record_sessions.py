#!/usr/bin/env python3
"""record_sessions.py — 5.2 录制会话打标器

录制手势训练数据时，用键盘标记每段动作的起止；后端照常把 fused_frame 入库，
事后用 export_windows.py --sessions 按时间窗切窗打标。

操作：
  1-9   选择手势（下方菜单，顺序 = CANONICAL_GESTURES）
  空格  开始 / 结束当前段
  Q     退出（自动收尾未结束的段）

每段结束追加一行 JSONL：{"label","start_ts","end_ts","duration_s"}

录制纪律（很重要）：
- 先按数字选手势，再按空格开始；一段里持续做同一个动作，别掺别的
- 段与段之间停 1-2 秒再开始下一段（配合 export --edge-trim-s 削边）
- 开始前确认：后端在跑、Pi 已连接（fused_frame 正在入库）、机位已正
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

# 防御：管道/重定向到 GBK 环境时，⚠ 等字符不让 print 崩（真实控制台本就走 UTF-8）
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(errors="replace")
    except (AttributeError, ValueError):
        pass

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from model.inference import CANONICAL_GESTURES  # noqa: E402

DEFAULT_OUT = _REPO_ROOT / "data" / "training_sessions.jsonl"

try:
    import msvcrt

    def _getch() -> str:
        ch = msvcrt.getwch()
        if ch in ("\x00", "\xe0"):
            # 扩展键（方向键/PageUp/PageDown/F 键等）按两次读入：
            # 前缀 \x00/\xe0 + 扫描码。吞掉扫描码，防 PageDown 的 'Q' 误触退出。
            msvcrt.getwch()
            return ""
        return ch
except ImportError:  # POSIX 兜底
    import tty
    import termios

    def _getch() -> str:
        fd = sys.stdin.fileno()
        old = termios.tcgetattr(fd)
        try:
            tty.setraw(fd)
            return sys.stdin.read(1)
        finally:
            termios.tcsetattr(fd, termios.TCSADRAIN, old)


def _append_segment(path: Path, label: str, start_ts: float, end_ts: float) -> None:
    rec = {
        "label": label,
        "start_ts": start_ts,
        "end_ts": end_ts,
        "duration_s": round(end_ts - start_ts, 3),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="5.2 录制会话打标器")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT,
                        help=f"JSONL 输出（默认 {DEFAULT_OUT}）")
    args = parser.parse_args()

    print("=" * 64)
    print("  5.2 录制会话打标器")
    print("=" * 64)
    print("  前置确认：后端在跑、Pi 已连接、fused_frame 正在入库、机位已正\n")
    for i, g in enumerate(CANONICAL_GESTURES, 1):
        print(f"    {i}. {g}")
    print("\n  数字键选手势 → 空格开始 → 持续做动作 → 空格结束；Q 退出")
    print(f"  输出文件：{args.out}\n")

    armed: str | None = None
    recording: dict | None = None
    counts: dict[str, int] = {}
    total_s: dict[str, float] = {}

    while True:
        state = (f"录制中[{recording['label']}]"
                 if recording else (f"已选[{armed}]" if armed else "未选手势"))
        print(f"\r  [{state}] 按键: ", end="", flush=True)
        ch = _getch()
        print(ch)  # 回显

        if ch in ("q", "Q"):
            if recording:
                end_ts = time.time()
                _append_segment(args.out, recording["label"],
                                recording["start_ts"], end_ts)
                dur = end_ts - recording["start_ts"]
                counts[recording["label"]] = counts.get(recording["label"], 0) + 1
                total_s[recording["label"]] = total_s.get(recording["label"], 0.0) + dur
                print(f"  ■ 自动收尾 {recording['label']} ({dur:.1f}s)")
            break

        if ch.isdigit():
            idx = int(ch) - 1
            if 0 <= idx < len(CANONICAL_GESTURES):
                if recording:
                    print("  ⚠ 录制中不能换标签，先空格结束当前段")
                else:
                    armed = CANONICAL_GESTURES[idx]
                    print(f"  → 已选手势: {armed}")
            continue

        if ch == " ":
            if recording is None:
                if not armed:
                    print("  ⚠ 先按 1-9 选手势")
                    continue
                recording = {"label": armed, "start_ts": time.time()}
                print(f"  ● 开始录制 [{armed}] —— 持续做动作…")
            else:
                end_ts = time.time()
                label = recording["label"]
                _append_segment(args.out, label, recording["start_ts"], end_ts)
                dur = end_ts - recording["start_ts"]
                counts[label] = counts.get(label, 0) + 1
                total_s[label] = total_s.get(label, 0.0) + dur
                print(f"  ■ 结束 [{label}] {dur:.1f}s"
                      f"（该手势累计 {counts[label]} 段 / {total_s[label]:.0f}s）")
                recording = None

    print("\n  各手势段数：")
    for g in CANONICAL_GESTURES:
        if counts.get(g):
            print(f"    {g:15s} {counts[g]:3d} 段 / {total_s[g]:.0f}s")
        else:
            print(f"    {g:15s}   0 段")
    missing = [g for g in CANONICAL_GESTURES if not counts.get(g)]
    if missing:
        print(f"  ⚠ 未录手势: {', '.join(missing)}")
    print(f"\n  打标文件: {args.out}")
    print("  下一步: python model/training/export_windows.py "
          f"--sessions {args.out} --source-like \"192.168.43.%\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())

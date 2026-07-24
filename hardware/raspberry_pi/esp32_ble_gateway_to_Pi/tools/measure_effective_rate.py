#!/usr/bin/env python3
"""
Measure effective micro:bit sample rate / packet arrival from gateway JSONL.

Reads esp32_gateway_receiver JSON Lines (file argument or stdin) and reports
per hand: packets received, sequence gaps, arrival %, effective Hz, RSSI.

Usage:
  # 先落盘 60 秒再统计（推荐，预览和 pi-fusion 互斥，先停 pi-fusion）
  python -m esp32_gateway_receiver.app --config config.json --log-level WARNING \
      > /tmp/mb_60s.jsonl
  python tools/measure_effective_rate.py /tmp/mb_60s.jsonl

  # 或边收边统计
  python -m esp32_gateway_receiver.app --config config.json --log-level WARNING \
      | python tools/measure_effective_rate.py

判断参考（2026-07-24 采样率对齐实验）：
  - 目标：每侧有效 >= 10 Hz（理想 20+），arrival >= 80%，RSSI 均值 > -75 dBm
  - 当前固件基线（SAMPLE_PERIOD_MS=150, REPEAT=1, TX=-12dBm）：
    名义 6.7 Hz，2026-07-23 实测抵达率 ~25% -> 有效 ~1.7 Hz
"""

import json
import sys
from collections import defaultdict

WRAP = 0x10000  # uint16 sample_sequence
GAP_SANITY = 500  # 跳号超过此值视为设备重启/乱序，不计入丢包


def new_stats():
    return {
        "received": 0,
        "gaps": 0,
        "restarts": 0,
        "last_seq": None,
        "t_first_ms": None,
        "t_last_ms": None,
        "rssi_sum": 0.0,
        "rssi_n": 0,
        "rssi_min": None,
        "rssi_max": None,
    }


def observe(line, stats):
    try:
        d = json.loads(line)
    except (json.JSONDecodeError, ValueError):
        return
    if d.get("type") != "microbit_sensor_state":
        return

    src = str(d.get("source", "?")).lower()
    s = stats[src]
    s["received"] += 1

    seq = d.get("sample_sequence")
    if isinstance(seq, int):
        if s["last_seq"] is not None:
            if seq == s["last_seq"]:
                return  # 重复包，不计时间也不计丢包
            gap = (seq - s["last_seq"] - 1) % WRAP
            if 0 < gap <= GAP_SANITY:
                s["gaps"] += gap
            else:
                s["restarts"] += 1
        s["last_seq"] = seq

    ts = d.get("device_timestamp_ms")
    if isinstance(ts, (int, float)):
        if s["t_first_ms"] is None:
            s["t_first_ms"] = ts
        s["t_last_ms"] = ts

    rssi = (d.get("gateway") or {}).get("ble_rssi")
    if isinstance(rssi, (int, float)):
        s["rssi_sum"] += rssi
        s["rssi_n"] += 1
        s["rssi_min"] = rssi if s["rssi_min"] is None else min(s["rssi_min"], rssi)
        s["rssi_max"] = rssi if s["rssi_max"] is None else max(s["rssi_max"], rssi)


def report(stats):
    if not stats:
        print("没有收到任何 microbit_sensor_state 行——检查 receiver 是否在跑、ESP32 是否已上电。")
        return 1
    print(f"{'source':<8} {'recv':>6} {'gaps':>6} {'arrival':>8} {'eff_Hz':>7} "
          f"{'RSSI avg/min/max':>20} {'restarts':>8}")
    for src in sorted(stats):
        s = stats[src]
        expected = s["received"] + s["gaps"]
        arrival = s["received"] / expected * 100 if expected else 0.0
        span_s = ((s["t_last_ms"] or 0) - (s["t_first_ms"] or 0)) / 1000.0
        eff_hz = s["received"] / span_s if span_s > 1 else float("nan")
        rssi = (f"{s['rssi_sum']/s['rssi_n']:.0f}/{s['rssi_min']}/{s['rssi_max']}"
                if s["rssi_n"] else "n/a")
        print(f"{src:<8} {s['received']:>6} {s['gaps']:>6} {arrival:>7.0f}% "
              f"{eff_hz:>7.1f} {rssi:>20} {s['restarts']:>8}")
    print("\n参考：目标 eff_Hz >= 10、arrival >= 80%、RSSI avg > -75 dBm")
    return 0


def main():
    stats = defaultdict(new_stats)
    if len(sys.argv) > 1 and sys.argv[1] not in ("-", ""):
        with open(sys.argv[1], "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                observe(line, stats)
    else:
        for line in sys.stdin:
            observe(line, stats)
    return report(stats)


if __name__ == "__main__":
    sys.exit(main())

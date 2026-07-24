#!/usr/bin/env python3
"""
Measure effective micro:bit sample rate / packet arrival from gateway JSONL.

Reads esp32_gateway_receiver JSON Lines (file argument or stdin) and reports
per hand: packets received, sequence gaps, arrival %, effective Hz, RSSI.

Usage:
  # Capture 60 s, then analyze (stop pi-fusion first; UDP 17778 is exclusive):
  python -m esp32_gateway_receiver.app --config config.json --log-level WARNING \
      > /tmp/mb_60s.jsonl
  python tools/measure_effective_rate.py /tmp/mb_60s.jsonl

  # Or pipe live:
  python -m esp32_gateway_receiver.app --config config.json --log-level WARNING \
      | python tools/measure_effective_rate.py

Reference targets for the 2026-07-24 v2 sampling-rate experiment:
  - per-hand effective rate >= 3 Hz, RSSI avg > -75 dBm, age_ms mostly < 1 s
  - current firmware baseline (SAMPLE_PERIOD_MS=150, REPEAT=1, TX=-12dBm):
    nominal 6.7 Hz, measured 2026-07-23 ~25% arrival -> ~1.7 Hz effective
"""

import json
import sys
from collections import defaultdict

WRAP = 0x10000  # uint16 sample_sequence
GAP_SANITY = 500  # larger jumps count as device restart / reorder, not loss


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

    seq = d.get("sample_sequence")
    if isinstance(seq, int):
        if seq == s["last_seq"]:
            return  # duplicate: not a new sample, ignore entirely
        if s["last_seq"] is not None:
            gap = (seq - s["last_seq"] - 1) % WRAP
            if gap == 0:
                pass  # in order
            elif gap <= GAP_SANITY:
                s["gaps"] += gap
            else:
                s["restarts"] += 1
        s["last_seq"] = seq
    s["received"] += 1

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
        print("No microbit_sensor_state lines seen -- "
              "is the receiver running and the ESP32 powered?")
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
    print("\nReference: target eff_Hz >= 3, RSSI avg > -75 dBm, age_ms mostly < 1 s")
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

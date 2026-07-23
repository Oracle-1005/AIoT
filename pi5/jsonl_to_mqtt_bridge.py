#!/usr/bin/env python3
"""
JSON Lines → MQTT Bridge — 组员 ESP32 网关链路接入我方 MQTT 架构
=================================================================
Route B (architecture decision 2026-07-23): the team member's ESP32
gateway receiver emits micro:bit samples as JSON Lines on stdout; this
bridge re-publishes them onto our MQTT topics so that every downstream
consumer (pc_inference_bridge RF inference, Flask dashboard, LED driver)
works unchanged.

Pipeline:
  Micro:bit ×2 → BLE → ESP32 gateway → UDP:17778
    → esp32_gateway_receiver (stdout, JSON Lines)
    → THIS BRIDGE (stdin → MQTT)
    → Pi 5 Mosquitto: microbit/accel/A,B + microbit/event/A,B

Input (JSON Lines, one per line):
  {"type":"microbit_sensor_state","source":"left|right","sample_sequence":N,
   "device_timestamp_ms":N,"raw":{"ax_mg":...,"ay_mg":...,"az_mg":...,
   "pitch_deg":...,"roll_deg":...}, ...}
  {"type":"microbit_control_event","source":"left|right","event_code":"...",
   "mapped_candidate":"start_or_resume|pause|style_switch|emergency_stop", ...}

Output (MQTT):
  microbit/accel/A (left hand) / microbit/accel/B (right hand):
    {"device_id":"A","acc_x":...,"acc_y":...,"acc_z":...,
     "timestamp_ms":...,"pc_timestamp":...,"acc_norm":...,
     "pitch_deg":...,"roll_deg":...,"sample_sequence":...}
    — field names/units (mg) match the USB-serial firmware format that
      the RF model was trained on; pitch/roll/sequence are extras.
  microbit/event/A,B: control event forwarded as-is plus "device_id".

Usage:
  python app.py --config cfg.json | python jsonl_to_mqtt_bridge.py
  python jsonl_to_mqtt_bridge.py --broker 192.168.43.221 --swap-hands
"""

import argparse
import json
import math
import os
import sys
import time

MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))

TOPIC_ACCEL = "microbit/accel/{device}"
TOPIC_EVENT = "microbit/event/{device}"

# Our firmware convention (hardware/microbit/ble_uart.js): A = left, B = right.
HAND_TO_DEVICE = {"left": "A", "right": "B"}

STATS_INTERVAL_S = 5.0


def build_accel_message(sample: dict, device: str, pc_timestamp: float) -> dict | None:
    """Convert one microbit_sensor_state JSON line to our MQTT accel format.

    Returns None if required fields are missing (caller skips the line).
    """
    raw = sample.get("raw")
    if not isinstance(raw, dict):
        return None
    try:
        ax = float(raw["ax_mg"])
        ay = float(raw["ay_mg"])
        az = float(raw["az_mg"])
    except (KeyError, TypeError, ValueError):
        return None

    return {
        "device_id": device,
        "acc_x": ax,
        "acc_y": ay,
        "acc_z": az,
        "timestamp_ms": sample.get("device_timestamp_ms", 0),
        "pc_timestamp": pc_timestamp,
        "acc_norm": round(math.sqrt(ax * ax + ay * ay + az * az), 2),
        # Extras for downstream consumers (fusion features, future LED hue):
        "pitch_deg": raw.get("pitch_deg"),
        "roll_deg": raw.get("roll_deg"),
        "sample_sequence": sample.get("sample_sequence"),
    }


def route_line(line: str, hand_map: dict) -> tuple | None:
    """Parse one JSON Lines entry → (topic, payload) or None to skip."""
    line = line.strip()
    if not line:
        return None
    try:
        item = json.loads(line)
    except json.JSONDecodeError:
        return None

    device = hand_map.get(str(item.get("source", "")).lower())
    if device is None:
        return None

    item_type = item.get("type")
    if item_type == "microbit_sensor_state":
        payload = build_accel_message(item, device, time.time())
        if payload is None:
            return None
        return TOPIC_ACCEL.format(device=device), payload

    if item_type == "microbit_control_event":
        payload = dict(item)
        payload["device_id"] = device
        return TOPIC_EVENT.format(device=device), payload

    return None


class MqttSink:
    """Thin paho wrapper; reconnect handled by paho's background loop."""

    def __init__(self, broker: str, port: int):
        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(client_id=f"jsonl_mqtt_bridge_{os.getpid()}")

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print(f"[bridge] MQTT connected: {broker}:{port}", file=sys.stderr)
            else:
                print(f"[bridge] MQTT connect failed rc={rc}", file=sys.stderr)

        self._client.on_connect = on_connect
        self._client.connect_async(broker, port, keepalive=60)
        self._client.loop_start()

    def publish(self, topic: str, payload: dict) -> None:
        self._client.publish(
            topic, json.dumps(payload, ensure_ascii=False, separators=(",", ":")), qos=0
        )

    def close(self) -> None:
        self._client.loop_stop()
        self._client.disconnect()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bridge ESP32 gateway JSON Lines (stdin) → MQTT accel/event topics",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker (default: localhost)")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT port (default: 1883)")
    parser.add_argument("--swap-hands", action="store_true",
                        help="swap hand mapping (left→B, right→A) if panels appear mirrored")
    args = parser.parse_args()

    hand_map = dict(HAND_TO_DEVICE)
    if args.swap_hands:
        hand_map = {"left": "B", "right": "A"}

    try:
        sink = MqttSink(args.broker, args.port)
    except ImportError:
        print("[bridge] ERROR: paho-mqtt not installed in this venv", file=sys.stderr)
        return 1

    print(f"[bridge] reading JSON Lines from stdin → {args.broker}:{args.port} "
          f"(left→{hand_map['left']}, right→{hand_map['right']})", file=sys.stderr)

    counts = {"A": 0, "B": 0, "event": 0, "skipped": 0}
    last_report = time.monotonic()

    try:
        for line in sys.stdin:
            routed = route_line(line, hand_map)
            if routed is None:
                counts["skipped"] += 1
                continue
            topic, payload = routed
            sink.publish(topic, payload)
            if "/accel/" in topic:
                counts[payload["device_id"]] += 1
            else:
                counts["event"] += 1

            now = time.monotonic()
            if now - last_report >= STATS_INTERVAL_S:
                dt = now - last_report
                print(f"[bridge] A={counts['A']/dt:.1f}/s B={counts['B']/dt:.1f}/s "
                      f"events={counts['event']} skipped={counts['skipped']}", file=sys.stderr)
                counts = {"A": 0, "B": 0, "event": 0, "skipped": 0}
                last_report = now
    except KeyboardInterrupt:
        pass
    finally:
        sink.close()

    print("[bridge] stdin closed, exiting", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

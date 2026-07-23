#!/usr/bin/env python3
"""Live verifier for Raspberry Pi -> PC backend data.

Polls the backend REST API and prints the Pi TCP gateway state, message
counter deltas, latest sensor status, and recent control events.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any


def _get_json(base_url: str, path: str, timeout_s: float) -> dict[str, Any]:
    url = urllib.parse.urljoin(base_url.rstrip("/") + "/", path.lstrip("/"))
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=timeout_s) as response:
        if response.status != 200:
            raise RuntimeError(f"{path} returned HTTP {response.status}")
        payload = json.loads(response.read().decode("utf-8"))
        if not isinstance(payload, dict):
            raise RuntimeError(f"{path} did not return a JSON object")
        return payload


def _message_counts(pi_status: dict[str, Any]) -> dict[str, int]:
    runtime = pi_status.get("runtime", {})
    if not isinstance(runtime, dict):
        return {}
    counts = runtime.get("message_counts", {})
    if not isinstance(counts, dict):
        return {}
    return {str(key): int(value) for key, value in counts.items()}


def _counter_delta(current: dict[str, int], previous: dict[str, int] | None) -> dict[str, int]:
    if previous is None:
        return {key: 0 for key in current}
    return {key: current.get(key, 0) - previous.get(key, 0) for key in current}


def _format_bool(value: Any) -> str:
    return "yes" if bool(value) else "no"


def _latest_status(pi_status: dict[str, Any]) -> dict[str, Any]:
    runtime = pi_status.get("runtime", {})
    if not isinstance(runtime, dict):
        return {}
    status = runtime.get("status", {})
    return status if isinstance(status, dict) else {}


def _latest_control_event(pi_status: dict[str, Any]) -> dict[str, Any]:
    runtime = pi_status.get("runtime", {})
    if not isinstance(runtime, dict):
        return {}
    event = runtime.get("last_control_event", {})
    return event if isinstance(event, dict) else {}


def _summarize_sensors(sensors: dict[str, Any]) -> str:
    camera = sensors.get("camera", {})
    left = sensors.get("microbit_left", {})
    right = sensors.get("microbit_right", {})
    if not isinstance(camera, dict):
        camera = {}
    if not isinstance(left, dict):
        left = {}
    if not isinstance(right, dict):
        right = {}

    return (
        f"camera_hands={camera.get('hands_detected', camera.get('hand_count', '-'))} "
        f"left_available={left.get('available', '-')} "
        f"left_seq={left.get('sample_sequence', '-')} "
        f"right_available={right.get('available', '-')} "
        f"right_seq={right.get('sample_sequence', '-')}"
    )


def _summarize_link(status: dict[str, Any]) -> str:
    camera = status.get("camera", {})
    microbits = status.get("microbits", {})
    if not isinstance(camera, dict):
        camera = {}
    if not isinstance(microbits, dict):
        microbits = {}
    left = microbits.get("left", {})
    right = microbits.get("right", {})
    if not isinstance(left, dict):
        left = {}
    if not isinstance(right, dict):
        right = {}
    return (
        f"camera_fps={camera.get('fps', camera.get('actual_fps', '-'))} "
        f"clock_ready={camera.get('clock_ready', '-')} "
        f"left_age_ms={left.get('age_ms', '-')} "
        f"left_rssi={left.get('rssi', '-')} "
        f"right_age_ms={right.get('age_ms', '-')} "
        f"right_rssi={right.get('rssi', '-')}"
    )


def _summarize_control(event_state: dict[str, Any]) -> str:
    payload = event_state.get("payload", {})
    if not isinstance(payload, dict):
        return "last_control_event=-"
    event = payload.get("event", {})
    if not isinstance(event, dict):
        return "last_control_event=-"
    received_at = event_state.get("received_at")
    age_s = "-"
    if isinstance(received_at, (int, float)):
        age_s = f"{max(0.0, time.time() - float(received_at)):.1f}s"
    return (
        f"last_control_event={event.get('type', '-')} "
        f"source={event.get('source', '-')} "
        f"code={event.get('code', '-')} "
        f"age={age_s}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify live Pi data received by the PC backend.")
    parser.add_argument("--base-url", default="http://127.0.0.1:5000", help="Backend base URL.")
    parser.add_argument("--interval", type=float, default=1.0, help="Polling interval in seconds.")
    parser.add_argument("--duration", type=float, default=30.0, help="Total verification duration in seconds.")
    parser.add_argument("--timeout", type=float, default=2.0, help="HTTP timeout in seconds.")
    parser.add_argument(
        "--require",
        action="append",
        default=["status"],
        choices=["status", "fused_frame", "control_event"],
        help="Message type that must increase during the run. Can be repeated.",
    )
    args = parser.parse_args()

    start = time.monotonic()
    previous_counts: dict[str, int] | None = None
    first_counts: dict[str, int] | None = None
    latest_counts: dict[str, int] = {}
    observed_connection = False

    print(f"Backend: {args.base_url}")
    print(f"Duration: {args.duration:.1f}s, interval: {args.interval:.1f}s")
    print("Press Ctrl+C to stop.\n")

    try:
        while time.monotonic() - start < args.duration:
            try:
                status = _get_json(args.base_url, "/api/status", args.timeout)
                pi_status = _get_json(args.base_url, "/api/pi/status", args.timeout)
                sensors = _get_json(args.base_url, "/api/sensors/live", args.timeout)
            except (urllib.error.URLError, TimeoutError, RuntimeError, json.JSONDecodeError) as exc:
                print(f"[ERROR] backend not reachable or invalid response: {exc}")
                time.sleep(args.interval)
                continue

            gateway = status.get("pi_gateway", {})
            if not isinstance(gateway, dict):
                gateway = {}

            latest_counts = _message_counts(pi_status)
            if first_counts is None:
                first_counts = dict(latest_counts)
            delta = _counter_delta(latest_counts, previous_counts)
            previous_counts = dict(latest_counts)

            connected = bool(gateway.get("connected"))
            observed_connection = observed_connection or connected

            line = (
                f"[{time.strftime('%H:%M:%S')}] "
                f"gateway_running={_format_bool(gateway.get('running'))} "
                f"pi_connected={_format_bool(connected)} "
                f"counts={latest_counts} "
                f"delta={delta}"
            )
            print(line)
            print("  " + _summarize_link(_latest_status(pi_status)))
            print("  " + _summarize_sensors(sensors))
            print("  " + _summarize_control(_latest_control_event(pi_status)))
            print()

            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\nStopped by user.")

    if first_counts is None:
        print("FAIL: backend API was never reachable.")
        return 2

    total_delta = {
        message_type: latest_counts.get(message_type, 0) - first_counts.get(message_type, 0)
        for message_type in set(first_counts) | set(latest_counts)
    }
    missing = [message_type for message_type in args.require if total_delta.get(message_type, 0) <= 0]

    print("Summary")
    print(f"  observed_connection={_format_bool(observed_connection)}")
    print(f"  first_counts={first_counts}")
    print(f"  latest_counts={latest_counts}")
    print(f"  total_delta={total_delta}")

    if missing:
        print(f"FAIL: required message types did not increase: {', '.join(missing)}")
        return 1

    print("PASS: required Pi message counters increased.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

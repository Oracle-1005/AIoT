"""Long-running acceptance test for the five-track Sonic Pi playlist.

The default schedule keeps each track for 120 seconds. At 25-second intervals
it advances the style and rotates one muted layer through melody, harmony,
bass, and drums. Every command must receive a Sonic Pi ACK.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


TRACK_ORDER = (
    "shape_of_you",
    "world_is_mine",
    "faded",
    "lemon",
    "rolling_girl",
)
LAYERS = ("melody", "harmony", "bass", "drums")


class ValidationError(RuntimeError):
    pass


def request_json(
    base_url: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: float = 5.0,
) -> dict[str, Any]:
    data = None
    headers: dict[str, str] = {}
    method = "GET"
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
        headers["Content-Type"] = "application/json"
        method = "POST"
    request = Request(
        f"{base_url.rstrip('/')}{path}",
        data=data,
        headers=headers,
        method=method,
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise ValidationError(f"{method} {path}: HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ValidationError(f"{method} {path}: {exc}") from exc
    if not isinstance(body, dict):
        raise ValidationError(f"{method} {path}: expected a JSON object")
    return body


def wait_until(
    fetch: Callable[[], dict[str, Any]],
    predicate: Callable[[dict[str, Any]], bool],
    description: str,
    *,
    timeout: float = 4.0,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout
    latest: dict[str, Any] = {}
    while time.monotonic() < deadline:
        latest = fetch()
        if predicate(latest):
            return latest
        time.sleep(0.15)
    raise ValidationError(f"timeout waiting for {description}; latest={latest}")


class Recorder:
    def __init__(self, path: Path) -> None:
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: str, **fields: Any) -> None:
        record = {
            "timestamp": datetime.now(timezone.utc).astimezone().isoformat(),
            "event": event,
            **fields,
        }
        line = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")
        print(line, flush=True)


class PlaylistValidator:
    def __init__(self, args: argparse.Namespace, recorder: Recorder) -> None:
        self.base_url = args.base_url
        self.track_seconds = args.track_seconds
        self.step_seconds = args.step_seconds
        self.cycles = args.cycles
        self.recorder = recorder
        self.baseline_timeouts = 0
        self.layers_supported = False

    def get(self, path: str) -> dict[str, Any]:
        return request_json(self.base_url, path)

    def command(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        body = request_json(
            self.base_url,
            path,
            {**payload, "wait_ms": 1800},
            timeout=5.0,
        )
        delivery = body.get("delivery")
        status = delivery.get("status") if isinstance(delivery, dict) else None
        if not body.get("sent") or status != "acked":
            raise ValidationError(
                f"command {path} {payload} was not acknowledged: {body}"
            )
        self.recorder.write(
            "command_acked",
            path=path,
            payload=payload,
            command_id=body.get("command_id"),
            delivery=delivery,
        )
        return body

    def assert_health(self, context: str) -> tuple[dict[str, Any], dict[str, Any]]:
        status = self.get("/api/sonic-pi/status")
        music = self.get("/api/music/state")
        if not status.get("command_channel_ready"):
            raise ValidationError(f"{context}: command_channel_ready=false")
        if status.get("audio_output_mode") != "internal":
            raise ValidationError(
                f"{context}: audio_output_mode must be internal, got "
                f"{status.get('audio_output_mode')!r}"
            )
        pending = int(status.get("pending_commands") or 0)
        timeouts = int(status.get("timed_out_commands") or 0)
        if pending:
            raise ValidationError(f"{context}: pending_commands={pending}")
        if timeouts > self.baseline_timeouts:
            raise ValidationError(
                f"{context}: timed_out_commands grew from "
                f"{self.baseline_timeouts} to {timeouts}"
            )
        feedback_at = music.get("last_beat_feedback_at")
        if not isinstance(feedback_at, (int, float)) or time.time() - feedback_at > 5.0:
            raise ValidationError(
                f"{context}: beat feedback is stale ({feedback_at!r})"
            )
        self.recorder.write(
            "health",
            context=context,
            track_id=music.get("track_id"),
            style=music.get("style"),
            layers=music.get("layers"),
            last_bar=music.get("last_bar"),
            last_beat=music.get("last_beat"),
            last_ack_latency_ms=status.get("last_ack_latency_ms"),
            retried_messages=status.get("retried_messages"),
            timed_out_commands=timeouts,
        )
        return status, music

    def set_layer(self, layer: str, enabled: bool) -> None:
        self.command(
            "/api/music/layers",
            {"layer": layer, "enabled": enabled},
        )
        wait_until(
            lambda: self.get("/api/music/state"),
            lambda state: bool(state.get("layers", {}).get(layer)) is enabled,
            f"{layer}={enabled}",
        )

    def next_style(self) -> None:
        before = self.get("/api/music/state").get("style")
        self.command("/api/music/style", {"style": "next"})
        wait_until(
            lambda: self.get("/api/music/state"),
            lambda state: state.get("style") != before,
            "style feedback to change",
        )

    def next_track(self, current_track: str) -> str:
        expected = TRACK_ORDER[
            (TRACK_ORDER.index(current_track) + 1) % len(TRACK_ORDER)
        ]
        self.command("/api/sonic-pi/transport", {"action": "next"})
        wait_until(
            lambda: self.get("/api/music/state"),
            lambda state: state.get("track_id") == expected,
            f"track {expected}",
        )
        return expected

    def restore_layers(self) -> None:
        for layer in LAYERS:
            try:
                state = self.get("/api/music/state")
                if not bool(state.get("layers", {}).get(layer)):
                    self.set_layer(layer, True)
            except ValidationError as exc:
                self.recorder.write(
                    "restore_failed",
                    layer=layer,
                    error=str(exc),
                )

    def sleep_until(self, deadline: float) -> None:
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return
            time.sleep(min(remaining, 0.5))

    def run(self) -> None:
        status = self.get("/api/sonic-pi/status")
        required_status_fields = {
            "command_channel_ready",
            "audio_output_mode",
            "pending_commands",
            "timed_out_commands",
        }
        missing_status_fields = sorted(required_status_fields - status.keys())
        if missing_status_fields:
            raise ValidationError(
                "PC backend API is outdated or the wrong process owns port 5000; "
                f"missing status fields: {missing_status_fields}. Stop every "
                "listener on port 5000, then start backend/app.py with "
                "backend\\.venv\\Scripts\\python.exe"
            )

        music = self.get("/api/music/state")
        required_music_fields = {"track_id", "track_count", "layers"}
        missing_music_fields = sorted(required_music_fields - music.keys())
        if missing_music_fields or int(music.get("track_count") or 0) != len(TRACK_ORDER):
            raise ValidationError(
                "PC backend music API is not the five-track version; "
                f"missing fields: {missing_music_fields}, "
                f"track_count={music.get('track_count')!r}"
            )
        self.layers_supported = True

        self.baseline_timeouts = int(status.get("timed_out_commands") or 0)
        if not status.get("command_channel_ready"):
            raise ValidationError(
                "Sonic Pi command channel is not ready; run aiot_loader.rb once"
            )
        if status.get("audio_output_mode") != "internal":
            raise ValidationError(
                "Sonic Pi did not report internal audio output"
            )

        self.command("/api/sonic-pi/transport", {"action": "start"})
        _, music = self.assert_health("startup")
        current_track = str(music.get("track_id"))
        if current_track not in TRACK_ORDER:
            raise ValidationError(f"unexpected track_id={current_track!r}")
        self.restore_layers()

        for cycle in range(1, self.cycles + 1):
            for track_number in range(1, len(TRACK_ORDER) + 1):
                started = time.monotonic()
                self.recorder.write(
                    "track_begin",
                    cycle=cycle,
                    track_number=track_number,
                    track_id=current_track,
                )
                muted_layer: str | None = None
                for step, layer in enumerate(LAYERS, start=1):
                    self.sleep_until(started + self.step_seconds * step)
                    self.next_style()
                    if muted_layer is not None:
                        self.set_layer(muted_layer, True)
                    self.set_layer(layer, False)
                    muted_layer = layer
                    self.assert_health(
                        f"cycle={cycle} track={current_track} step={step}"
                    )

                self.sleep_until(started + self.track_seconds)
                if muted_layer is not None:
                    self.set_layer(muted_layer, True)
                current_track = self.next_track(current_track)
                self.assert_health(
                    f"cycle={cycle} switched_to={current_track}"
                )

        self.recorder.write("validation_passed", cycles=self.cycles)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate the Sonic Pi five-track playlist through the PC backend."
    )
    parser.add_argument("--base-url", default="http://127.0.0.1:5000")
    parser.add_argument("--cycles", type=int, default=1)
    parser.add_argument("--track-seconds", type=float, default=120.0)
    parser.add_argument("--step-seconds", type=float, default=25.0)
    parser.add_argument(
        "--log",
        type=Path,
        default=Path(__file__).resolve().parents[1]
        / "music"
        / "sonic_pi"
        / "validation_logs"
        / f"playlist_{datetime.now():%Y%m%d_%H%M%S}.jsonl",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the default schedule without contacting the backend.",
    )
    args = parser.parse_args()
    if args.cycles < 1:
        parser.error("--cycles must be at least 1")
    if args.step_seconds <= 0:
        parser.error("--step-seconds must be positive")
    if args.track_seconds < args.step_seconds * len(LAYERS):
        parser.error("--track-seconds must cover four layer/style steps")
    return args


def print_schedule(args: argparse.Namespace) -> None:
    print(f"cycles={args.cycles}")
    for cycle in range(1, args.cycles + 1):
        for track in TRACK_ORDER:
            print(f"cycle {cycle}: {track}, switch after {args.track_seconds:g}s")
            for step, layer in enumerate(LAYERS, start=1):
                print(
                    f"  +{args.step_seconds * step:g}s: style next; "
                    f"restore previous layer; disable {layer}"
                )


def main() -> int:
    args = parse_args()
    if args.dry_run:
        print_schedule(args)
        return 0

    recorder = Recorder(args.log.resolve())
    validator = PlaylistValidator(args, recorder)
    recorder.write(
        "validation_started",
        base_url=args.base_url,
        cycles=args.cycles,
        track_seconds=args.track_seconds,
        step_seconds=args.step_seconds,
        log=str(recorder.path.resolve()),
    )
    try:
        validator.run()
    except (ValidationError, KeyboardInterrupt) as exc:
        recorder.write("validation_failed", error=str(exc))
        if validator.layers_supported:
            validator.restore_layers()
        print(
            "\nFAILED. Keep the Sonic Pi GUI log visible and inspect the last "
            f"JSONL event: {recorder.path.resolve()}",
            file=sys.stderr,
        )
        return 1

    print(
        "\nPASSED backend/OSC checks. Confirm that the Sonic Pi GUI contains "
        "no Runtime Error or Serious timing error."
    )
    print(f"Log: {recorder.path.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

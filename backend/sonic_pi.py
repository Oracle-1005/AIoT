"""OSC adapter between the backend music state and Sonic Pi."""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from state import live_state

try:
    from pythonosc import dispatcher, osc_server, udp_client
except ImportError:  # pragma: no cover - exercised when dependency is absent
    dispatcher = None
    osc_server = None
    udp_client = None


SONIC_PI_ENABLED = os.getenv("AIOT_SONIC_PI_ENABLED", "1").lower() in {
    "1",
    "true",
    "yes",
    "on",
}
SONIC_PI_SEND_HOST = os.getenv("AIOT_SONIC_PI_SEND_HOST", "127.0.0.1")
SONIC_PI_SEND_PORT = int(os.getenv("AIOT_SONIC_PI_SEND_PORT", "4560"))
SONIC_PI_LISTEN_HOST = os.getenv("AIOT_SONIC_PI_LISTEN_HOST", "127.0.0.1")
SONIC_PI_LISTEN_PORT = int(os.getenv("AIOT_SONIC_PI_LISTEN_PORT", "4561"))


ACCENT_GESTURES = {
    "downbeat",
    "left_wrist_strike",
    "right_wrist_strike",
    "bilateral_strike",
}
START_GESTURES = {
    "downbeat",
    "left_wrist_strike",
    "right_wrist_strike",
    "bilateral_strike",
    "gesture_start",
    "resume",
}
STOP_GESTURES = {
    "cutoff",
    "gesture_end",
    "stop",
}


class SonicPiOscAdapter:
    """Optional Sonic Pi OSC sender/listener.

    UDP sends do not prove Sonic Pi is online. The adapter reports Sonic Pi as
    connected only after a `/music/*` feedback message is received.
    """

    def __init__(self) -> None:
        self.enabled = SONIC_PI_ENABLED
        self.send_host = SONIC_PI_SEND_HOST
        self.send_port = SONIC_PI_SEND_PORT
        self.listen_host = SONIC_PI_LISTEN_HOST
        self.listen_port = SONIC_PI_LISTEN_PORT

        self._client: Any | None = None
        self._server: Any | None = None
        self._thread: threading.Thread | None = None
        self._lock = threading.RLock()
        self._last_error: str | None = None
        self._last_sent_command: dict[str, Any] | None = None
        self._last_feedback_at: float | None = None
        self._attempted_messages = 0
        self._sent_messages = 0
        self._received_messages = 0

    @property
    def available(self) -> bool:
        return dispatcher is not None and osc_server is not None and udp_client is not None

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> bool:
        if not self.enabled or self.running:
            return False

        if not self.available:
            self._set_error("python-osc is not installed")
            return False

        osc_dispatcher = dispatcher.Dispatcher()
        osc_dispatcher.map("/music/beat", self._handle_beat)
        osc_dispatcher.map("/music/bar", self._handle_bar)
        osc_dispatcher.map("/music/state", self._handle_state)
        osc_dispatcher.map("/music/ack", self._handle_ack)
        osc_dispatcher.map("/music/error", self._handle_error)
        osc_dispatcher.map("/music/pong", self._handle_pong)

        try:
            server = osc_server.ThreadingOSCUDPServer(
                (self.listen_host, self.listen_port),
                osc_dispatcher,
            )
        except OSError as exc:
            self._set_error(f"OSC listener startup failed: {exc}")
            return False

        self._client = udp_client.SimpleUDPClient(self.send_host, self.send_port)
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="sonic-pi-osc",
            daemon=True,
        )
        self._thread.start()
        self._set_error(None)
        print(
            "[SonicPi] OSC adapter listening on "
            f"{self.listen_host}:{self.listen_port}, sending to "
            f"{self.send_host}:{self.send_port}"
        )
        return True

    def stop(self) -> None:
        server = self._server
        self._server = None

        if server is not None:
            server.shutdown()
            server.server_close()

        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)

    def status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            connected = (
                self._last_feedback_at is not None
                and now - self._last_feedback_at <= 5
            )
            return {
                "enabled": self.enabled,
                "available": self.available,
                "running": self.running,
                "connected": connected,
                "send_host": self.send_host,
                "send_port": self.send_port,
                "listen_host": self.listen_host,
                "listen_port": self.listen_port,
                "attempted_messages": self._attempted_messages,
                "sent_messages": self._sent_messages,
                "received_messages": self._received_messages,
                "last_sent_command": _copy_command(self._last_sent_command),
                "last_feedback_at": self._last_feedback_at,
                "last_error": self._last_error,
            }

    def publish_control_event(
        self,
        payload: dict[str, Any],
        music_state: dict[str, Any],
    ) -> None:
        event = payload.get("event", {})
        music_control = payload.get("music_control", {})
        if not isinstance(event, dict):
            event = {}
        if not isinstance(music_control, dict):
            music_control = {}

        gesture = str(event.get("type", "")).strip()
        strength = _clamp(
            _as_float(
                event.get("strength"),
                _as_float(event.get("confidence"), 0.8),
            ),
            0.0,
            1.2,
        )

        if gesture in START_GESTURES:
            self.send_transport("start")
        elif gesture in STOP_GESTURES:
            self.send_transport("cutoff")

        state_sent = False
        if music_control or gesture in {"crescendo", "decrescendo", "style_switch"}:
            state_sent = self.send_state_from_music(music_state, music_control)

        if gesture in {"tempo_up", "tempo_down"} and not state_sent:
            self.send_bpm(_as_float(music_state.get("bpm"), 108.0))

        if gesture in ACCENT_GESTURES:
            self.send_accent(strength, gesture)

    def publish_prediction(
        self,
        prediction: dict[str, Any],
        music_state: dict[str, Any],
    ) -> None:
        gesture = str(prediction.get("gesture", "")).strip()
        if not gesture:
            return

        payload = {
            "event": {
                "type": gesture,
                "confidence": prediction.get("confidence", 0.8),
                "strength": prediction.get("confidence", 0.8),
            },
            "music_control": {
                "estimated_bpm": music_state.get("bpm"),
                "volume": music_state.get("volume"),
                "intensity": music_state.get("energy", 0.62),
            },
        }
        self.publish_control_event(payload, music_state)

    def send_transport(
        self,
        action: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        return self._send(
            "/conductor/transport",
            command_id or _command_id(),
            str(action),
        )

    def send_bpm(
        self,
        bpm: float,
        *,
        command_id: str | None = None,
    ) -> bool:
        return self._send(
            "/conductor/bpm",
            command_id or _command_id(),
            _clamp(_as_float(bpm, 108.0), 72.0, 148.0),
        )

    def send_accent(
        self,
        strength: float,
        accent_type: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        return self._send(
            "/conductor/accent",
            command_id or _command_id(),
            _clamp(_as_float(strength, 0.8), 0.0, 1.2),
            str(accent_type),
        )

    def send_state_from_music(
        self,
        music_state: dict[str, Any],
        overrides: dict[str, Any] | None = None,
        *,
        command_id: str | None = None,
    ) -> bool:
        overrides = overrides or {}
        bpm = _as_float(
            overrides.get(
                "bpm",
                overrides.get("target_bpm", overrides.get("estimated_bpm")),
            ),
            _as_float(music_state.get("bpm"), 108.0),
        )
        volume = _clamp(
            _as_float(overrides.get("volume"), _as_float(music_state.get("volume"), 0.8)),
            0.0,
            1.0,
        )
        energy = _clamp(
            _as_float(
                overrides.get("energy", overrides.get("intensity")),
                _as_float(music_state.get("energy"), 0.62),
            ),
            0.0,
            1.0,
        )
        articulation = _clamp(
            _as_float(overrides.get("articulation"), energy),
            0.0,
            1.0,
        )

        return self._send(
            "/conductor/state",
            command_id or _command_id(),
            _clamp(bpm, 72.0, 148.0),
            _clamp(volume * 1.15, 0.0, 1.3),
            _clamp(0.35 + energy * 0.75, 0.0, 1.3),
            articulation,
            _clamp(0.25 + energy * 0.65, 0.0, 1.2),
            _clamp(0.25 + volume * 0.65, 0.0, 1.2),
            _clamp(0.45 + volume * 0.85, 0.0, 1.3),
            energy,
            _clamp(0.15 + energy * 0.35, 0.0, 0.9),
            _clamp(75.0 + energy * 45.0, 55.0, 130.0),
        )

    def _send(self, path: str, *args: Any) -> bool:
        sent_at = time.time()
        command = {
            "path": path,
            "args": list(args),
            "sent_at": sent_at,
            "ok": False,
        }

        with self._lock:
            self._attempted_messages += 1
            self._last_sent_command = command

        if not self.enabled:
            self._set_error("Sonic Pi OSC adapter is disabled")
            return False

        if not self.available:
            self._set_error("python-osc is not installed")
            return False

        if self._client is None:
            self._client = udp_client.SimpleUDPClient(self.send_host, self.send_port)

        try:
            self._client.send_message(path, list(args))
        except OSError as exc:
            self._set_error(f"OSC send failed: {exc}")
            return False

        with self._lock:
            self._sent_messages += 1
            command["ok"] = True
            self._last_sent_command = command
            self._last_error = None
        return True

    def _handle_beat(
        self,
        _address: str,
        bar: Any,
        beat: Any,
        bpm: Any,
        beat_strength: Any,
    ) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_beat(
            bar=bar,
            beat=beat,
            bpm=bpm,
            beat_strength=beat_strength,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_bar(self, _address: str, bar: Any, section: Any) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_bar(
            bar=bar,
            section=section,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_state(
        self,
        _address: str,
        playing: Any,
        bpm: Any,
        section: Any,
        energy: Any,
    ) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_state(
            playing=playing,
            bpm=bpm,
            section=section,
            energy=energy,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_ack(self, _address: str, command_id: Any, result: Any) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_ack(
            command_id=command_id,
            result=result,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_error(self, _address: str, code: Any, message: Any) -> None:
        received_at = time.time()
        self._set_error(f"Sonic Pi error {code}: {message}")
        live_state.apply_sonic_pi_error(
            code=code,
            message=message,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_pong(self, _address: str, *_args: Any) -> None:
        self._record_feedback(time.time())

    def _record_feedback(self, received_at: float) -> None:
        with self._lock:
            self._received_messages += 1
            self._last_feedback_at = received_at

    def _set_error(self, message: str | None) -> None:
        with self._lock:
            self._last_error = message


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _command_id() -> str:
    return f"sp-{uuid.uuid4().hex[:10]}"


def _copy_command(command: dict[str, Any] | None) -> dict[str, Any] | None:
    if command is None:
        return None
    return {
        "path": command["path"],
        "args": list(command["args"]),
        "sent_at": command["sent_at"],
        "ok": command["ok"],
    }


sonic_pi_adapter = SonicPiOscAdapter()

"""OSC adapter between the backend music state and Sonic Pi."""

from __future__ import annotations

import os
import threading
import time
import uuid
from typing import Any

from pi_gateway import pi_gateway
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
SONIC_PI_ACK_TIMEOUT = max(
    0.5,
    float(os.getenv("AIOT_SONIC_PI_ACK_TIMEOUT", "1.5")),
)
SONIC_PI_PING_INTERVAL = max(
    0.5,
    float(os.getenv("AIOT_SONIC_PI_PING_INTERVAL", "2.0")),
)
SONIC_PI_RETRY_DELAYS = (0.12, 0.30, 0.65)

# Forward Sonic Pi beat/state feedback to the Pi LED chain (music-reactive
# panel). pi_gateway.send returns False when the Pi is offline — harmless.
MUSIC_LED_ENABLED = os.getenv("AIOT_MUSIC_LED_ENABLED", "1").lower() in {
    "1",
    "true",
    "yes",
    "on",
}


ACCENT_GESTURES = {
    "downbeat",
    "upbeat",
    "left_cue",
    "right_cue",
    "left_wrist_strike",
    "right_wrist_strike",
    "bilateral_strike",
}
START_GESTURES = {
    "downbeat",
    "upbeat",
    "left_cue",
    "right_cue",
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

GESTURE_BPM_STEP = float(os.getenv("AIOT_GESTURE_BPM_STEP", "4"))
GESTURE_VOLUME_STEP = float(os.getenv("AIOT_GESTURE_VOLUME_STEP", "0.06"))

MUSIC_COMMAND_ALIASES = {
    "play": "start",
    "start": "start",
    "resume": "start",
    "gesture_start": "start",
    "downbeat": "start",
    "upbeat": "start",
    "left_cue": "start",
    "right_cue": "start",
    "left_wrist_strike": "start",
    "right_wrist_strike": "start",
    "bilateral_strike": "start",
    "pause": "stop",
    "stop": "stop",
    "cutoff": "stop",
    "gesture_end": "stop",
    "bpm_up": "bpm_up",
    "tempo_up": "bpm_up",
    "speed_up": "bpm_up",
    "bpm_down": "bpm_down",
    "tempo_down": "bpm_down",
    "speed_down": "bpm_down",
    "vol_up": "vol_up",
    "volume_up": "vol_up",
    "crescendo": "vol_up",
    "vol_down": "vol_down",
    "volume_down": "vol_down",
    "decrescendo": "vol_down",
    "style": "style",
    "style_switch": "style",
    "style_next": "style",
    "style_prev": "style",
    "style_previous": "style",
    "zone_on": "zone_on",
    "layer_on": "zone_on",
    "zone_off": "zone_off",
    "layer_off": "zone_off",
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
        self._retry_thread: threading.Thread | None = None
        self._retry_stop = threading.Event()
        self._lock = threading.RLock()
        self._last_error: str | None = None
        self._last_sent_command: dict[str, Any] | None = None
        self._last_feedback_at: float | None = None
        self._last_ack_at: float | None = None
        self._last_ack_latency_ms: float | None = None
        self._last_pong_at: float | None = None
        self._last_ping_at: float | None = None
        self._last_ping_latency_ms: float | None = None
        self._audio_output_mode: str | None = None
        self._next_ping_at = 0.0
        self._pending_commands: dict[str, dict[str, Any]] = {}
        self._command_outcomes: dict[str, dict[str, Any]] = {}
        self._attempted_messages = 0
        self._sent_messages = 0
        self._received_messages = 0
        self._retried_messages = 0
        self._acked_commands = 0
        self._timed_out_commands = 0
        self._superseded_commands = 0

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
        osc_dispatcher.map("/music/track", self._handle_track)
        osc_dispatcher.map("/music/state", self._handle_state)
        osc_dispatcher.map("/music/layers", self._handle_layers)
        osc_dispatcher.map("/music/style", self._handle_style)
        osc_dispatcher.map("/music/ack", self._handle_ack)
        osc_dispatcher.map("/music/error", self._handle_error)
        osc_dispatcher.map("/music/pong", self._handle_pong)
        osc_dispatcher.map("/music/output", self._handle_output)

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
        self._retry_stop.clear()
        self._next_ping_at = time.time() + 0.2
        self._thread = threading.Thread(
            target=server.serve_forever,
            name="sonic-pi-osc",
            daemon=True,
        )
        self._thread.start()
        self._retry_thread = threading.Thread(
            target=self._retry_loop,
            name="sonic-pi-osc-retry",
            daemon=True,
        )
        self._retry_thread.start()
        self._set_error(None)
        print(
            "[SonicPi] OSC adapter listening on "
            f"{self.listen_host}:{self.listen_port}, sending to "
            f"{self.send_host}:{self.send_port}"
        )
        return True

    def stop(self) -> None:
        self._retry_stop.set()
        server = self._server
        self._server = None

        if server is not None:
            server.shutdown()
            server.server_close()

        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)
        retry_thread = self._retry_thread
        if (
            retry_thread
            and retry_thread.is_alive()
            and retry_thread is not threading.current_thread()
        ):
            retry_thread.join(timeout=2)
        self._thread = None
        self._retry_thread = None

    def _command_channel_ready_locked(self, now: float | None = None) -> bool:
        current = time.time() if now is None else float(now)
        window = max(5.0, SONIC_PI_PING_INTERVAL * 2.5)
        return (
            (self._last_pong_at is not None and current - self._last_pong_at <= window)
            or (self._last_ack_at is not None and current - self._last_ack_at <= window)
        )

    def command_channel_ready(self) -> bool:
        with self._lock:
            return self._command_channel_ready_locked(time.time())
    def status(self) -> dict[str, Any]:
        with self._lock:
            now = time.time()
            connected = (
                self._last_feedback_at is not None
                and now - self._last_feedback_at <= 5
            )
            command_channel_ready = self._command_channel_ready_locked(now)
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
                "retried_messages": self._retried_messages,
                "acked_commands": self._acked_commands,
                "timed_out_commands": self._timed_out_commands,
                "superseded_commands": self._superseded_commands,
                "pending_commands": len(self._pending_commands),
                "command_channel_ready": command_channel_ready,
                "last_ack_at": self._last_ack_at,
                "last_ack_latency_ms": self._last_ack_latency_ms,
                "last_pong_at": self._last_pong_at,
                "last_ping_latency_ms": self._last_ping_latency_ms,
                "audio_output_mode": self._audio_output_mode,
                "last_sent_command": _copy_command(self._last_sent_command),
                "last_feedback_at": self._last_feedback_at,
                "last_error": self._last_error,
            }

    def new_command_id(self) -> str:
        return _command_id()

    def command_status(self, command_id: str) -> dict[str, Any]:
        command_text = str(command_id).strip()
        with self._lock:
            pending = self._pending_commands.get(command_text)
            if pending is not None:
                return _copy_delivery(pending, "pending")
            outcome = self._command_outcomes.get(command_text)
            if outcome is not None:
                return dict(outcome)
        return {
            "command_id": command_text,
            "status": "unknown",
        }

    def wait_for_command(
        self,
        command_id: str,
        timeout: float,
    ) -> dict[str, Any]:
        command_text = str(command_id).strip()
        with self._lock:
            pending = self._pending_commands.get(command_text)
            event = pending.get("event") if pending is not None else None
        if event is not None:
            event.wait(max(0.0, float(timeout)))
        return self.command_status(command_text)

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

        command_detail = dict(event)
        command_detail.update(music_control)
        state_already_applied = bool(music_control) or gesture in {
            "gesture_start",
            "resume",
            "stop",
            "cutoff",
            "gesture_end",
            "style_switch",
        } | ACCENT_GESTURES
        command_sent = self.send_gesture_command(
            gesture,
            command_detail,
            music_state=music_state,
            update_live_state=not state_already_applied,
        )

        state_sent = False
        if music_control and gesture in ACCENT_GESTURES:
            state_sent = self.send_state_from_music(music_state, music_control)
        elif not command_sent and (music_control or gesture in {"crescendo", "decrescendo"}):
            state_sent = self.send_state_from_music(music_state, music_control)

        if gesture in {"tempo_up", "tempo_down"} and not command_sent and not state_sent:
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

        detail = {
            "confidence": prediction.get("confidence", 0.8),
            "strength": prediction.get("confidence", 0.8),
        }
        self.send_gesture_command(
            gesture,
            detail,
            music_state=music_state,
            update_live_state=False,
        )
        if gesture in ACCENT_GESTURES:
            self.send_accent(_as_float(detail.get("strength"), 0.8), gesture)

    def send_gesture_command(
        self,
        name: str,
        detail: dict[str, Any] | None = None,
        *,
        music_state: dict[str, Any] | None = None,
        update_live_state: bool = True,
    ) -> bool:
        """Map a recognized gesture/action name to one concrete Sonic Pi command."""
        detail = detail if isinstance(detail, dict) else {}
        command = _canonical_music_command(name)
        if not command:
            return False

        state = music_state if isinstance(music_state, dict) else live_state.get_music()
        now = time.time()
        state_updates_enabled = bool(update_live_state and self.command_channel_ready())
        if update_live_state and not state_updates_enabled:
            self._set_error(
                "Sonic Pi command channel is not ready; enable incoming OSC and rerun the current loader"
            )
        gesture_name = str(name).strip() or command

        if command == "start":
            sent = self.send_transport("start")
            if sent and state_updates_enabled:
                live_state.apply_sonic_pi_transport_intent("start", now)
                live_state.set_music_current_gesture(gesture_name)
            return sent

        if command == "stop":
            sent = self.send_transport("stop")
            if sent and state_updates_enabled:
                live_state.apply_sonic_pi_transport_intent("stop", now)
                live_state.set_music_current_gesture(gesture_name)
            return sent

        if command in {"bpm_up", "bpm_down"}:
            direction = 1.0 if command == "bpm_up" else -1.0
            base_bpm = _as_float(detail.get("bpm"), _as_float(state.get("bpm"), 96.0))
            target = _clamp(
                base_bpm + (GESTURE_BPM_STEP * direction if update_live_state else 0.0),
                72.0,
                148.0,
            )
            sent = self.send_bpm(target)
            if sent and state_updates_enabled:
                live_state.set_music_bpm(target)
                live_state.set_music_current_gesture(gesture_name)
            return sent

        if command in {"vol_up", "vol_down"}:
            direction = 1.0 if command == "vol_up" else -1.0
            base_volume = _as_float(detail.get("volume"), _as_float(state.get("volume"), 0.8))
            target = _clamp(
                base_volume + (GESTURE_VOLUME_STEP * direction if update_live_state else 0.0),
                0.0,
                1.0,
            )
            sent = self.send_volume(target)
            if sent and state_updates_enabled:
                live_state.set_music_volume(target)
                live_state.set_music_current_gesture(gesture_name)
            return sent

        if command == "style":
            direction = str(
                detail.get(
                    "direction",
                    "previous" if str(name).strip().lower() in {"style_prev", "style_previous"} else "next",
                )
            )
            sent = self.send_style(direction)
            if sent and state_updates_enabled:
                live_state.apply_music_style_intent(direction, gesture=gesture_name)
            return sent

        if command in {"zone_on", "zone_off"}:
            layer = str(detail.get("layer", "")).strip()
            enabled = command == "zone_on"
            if "enabled" in detail:
                enabled = bool(detail.get("enabled"))
            if not layer:
                return False
            sent = self.send_layer(layer, enabled)
            if sent and state_updates_enabled:
                live_state.set_music_layer(layer, enabled)
                live_state.set_music_current_gesture(gesture_name)
            return sent

        return False

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

    def send_layer(
        self,
        layer: str,
        enabled: bool,
        *,
        command_id: str | None = None,
    ) -> bool:
        """声部硬切：rb 侧立即翻转播放门（melody/harmony/bass/drums）。"""
        return self._send(
            "/conductor/layer",
            command_id or _command_id(),
            str(layer),
            1.0 if enabled else 0.0,
        )

    def send_volume(
        self,
        volume: float,
        *,
        command_id: str | None = None,
    ) -> bool:
        """主音量直控：/conductor/volume（rb 有独立 receiver，不走 state 重算）。"""
        return self._send(
            "/conductor/volume",
            command_id or _command_id(),
            _clamp(_as_float(volume, 0.8), 0.0, 1.0),
        )

    def send_style(
        self,
        style: str,
        *,
        command_id: str | None = None,
    ) -> bool:
        """切换当前曲目的风格；支持 next/previous 或该曲目的明确预设名。"""
        return self._send(
            "/conductor/style",
            command_id or _command_id(),
            str(style),
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

        style = str(overrides.get("style", music_state.get("style", "piano")))

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
            # 第 12 个参数（追加，向后兼容：旧版 rb 并行赋值会丢弃多余实参）
            style,
        )

    def _send(self, path: str, *args: Any) -> bool:
        sent_at = time.time()
        command_id = str(args[0]) if args else ""
        command = {
            "command_id": command_id,
            "path": path,
            "args": list(args),
            "sent_at": sent_at,
            "ok": False,
            "attempts": 0,
            "retry_index": 0,
            "next_retry_at": sent_at + SONIC_PI_RETRY_DELAYS[0],
            "deadline": sent_at + SONIC_PI_ACK_TIMEOUT,
            "event": threading.Event(),
        }

        with self._lock:
            self._attempted_messages += 1
            existing = self._pending_commands.get(command_id)
            if existing is None:
                existing = self._command_outcomes.get(command_id)
            if existing is not None:
                same_command = (
                    existing.get("path") == path
                    and list(existing.get("args", [])) == list(args)
                )
                if same_command:
                    return True
                self._last_error = (
                    f"command_id collision for {command_id}: "
                    f"{existing.get('path')} != {path}"
                )
                return False
            self._last_sent_command = command

        if not self.enabled:
            self._set_error("Sonic Pi OSC adapter is disabled")
            return False

        if not self.available:
            self._set_error("python-osc is not installed")
            return False

        if self._client is None:
            self._client = udp_client.SimpleUDPClient(self.send_host, self.send_port)

        reliable = path != "/conductor/accent" and bool(command_id)
        if reliable:
            with self._lock:
                self._supersede_coalesced_locked(command)
                self._pending_commands[command_id] = command
                # Keep coalescing and the corresponding UDP send ordered.
                # Otherwise an older state retry can race past a newer value.
                sent = self._send_datagram(command, is_retry=False)
        else:
            sent = self._send_datagram(command, is_retry=False)
        if not sent and reliable:
            with self._lock:
                pending = self._pending_commands.pop(command_id, None)
                if pending is not None:
                    self._finish_delivery_locked(
                        pending,
                        status="send_failed",
                        result=self._last_error,
                    )
        return sent

    def _send_datagram(
        self,
        command: dict[str, Any],
        *,
        is_retry: bool,
    ) -> bool:
        client = self._client
        if client is None:
            return False
        try:
            client.send_message(command["path"], list(command["args"]))
        except OSError as exc:
            self._set_error(f"OSC send failed: {exc}")
            return False

        sent_at = time.time()
        with self._lock:
            self._sent_messages += 1
            if is_retry:
                self._retried_messages += 1
            command["ok"] = True
            command["attempts"] = int(command.get("attempts", 0)) + 1
            command["last_sent_at"] = sent_at
            if not is_retry:
                self._last_sent_command = command
            self._last_error = None
        return True

    def _retry_loop(self) -> None:
        while not self._retry_stop.wait(0.025):
            now = time.time()
            self._retry_pending(now)
            self._maybe_send_ping(now)

    def _retry_pending(self, now: float | None = None) -> None:
        current = time.time() if now is None else float(now)
        due: list[dict[str, Any]] = []
        with self._lock:
            for command_id, pending in list(self._pending_commands.items()):
                if current >= float(pending["deadline"]):
                    self._pending_commands.pop(command_id, None)
                    self._timed_out_commands += 1
                    self._finish_delivery_locked(
                        pending,
                        status="timed_out",
                        result=None,
                        completed_at=current,
                    )
                    continue
                if current < float(pending["next_retry_at"]):
                    continue

                retry_index = int(pending["retry_index"])
                if retry_index >= len(SONIC_PI_RETRY_DELAYS):
                    pending["next_retry_at"] = pending["deadline"]
                    continue

                pending["retry_index"] = retry_index + 1
                next_index = retry_index + 1
                pending["next_retry_at"] = (
                    current + SONIC_PI_RETRY_DELAYS[next_index]
                    if next_index < len(SONIC_PI_RETRY_DELAYS)
                    else pending["deadline"]
                )
                due.append(pending)

        for pending in due:
            with self._lock:
                command_id = str(pending["command_id"])
                if self._pending_commands.get(command_id) is not pending:
                    continue
                self._send_datagram(pending, is_retry=True)

    def _maybe_send_ping(self, now: float) -> None:
        with self._lock:
            if now < self._next_ping_at:
                return
            self._next_ping_at = now + SONIC_PI_PING_INTERVAL
            command_id = f"ping-{uuid.uuid4().hex[:8]}"
            self._last_ping_at = now
            self._last_ping_id = command_id
            client = self._client
        if client is None:
            return
        try:
            client.send_message("/conductor/ping", [command_id])
        except OSError as exc:
            self._set_error(f"OSC ping failed: {exc}")

    def _supersede_coalesced_locked(self, command: dict[str, Any]) -> None:
        key = _coalesce_key(command["path"], command["args"])
        if key is None:
            return
        for command_id, pending in list(self._pending_commands.items()):
            if _coalesce_key(pending["path"], pending["args"]) != key:
                continue
            self._pending_commands.pop(command_id, None)
            self._superseded_commands += 1
            self._finish_delivery_locked(
                pending,
                status="superseded",
                result=None,
            )

    def _acknowledge_command(
        self,
        command_id: Any,
        result: Any,
        received_at: float,
    ) -> bool:
        command_text = str(command_id)
        with self._lock:
            pending = self._pending_commands.pop(command_text, None)
            if pending is None:
                return False
            self._acked_commands += 1
            self._last_ack_at = received_at
            self._last_ack_latency_ms = round(
                max(0.0, received_at - float(pending["sent_at"])) * 1000.0,
                1,
            )
            self._finish_delivery_locked(
                pending,
                status="acked",
                result=str(result),
                completed_at=received_at,
            )
            return True

    def _finish_delivery_locked(
        self,
        command: dict[str, Any],
        *,
        status: str,
        result: Any,
        completed_at: float | None = None,
    ) -> None:
        finished_at = time.time() if completed_at is None else completed_at
        outcome = _copy_delivery(command, status)
        outcome["result"] = result
        outcome["completed_at"] = finished_at
        outcome["latency_ms"] = round(
            max(0.0, finished_at - float(command["sent_at"])) * 1000.0,
            1,
        )
        if status == "timed_out":
            self._last_error = (
                f"Sonic Pi command timed out on {command['path']}; "
                "enable incoming OSC in Sonic Pi and run the current loader"
            )
        self._command_outcomes[str(command["command_id"])] = outcome
        while len(self._command_outcomes) > 128:
            self._command_outcomes.pop(next(iter(self._command_outcomes)))
        event = command.get("event")
        if event is not None:
            event.set()

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
        self._forward_music_led("music_beat", {
            "bar": _as_float(bar),
            "beat": _as_float(beat),
            "bpm": _as_float(bpm),
            "beat_strength": _as_float(beat_strength, 1.0),
        })

    def _handle_bar(self, _address: str, bar: Any, section: Any) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_bar(
            bar=bar,
            section=section,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_track(
        self,
        _address: str,
        piece_id: Any,
        title: Any,
        key: Any,
        total_bars: Any,
        beats_per_bar: Any,
        default_bpm: Any,
    ) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_track(
            piece_id=piece_id,
            title=title,
            key=key,
            total_bars=total_bars,
            beats_per_bar=beats_per_bar,
            default_bpm=default_bpm,
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
        self._forward_music_led("music_state", {
            "playing": _truthy(playing),
            "bpm": _as_float(bpm),
            "section": str(section),
            "energy": _as_float(energy),
        })

    def _forward_music_led(self, message_type: str, payload: dict[str, Any]) -> None:
        """Forward one music feedback message to the Pi LED chain.

        Best-effort: a disconnected Pi (send → False) is silent; unexpected
        errors are logged at most once a minute so a ~4 msg/s stream can
        never flood the log.
        """
        if not MUSIC_LED_ENABLED:
            return
        try:
            pi_gateway.send({"message_type": message_type, "payload": payload})
        except Exception as exc:  # pragma: no cover - defensive
            now = time.time()
            if now - getattr(self, "_music_led_error_at", 0.0) > 60.0:
                self._music_led_error_at = now
                self._set_error(f"music LED forward failed: {exc}")

    def _handle_layers(
        self,
        _address: str,
        melody: Any,
        harmony: Any,
        bass: Any,
        drums: Any,
    ) -> None:
        received_at = time.time()
        live_state.apply_sonic_pi_layers(
            melody=melody,
            harmony=harmony,
            bass=bass,
            drums=drums,
            received_at=received_at,
        )
        self._record_feedback(received_at)

    def _handle_style(self, _address: str, _track: Any, style: Any) -> None:
        """接收当前曲目的风格反馈：/music/style track_id style。"""
        received_at = time.time()
        live_state.apply_sonic_pi_style(style, received_at)
        self._record_feedback(received_at)

    def _handle_ack(self, _address: str, command_id: Any, result: Any) -> None:
        received_at = time.time()
        if self._acknowledge_command(command_id, result, received_at):
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

    def _handle_pong(self, _address: str, command_id: Any = "", *_args: Any) -> None:
        received_at = time.time()
        with self._lock:
            # Any pong proves the 4560 command channel is alive. A pong that
            # arrives after the next ping went out (slow/loaded Tau) no longer
            # matches the latest ping id; dropping it made command_channel_ready
            # flap even though the channel was fine.
            self._last_pong_at = received_at
            if (
                str(command_id) == str(getattr(self, "_last_ping_id", ""))
                and self._last_ping_at is not None
            ):
                self._last_ping_latency_ms = round(
                    max(0.0, received_at - self._last_ping_at) * 1000.0,
                    1,
                )
        self._record_feedback(received_at)

    def _handle_output(self, _address: str, output_mode: Any = "") -> None:
        received_at = time.time()
        with self._lock:
            self._audio_output_mode = str(output_mode)
        self._record_feedback(received_at)

    def _record_feedback(self, received_at: float) -> None:
        with self._lock:
            self._received_messages += 1
            self._last_feedback_at = received_at

    def _set_error(self, message: str | None) -> None:
        with self._lock:
            self._last_error = message


def _canonical_music_command(name: Any) -> str | None:
    text = str(name).strip().lower()
    if not text:
        return None
    return MUSIC_COMMAND_ALIASES.get(text)

def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _truthy(value: Any) -> bool:
    """Mirror of state._truthy for the LED-forward playing flag."""
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value != 0
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on", "playing", "play"}
    return bool(value)


def _clamp(value: float, low: float, high: float) -> float:
    return min(high, max(low, float(value)))


def _command_id() -> str:
    return f"sp-{uuid.uuid4().hex[:10]}"


def _coalesce_key(path: str, args: list[Any]) -> str | None:
    if path in {"/conductor/state", "/conductor/bpm", "/conductor/volume"}:
        return path
    if path == "/conductor/layer" and len(args) >= 2:
        return f"{path}:{args[1]}"
    return None


def _copy_delivery(
    command: dict[str, Any],
    status: str,
) -> dict[str, Any]:
    return {
        "command_id": str(command.get("command_id", "")),
        "path": str(command["path"]),
        "args": list(command["args"]),
        "sent_at": float(command["sent_at"]),
        "last_sent_at": command.get("last_sent_at"),
        "attempts": int(command.get("attempts", 0)),
        "status": status,
    }


def _copy_command(command: dict[str, Any] | None) -> dict[str, Any] | None:
    if command is None:
        return None
    return {
        "path": command["path"],
        "args": list(command["args"]),
        "sent_at": command["sent_at"],
        "ok": command["ok"],
        "command_id": command.get("command_id"),
        "attempts": command.get("attempts", 0),
    }


sonic_pi_adapter = SonicPiOscAdapter()

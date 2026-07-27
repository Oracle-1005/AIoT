"""LED downlink consumer — drives the WS2812B panels from PC backend commands.

Consumes the frozen `led_command` schema (backend/docs/INTERFACE_CONTRACT.md
§8.1), received over the TCP downlink (see tcp_client.py):

    {"message_type": "led_command",
     "payload": {"effect": "downbeat", "brightness": 0.9,
                 "duration_ms": 120, "source": "backend"}}

Semantics:
  - `effect`: canonical backend event type (§8.2, e.g. `gesture_start`,
    `decrescendo`, `left_cue`). RF labels and LedController aliases
    (Chinese labels, `strong_beat`, `diminuendo`, ...) are also accepted.
  - `brightness`: animation intensity [0, 1] (clamped).
  - `duration_ms`: > 0 reverts to `default_pattern` after the interval;
    0 holds the pattern until the next command. One-shot animations
    (start/stop) complete on their own regardless.

Safety: the consumer must never break the fusion pipeline. If no LED
backend is available (non-Pi host, /dev/leds0 missing or not writable),
commands are logged and dropped while the rest of the pipeline runs on.

All methods are called from the fusion event loop thread; no locking.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable

logger = logging.getLogger(__name__)

try:
    from raspberry_pi_iot.led.controller import (
        GESTURE_PATTERN_MAP,
        PATTERNS,
        LedController,
    )
except ImportError:  # hardware/ not on sys.path (offline tooling/tests)
    LedController = None  # type: ignore[assignment]
    GESTURE_PATTERN_MAP: dict = {}
    PATTERNS: frozenset = frozenset()

# Canonical backend event types (INTERFACE_CONTRACT §8.2) → LedController
# base pattern. RF labels and English aliases are resolved separately via
# GESTURE_PATTERN_MAP; raw pattern names pass through unchanged.
EFFECT_TO_PATTERN = {
    "idle": "breathing",
    "gesture_start": "start",
    "stop": "stop",
    "downbeat": "downbeat",
    "upbeat": "upbeat",
    "crescendo": "crescendo",
    "decrescendo": "diminuendo",
    "left_cue": "left",
    "right_cue": "right",
    "strong_beat": "downbeat",
    "weak_beat": "upbeat",
    # Operational aliases (not gestures): force the panels dark. The canonical
    # "idle" event stays mapped to breathing per the LedController design.
    "off": "idle",
    "clear": "idle",
    "lights_off": "idle",
}

# Downlink types we explicitly do not handle yet (logged at debug level).
_UNHANDLED_TYPES = {"led_state", "led_config", "system_command", "time_sync"}


def _as_bool(value) -> bool:
    """Coerce playing flags that may arrive as bool/int/str."""
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on", "playing"}
    return bool(value)


class LedConsumer:
    """Consumes led_command downlink messages and drives a LedController.

    Args:
        enabled: When False, no controller is created and all commands are
            dropped silently (config gate).
        default_pattern: Pattern to revert to after a timed command, and the
            pattern used at startup (must be in PATTERNS).
        brightness_limit: Passed through to LedController (safety cap 0-1).
        music_panel: Music mode — both panels form one 16x32 vertically
            stacked music canvas (passed through to LedController).
        music_stack_top_panel: Which physical panel is the top half of the
            16-row canvas (0 or 1; passed through to LedController).
        controller: Pre-built controller for tests; bypasses auto-construction.
        clock: Monotonic clock, injectable for tests.
    """

    def __init__(
        self,
        *,
        enabled: bool = True,
        default_pattern: str = "breathing",
        brightness_limit: float = 0.25,
        music_panel: bool = False,
        music_stack_top_panel: int = 0,
        controller=None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._default_pattern = (
            default_pattern if default_pattern in PATTERNS else "breathing"
        )
        self._music_panel = bool(music_panel)
        self._music_stack_top_panel = int(music_stack_top_panel)
        self._clock = clock
        self._revert_at: float | None = None

        # Observability counters
        self.commands_applied = 0
        self.commands_rejected = 0
        self.commands_dropped_offline = 0
        self.music_messages_applied = 0
        self.music_messages_rejected = 0

        self._controller = controller
        if not enabled:
            logger.info("LED consumer disabled by config.")
            return
        if self._controller is None:
            if LedController is None:
                logger.warning(
                    "LED consumer: LedController unavailable (import failed) "
                    "— led_commands will be dropped."
                )
                return
            try:
                self._controller = LedController(
                    brightness_limit=brightness_limit,
                    music_panel_enabled=self._music_panel,
                    music_stack_top_panel=self._music_stack_top_panel,
                )
            except Exception:
                logger.exception("LED consumer: LedController init failed — commands will be dropped.")
                self._controller = None
                return
        status = self._controller.get_status()
        if status.get("connected"):
            logger.info(
                "LED consumer ready: backend=%s, %d LEDs, default_pattern=%s",
                status.get("backend"), status.get("total_leds"), self._default_pattern,
            )
            self._controller.set_pattern(self._default_pattern)
        else:
            logger.warning(
                "LED consumer: no LED backend (%s) — led_commands will be dropped.",
                status.get("error") or "not connected",
            )

    # ── Downlink entry point ──────────────────────────────────────────

    def handle_message(self, message: dict) -> None:
        """TcpJsonlClient downlink callback. Routes led_command payloads."""
        if not isinstance(message, dict):
            return
        msg_type = message.get("message_type")
        if msg_type == "led_command":
            self.apply_command(message.get("payload"))
        elif msg_type == "music_beat":
            self.apply_music_beat(message.get("payload"))
        elif msg_type == "music_state":
            self.apply_music_state(message.get("payload"))
        elif msg_type in _UNHANDLED_TYPES:
            logger.debug("Downlink %r ignored (not implemented).", msg_type)
        else:
            logger.warning("Unknown downlink message_type %r — ignored.", msg_type)

    # ── Command handling ──────────────────────────────────────────────

    def apply_command(self, payload) -> None:
        """Validate and apply one led_command payload (frozen schema §8.1)."""
        if not isinstance(payload, dict):
            self._reject("payload is not an object: %r", payload)
            return
        try:
            effect = payload["effect"]
            brightness = float(payload["brightness"])
            duration_ms = int(payload["duration_ms"])
        except (KeyError, TypeError, ValueError) as exc:
            self._reject("schema violation (%s): %r", exc, payload)
            return
        if not isinstance(effect, str) or not effect.strip():
            self._reject("effect must be a non-empty string: %r", payload)
            return
        brightness = max(0.0, min(1.0, brightness))
        if duration_ms < 0:
            self._reject("duration_ms must be >= 0: %r", payload)
            return

        pattern = self._resolve_pattern(effect)
        if pattern is None:
            self._reject("unknown effect %r", effect)
            return

        if not self._hardware_ready():
            self.commands_dropped_offline += 1
            if self.commands_dropped_offline % 100 == 1:
                logger.warning(
                    "led_command %r dropped — no LED backend (%d dropped so far).",
                    effect, self.commands_dropped_offline,
                )
            return

        self._controller.set_state(intensity=brightness)
        if not self._controller.set_pattern(pattern):
            self._reject("pattern %r refused by controller", pattern)
            return
        self._revert_at = (
            self._clock() + duration_ms / 1000.0 if duration_ms > 0 else None
        )
        self.commands_applied += 1
        logger.info(
            "led_command applied: effect=%r → pattern=%s, brightness=%.2f, duration_ms=%d",
            effect, pattern, brightness, duration_ms,
        )

    # ── Music visualiser messages (~4 msg/s — logged at debug) ────────

    def apply_music_beat(self, payload) -> None:
        """Validate and apply one music_beat payload (spectrum kick)."""
        if not isinstance(payload, dict):
            self._reject_music("music_beat payload is not an object: %r", payload)
            return
        try:
            strength = float(payload.get("beat_strength", 1.0))
        except (TypeError, ValueError):
            self._reject_music("music_beat bad beat_strength: %r", payload)
            return
        bpm = payload.get("bpm")
        try:
            bpm = float(bpm) if bpm is not None else None
        except (TypeError, ValueError):
            bpm = None

        if not self._hardware_ready():
            self.commands_dropped_offline += 1
            return
        self._controller.music_kick(strength, bpm=bpm)
        self.music_messages_applied += 1
        logger.debug("music_beat applied: strength=%.2f bpm=%s", strength, bpm)

    def apply_music_state(self, payload) -> None:
        """Validate and apply one music_state payload (playing/bpm/energy)."""
        if not isinstance(payload, dict):
            self._reject_music("music_state payload is not an object: %r", payload)
            return
        try:
            energy = float(payload.get("energy", 0.0))
        except (TypeError, ValueError):
            self._reject_music("music_state bad energy: %r", payload)
            return
        playing = _as_bool(payload.get("playing", False))
        bpm = payload.get("bpm")
        try:
            bpm = float(bpm) if bpm is not None else None
        except (TypeError, ValueError):
            bpm = None
        section = payload.get("section")

        if not self._hardware_ready():
            self.commands_dropped_offline += 1
            return
        self._controller.set_music_state(
            playing=playing, bpm=bpm, energy=energy, section=section,
        )
        self.music_messages_applied += 1
        logger.debug(
            "music_state applied: playing=%s bpm=%s energy=%.2f section=%r",
            playing, bpm, energy, section,
        )

    # ── Periodic update (called from the fusion main loop) ────────────

    def update(self) -> None:
        """Handle timed revert and render one animation frame."""
        if self._controller is None:
            return
        if self._revert_at is not None and self._clock() >= self._revert_at:
            self._revert_at = None
            logger.info("led_command duration elapsed → revert to %s", self._default_pattern)
            self._controller.set_pattern(self._default_pattern)
        self._controller.update()

    def close(self) -> None:
        """Turn all LEDs off (shutdown)."""
        if self._controller is not None:
            try:
                self._controller.clear()
            except Exception:
                logger.exception("LED clear failed on shutdown.")

    # ── Status ────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        """Status snapshot for logging / future status-message inclusion."""
        status = {
            "controller_present": self._controller is not None,
            "default_pattern": self._default_pattern,
            "music_panel": self._music_panel,
            "commands_applied": self.commands_applied,
            "commands_rejected": self.commands_rejected,
            "commands_dropped_offline": self.commands_dropped_offline,
            "music_messages_applied": self.music_messages_applied,
            "music_messages_rejected": self.music_messages_rejected,
        }
        if self._controller is not None:
            status["controller"] = self._controller.get_status()
        return status

    # ── Internal ──────────────────────────────────────────────────────

    def _resolve_pattern(self, effect: str) -> str | None:
        """Map an effect name to a LedController base pattern.

        Accepts canonical backend event types (§8.2), raw pattern names,
        RF labels (Chinese), and English aliases (GESTURE_PATTERN_MAP).
        """
        key = effect.strip().lower()
        pattern = EFFECT_TO_PATTERN.get(key)
        if pattern is not None:
            return pattern
        if effect in GESTURE_PATTERN_MAP:  # Chinese labels, exact case
            return GESTURE_PATTERN_MAP[effect]
        pattern = GESTURE_PATTERN_MAP.get(key)
        if pattern is not None:
            return pattern
        if key in PATTERNS:
            return key
        return None

    def _reject(self, fmt: str, *args) -> None:
        self.commands_rejected += 1
        logger.warning("led_command rejected: " + fmt, *args)

    def _reject_music(self, fmt: str, *args) -> None:
        self.music_messages_rejected += 1
        logger.warning("music message rejected: " + fmt, *args)

    def _hardware_ready(self) -> bool:
        """Controller exists AND has a live LED backend (e.g. /dev/leds0).

        A constructed-but-disconnected controller (no permission, wrong
        host) must not pretend to apply commands.
        """
        if self._controller is None:
            return False
        try:
            return bool(self._controller.get_status().get("connected"))
        except Exception:
            return False

"""WS2812B LED controller — dual backend.

Controls two 8x32 WS2812B panels directly from a Raspberry Pi.
Backend is auto-detected at init:
- Pi 5: kernel ws2812-pio driver via /dev/leds0 (preferred; rpi_ws281x
  cannot drive the RP1 PWM). Enable with:
  dtoverlay=ws2812-pio,gpio=19,num_leds=512,brightness=0
- Pi 3/4: rpi_ws281x userspace library on a PWM GPIO (default 19).

LED control is entirely local — no serial protocol or network dependency.

Panel layout:
- Panel 0 (LEDs 0-255) and Panel 1 (LEDs 256-511) are each an
  8(row) x 32(col) matrix, physically 32 columns (left→right) x 8 rows
  (top→bottom). Wiring is COLUMN-major serpentine: each physical column
  is 8 consecutive LEDs; even columns run top→bottom, odd columns
  bottom→top. (Verified on hardware 2026-07-26 with a raw-index block
  sweep — the earlier row-major assumption was wrong and scrambled all
  2D effects.)
- Music mode (music_panel_enabled): both panels stack VERTICALLY into a
  16-row x 32-col canvas (2026-07-27 user-specified; not 8x64 horizontal).
  music_stack_top_panel selects the top-half physical panel.

Base patterns (set_pattern): breathing / wave / idle — continuous,
parameterised by set_state(). A beat pulse (show_beat) temporarily
overrides the base pattern.

Gesture patterns (show_gesture): the RF model's 9 conducting gestures
map onto base patterns —
- 静止/Idle        → breathing (blue pulse)
- 开始/Start       → green wipe from center outward (one-shot, holds)
- 停止/Stop        → red flash → exponential fade to black (one-shot)
- 强拍/Downbeat    → white flash travelling top → bottom (0.8s cycle)
- 弱拍/Upbeat      → soft gold ripple bottom → top (1.2s cycle)
- 渐强/Crescendo   → 蓝紫色流星雨左下→右上，3s 渐亮
- 渐弱/Diminuendo  → 金黄色流星雨左下→右上，3s 渐暗
- 左手提示/Left     → left panel blue flash, right dim
- 右手提示/Right    → right panel blue flash, left dim
"""

import logging
import math
import os
import time

logger = logging.getLogger(__name__)

# Pi 5 kernel driver device (ws2812-pio overlay). If present it is used
# instead of rpi_ws281x, which does not support the Pi 5's RP1 PWM.
_LEDS0_PATH = "/dev/leds0"


class _Leds0Strip:
    """PixelStrip-compatible adapter for the Pi 5 ws2812-pio kernel driver.

    The driver exposes /dev/leds0 with 4 bytes per pixel in memory order
    R, G, B, W (W unused for WS2812B). A full-buffer write refreshes the
    whole strip; writing a single byte at offset 0 sets driver-side
    brightness (left unused — this class does all scaling in software,
    so the overlay should be loaded with brightness=0 / pass-through).

    Writes must use pwrite() at offset 0: the device does not support
    lseek (ESPIPE), and plain write() advances the file position so the
    second frame would hit the end of the driver's pixel buffer (ENOSPC).
    pwrite() leaves the position untouched — every call replaces the
    whole frame. A 1-byte pwrite at offset 0 sets driver-side brightness
    (left unused — this class does all scaling in software, so the
    overlay should be loaded with brightness=0 / pass-through).

    Colors accepted by setPixelColor use the rpi_ws281x packing 0xRRGGBB.
    """

    def __init__(self, path: str, num_leds: int):
        # O_BINARY avoids Windows text-mode translation (harmless on Linux)
        self._fd = os.open(path, os.O_WRONLY | getattr(os, "O_BINARY", 0))
        self._buf = bytearray(num_leds * 4)

    def setPixelColor(self, i: int, color: int) -> None:
        o = i * 4
        self._buf[o] = (color >> 16) & 0xFF      # R
        self._buf[o + 1] = (color >> 8) & 0xFF   # G
        self._buf[o + 2] = color & 0xFF          # B
        # byte o+3 (white) stays 0

    def _write_at_zero(self, data: bytes) -> None:
        if hasattr(os, "pwrite"):
            os.pwrite(self._fd, data, 0)
        else:  # fallback for non-POSIX (offline testing only)
            os.lseek(self._fd, 0, os.SEEK_SET)
            os.write(self._fd, data)

    def show(self) -> None:
        """Push the whole frame; the driver DMAs it out to the strip."""
        self._write_at_zero(self._buf)

    def setBrightness(self, brightness: int) -> None:
        """Driver-side global brightness (1-byte write at offset 0)."""
        self._write_at_zero(bytes([max(0, min(255, int(brightness)))]))


# Gesture name → base pattern. Chinese labels come from the RF model's
# `model/gesture` messages; English aliases are accepted for testing.
GESTURE_PATTERN_MAP = {
    "静止": "breathing",
    "idle": "breathing",
    "开始": "start",
    "start": "start",
    "停止": "stop",
    "stop": "stop",
    "强拍": "downbeat",
    "downbeat": "downbeat",
    "弱拍": "upbeat",
    "upbeat": "upbeat",
    "渐强": "crescendo",
    "crescendo": "crescendo",
    "渐弱": "diminuendo",
    "diminuendo": "diminuendo",
    "左手提示": "left",
    "left": "left",
    "右手提示": "right",
    "right": "right",
}

# All valid base pattern names accepted by set_pattern().
PATTERNS = frozenset({
    "breathing", "wave", "idle",
    "start", "stop", "downbeat", "upbeat",
    "crescendo", "diminuendo", "left", "right",
})


class LedController:
    """Controls two WS2812B 8x32 LED panels via a PWM GPIO pin.

    Each panel has 256 LEDs (8x32), totaling 512 LEDs. Panels are mapped:
    - Panel 0 (LEDs 0-255): left hand
    - Panel 1 (LEDs 256-511): right hand

    Args:
        gpio: GPIO pin for data output (default 19, physical pin 35, PWM1;
            GPIO18/PWM0 also works — both are equivalent with respect to
            onboard audio since Pi 5 has no analog audio jack).
        panel_count: Number of WS2812B panels (default 2).
        led_per_panel: Number of LEDs per panel (256 for 8x32).
        brightness_limit: Maximum brightness 0-1 (default 0.25 for safety).
        rows: Matrix rows per panel (default 8). rows*cols must equal
            led_per_panel for the 2D gesture animations to map correctly.
        cols: Matrix columns per panel (default 32).
        music_panel_enabled: Music mode — BOTH panels become one music
            spectrum visualiser stacked vertically into a 16-row x 32-col
            canvas (driven by set_music_state/music_kick). Gesture
            patterns get an empty canvas in this mode (gesture feedback
            moved to the frontend, 2026-07-26 22:05 decision). Default
            False keeps the legacy mirrored behaviour.
        music_stack_top_panel: Which physical panel is the TOP half of the
            16-row canvas (default 0; the other panel is rows 8-15).
    """

    LED_FREQ_HZ = 800000
    LED_DMA = 10
    LED_INVERT = False

    def __init__(
        self,
        gpio: int = 19,
        panel_count: int = 2,
        led_per_panel: int = 256,
        brightness_limit: float = 0.25,
        rows: int = 8,
        cols: int = 32,
        music_panel_enabled: bool = False,
        music_stack_top_panel: int = 0,
    ):
        self._gpio = gpio
        self._panel_count = panel_count
        self._led_per_panel = led_per_panel
        self._rows = rows
        self._cols = cols
        self._total_leds = panel_count * led_per_panel
        self._brightness_limit = brightness_limit
        self._brightness = 0.0

        # State
        self._current_pattern = "breathing"
        self._pattern_start = time.monotonic()
        self._last_beat_time = 0.0
        self._beat_strength = 0.0
        self._beat_duration_ms = 120
        self._beat_hand = "none"
        # Rest tempo: 0 = no music yet → breathing falls back to a slow ~4 s
        # cycle. A performing tempo (e.g. 120) would make "breathing" a 2 Hz
        # blink. set_state(bpm=...) overrides once music is playing.
        self._bpm = 0.0
        self._intensity = 0.5
        self._left_weight = 0.5
        self._right_weight = 0.5
        self._connected = False
        self._error = None
        self._backend = "none"
        self._consecutive_errors = 0

        # Music mode (2026-07-26 22:05 决策 + 07-27 用户指定拼接方向):
        # 双灯板全部给音乐波形，手势响应移出灯板改前端呈现。两板竖拼成
        # 16 行×32 列画布（非横拼 8×64）：music_stack_top_panel 指定上半
        # 屏物理板号（默认 0，rows 0-7），另一板为下半屏（rows 8-15）。
        # 频谱柱从画布底行（row 15）向上生长，重拍闪画布底行。
        self._music_panel_enabled = bool(music_panel_enabled)
        self._music_stack_top_panel = int(music_stack_top_panel)
        self._music = {"playing": False, "bpm": 0.0, "energy": 0.0, "section": ""}
        self._kick_at = 0.0
        self._kick_strength = 0.0
        self._kick_is_downbeat = False
        # Spectrum column state (float heights in canvas rows) persists
        # across frames for attack/decay motion; everything else stateless.
        self._spec_heights = [0.0] * cols
        self._spec_last_t: float | None = None
        self._music_energy_smooth = 0.0

        try:
            if os.path.exists(_LEDS0_PATH):
                # Pi 5: kernel ws2812-pio driver (rpi_ws281x can't drive RP1 PWM)
                self._strip = _Leds0Strip(_LEDS0_PATH, self._total_leds)
                self._connected = True
                self._backend = "ws2812-pio"
                logger.info(
                    "LED controller: %s, %d LEDs via kernel ws2812-pio driver, "
                    "brightness_limit=%.0f%%",
                    _LEDS0_PATH, self._total_leds, brightness_limit * 100,
                )
                return
        except Exception as e:
            self._error = f"ws2812-pio open failed: {e}"
            logger.error("LED init failed: %s", self._error)
            return

        try:
            from rpi_ws281x import PixelStrip, Color

            brightness_byte = int(brightness_limit * 255)
            self._strip = PixelStrip(
                self._total_leds,
                gpio,
                self.LED_FREQ_HZ,
                self.LED_DMA,
                self.LED_INVERT,
                brightness_byte,
            )
            self._strip.begin()
            self._connected = True
            self._backend = "rpi_ws281x"
            self._Color = Color
            logger.info(
                "LED controller initialized: %d LEDs on GPIO%d, brightness_limit=%.0f%%",
                self._total_leds,
                gpio,
                brightness_limit * 100,
            )
        except ImportError:
            self._error = "rpi_ws281x not installed"
            logger.warning("LED: %s. LED control disabled.", self._error)
        except Exception as e:
            self._error = str(e)
            logger.error("LED init failed: %s", e)

    # ---- Public API ----

    def show_beat(self, hand: str = "right", strength: float = 0.5, duration_ms: int = 120) -> None:
        """Trigger a beat pulse animation on the specified panel.

        Args:
            hand: "left", "right", or "both".
            strength: Pulse intensity [0, 1].
            duration_ms: How long the pulse lasts.
        """
        self._last_beat_time = time.monotonic()
        self._beat_strength = max(0.0, min(1.0, strength))
        self._beat_duration_ms = duration_ms
        self._beat_hand = hand

    def set_state(
        self,
        bpm: float | None = None,
        intensity: float | None = None,
        left_weight: float | None = None,
        right_weight: float | None = None,
    ) -> None:
        """Update continuous LED state parameters.

        Args:
            bpm: Current estimated BPM.
            intensity: Overall motion intensity [0, 1].
            left_weight: Left hand contribution weight [0, 1].
            right_weight: Right hand contribution weight [0, 1].
        """
        if bpm is not None:
            self._bpm = bpm
        if intensity is not None:
            self._intensity = max(0.0, min(1.0, intensity))
        if left_weight is not None:
            self._left_weight = max(0.0, min(1.0, left_weight))
        if right_weight is not None:
            self._right_weight = max(0.0, min(1.0, right_weight))

    def set_music_state(
        self,
        playing: bool | None = None,
        bpm: float | None = None,
        energy: float | None = None,
        section: str | None = None,
    ) -> None:
        """Update the music visualiser state (last panel, split mode only).

        Args:
            playing: Music is playing; False ramps the spectrum to black.
            bpm: Current tempo (informational; reserved for future styles).
            energy: Music energy [0, 1] — drives column height and hue.
            section: Piece section label (informational).
        """
        if playing is not None:
            self._music["playing"] = bool(playing)
        if bpm is not None:
            self._music["bpm"] = max(0.0, float(bpm))
        if energy is not None:
            self._music["energy"] = max(0.0, min(1.0, float(energy)))
        if section is not None:
            self._music["section"] = str(section)

    def music_kick(self, strength: float = 1.0, bpm: float | None = None) -> None:
        """Beat kick for the music visualiser — boosts spectrum columns.

        Stacks with the decaying remnant of the previous kick by max().
        strength >= 0.9 marks a downbeat (bottom-row white flash).
        """
        strength = max(0.0, min(1.0, float(strength)))
        now = time.monotonic()
        remnant = self._kick_strength * math.exp(-(now - self._kick_at) * self._SPEC_KICK_DECAY)
        self._kick_strength = max(strength, remnant)
        self._kick_at = now
        self._kick_is_downbeat = strength >= 0.9
        if bpm is not None:
            self._music["bpm"] = max(0.0, float(bpm))

    def set_pattern(self, pattern: str) -> bool:
        """Switch the base animation pattern.

        Resets the pattern clock, so one-shot animations (start/stop)
        replay from the beginning. Returns False for unknown names.
        """
        if pattern not in PATTERNS:
            logger.warning("LED: unknown pattern %r", pattern)
            return False
        if pattern != self._current_pattern:
            logger.info("LED pattern: %s → %s", self._current_pattern, pattern)
            self._current_pattern = pattern
            self._pattern_start = time.monotonic()
            # 立即清掉手势区残影：灯带是持久帧缓冲，上一图案最后
            # 一帧不会自动熄灭。只写缓冲不调 show()（show 可能从
            # MQTT 回调线程与渲染循环竞争），下一帧 ≤20ms 内自然覆盖。
            if self._connected and hasattr(self, "_strip"):
                for i in range(self._gesture_span()):
                    self._strip.setPixelColor(i, 0)
        return True

    def show_gesture(self, gesture: str, confidence: float = 1.0) -> bool:
        """Map a recognized gesture (Chinese label or English) to a pattern.

        This is the entry point for gesture sources (RF inference via
        MQTT, or direct calls). Unknown gestures are ignored so the
        current animation keeps running.

        Args:
            gesture: Gesture label, e.g. "强拍" or "downbeat".
            confidence: Classifier confidence [0, 1] (logging only).

        Returns:
            True if the gesture was recognized and applied.
        """
        if not gesture:
            return False
        pattern = GESTURE_PATTERN_MAP.get(gesture)
        if pattern is None:
            pattern = GESTURE_PATTERN_MAP.get(gesture.strip().lower())
        if pattern is None:
            logger.warning("LED: unknown gesture %r (conf=%.2f)", gesture, confidence)
            return False
        return self.set_pattern(pattern)

    def clear(self) -> None:
        """Turn off all LEDs."""
        if self._connected and hasattr(self, '_strip'):
            for i in range(self._total_leds):
                self._strip.setPixelColor(i, 0)
            self._strip.show()

    def update(self) -> None:
        """Compute and display the current animation frame.

        Called at the configured refresh rate (typically 50Hz) by the
        main event loop. Consecutive failures are rate-limited in the log
        and eventually flip the controller to disconnected, so a mid-run
        device failure (overlay unload, EIO on /dev/leds0) neither floods
        the journal at 50Hz nor keeps reporting a healthy connected state.
        """
        if not self._connected:
            return

        try:
            self._update_animation()
            self._consecutive_errors = 0
        except Exception as e:
            self._consecutive_errors += 1
            # Log the first few, then once every ~5s at 50Hz
            if self._consecutive_errors <= 3 or self._consecutive_errors % 250 == 0:
                logger.error(
                    "LED update error (#%d consecutive): %s",
                    self._consecutive_errors, e,
                    exc_info=self._consecutive_errors <= 3,
                )
            if self._consecutive_errors >= 250:
                self._connected = False
                self._error = f"update failed {self._consecutive_errors}x: {e}"
                logger.error("LED: too many consecutive failures — marking disconnected.")

    def get_status(self) -> dict:
        """Return LED status for the status message."""
        return {
            "connected": self._connected,
            "backend": self._backend,
            "gpio": self._gpio,
            "panel_count": self._panel_count,
            "total_leds": self._total_leds,
            "brightness_limit": self._brightness_limit,
            "actual_brightness": round(self._brightness, 3),
            "current_pattern": self._current_pattern,
            "music_panel_enabled": self._music_panel_enabled,
            "music_stack_top_panel": self._music_stack_top_panel,
            "music": dict(self._music),
            "fps": 50,
            "error": self._error,
        }

    # ---- Internal: 2D matrix helpers ----

    def _gesture_panels(self) -> list[int]:
        """Panels available to gesture patterns.

        Music mode: none — the visualiser owns both panels and rewrites
        them every frame; gesture renderers get an empty canvas (their
        output is overwritten anyway).
        """
        if self._music_panel_enabled and self._panel_count > 1:
            return []
        return list(range(self._panel_count))

    def _gesture_span(self) -> int:
        """Number of strip LEDs covered by gesture panels."""
        return len(self._gesture_panels()) * self._led_per_panel

    def _pixel_index(self, panel: int, row: int, col: int) -> int:
        """Map (panel, row, col) to strip index with serpentine correction.

        Hardware is column-major serpentine: each physical column is 8
        consecutive LEDs, even columns run top→bottom, odd columns
        bottom→top. row 0 = top, col 0 = left.
        """
        if col % 2 == 1:
            row = (self._rows - 1) - row
        return panel * self._led_per_panel + col * self._rows + row

    def _set_xy(self, panel: int, row: int, col: int, color) -> None:
        """Set one matrix pixel; out-of-range coordinates are ignored."""
        if 0 <= panel < self._panel_count and 0 <= row < self._rows and 0 <= col < self._cols:
            self._strip.setPixelColor(self._pixel_index(panel, row, col), color)

    def _fill_panel(self, panel: int, color) -> None:
        """Fill one panel with a single color."""
        start = panel * self._led_per_panel
        for i in range(start, start + self._led_per_panel):
            self._strip.setPixelColor(i, color)

    def _fill_all(self, color) -> None:
        """Fill all panels with a single color."""
        for i in range(self._total_leds):
            self._strip.setPixelColor(i, color)

    def _color(self, r: float, g: float, b: float, scale: float = 1.0):
        """Build a strip color with brightness-limit safety scaling.

        r/g/b are given at full brightness (0-255); scale (0-1) is the
        per-pixel animation factor. Output is capped by brightness_limit,
        matching the convention of the base animations.
        """
        k = max(0.0, min(1.0, scale)) * self._brightness_limit
        ri, gi, bi = int(r * k), int(g * k), int(b * k)
        if hasattr(self, '_Color'):
            return self._Color(ri, gi, bi)
        return (ri << 16) | (gi << 8) | bi

    @staticmethod
    def _hash01(x: float) -> float:
        """Deterministic pseudo-random in [0, 1) — stateless, no RNG."""
        v = math.sin(x) * 43758.5453
        return v - math.floor(v)

    @staticmethod
    def _hsv_to_rgb(h: float, s: float, v: float) -> tuple:
        """HSV (h: 0-360, s/v: 0-1) → (r, g, b) floats 0-255."""
        h = h % 360
        c = v * s
        x = c * (1 - abs((h / 60) % 2 - 1))
        m = v - c
        if h < 60:
            r, g, b = c, x, 0
        elif h < 120:
            r, g, b = x, c, 0
        elif h < 180:
            r, g, b = 0, c, x
        elif h < 240:
            r, g, b = 0, x, c
        elif h < 300:
            r, g, b = x, 0, c
        else:
            r, g, b = c, 0, x
        return (r + m) * 255, (g + m) * 255, (b + m) * 255

    # ---- Internal: Animation ----

    def _update_animation(self) -> None:
        """Generate the current frame of the active animation pattern."""
        now = time.monotonic()

        # Check if a beat pulse is active
        beat_elapsed_ms = (now - self._last_beat_time) * 1000.0
        beat_active = beat_elapsed_ms < self._beat_duration_ms

        if beat_active:
            self._render_beat_pulse(beat_elapsed_ms)
        else:
            elapsed = now - self._pattern_start
            pattern = self._current_pattern
            if pattern == "breathing":
                self._render_breathing(now)
            elif pattern == "wave":
                self._render_wave(now)
            elif pattern == "start":
                self._render_start(elapsed)
            elif pattern == "stop":
                self._render_stop(elapsed)
            elif pattern == "downbeat":
                self._render_downbeat(elapsed)
            elif pattern == "upbeat":
                self._render_upbeat(elapsed)
            elif pattern == "crescendo":
                self._render_crescendo(elapsed)
            elif pattern == "diminuendo":
                self._render_diminuendo(elapsed)
            elif pattern == "left":
                self._render_left(elapsed)
            elif pattern == "right":
                self._render_right(elapsed)
            else:
                self._render_idle()

        # Music mode: the spectrum visualiser owns BOTH panels (16x32
        # stacked canvas) and fully rewrites every pixel every frame, so
        # gesture renderers above can never leak through. Gesture feedback
        # moved to the frontend (2026-07-26 22:05 decision).
        if self._music_panel_enabled and self._panel_count > 1:
            self._render_music_spectrum(now)

        self._strip.show()

    def _render_beat_pulse(self, elapsed_ms: float) -> None:
        """Render a beat pulse animation.

        Brightness decays from peak to zero over duration_ms.
        """
        duration = self._beat_duration_ms
        if duration <= 0:
            return

        # Decay factor: 1.0 at t=0, 0.0 at t=duration
        decay = max(0.0, 1.0 - elapsed_ms / duration)
        brightness = self._beat_strength * decay * self._brightness_limit

        # Color: white with blue tint at peak, fading to off
        r = int(brightness * 255)
        g = int(brightness * 200)
        b = int(brightness * 255)

        color = self._Color(r, g, b) if hasattr(self, '_Color') else (r << 16) | (g << 8) | b

        # Determine which panels to light
        left_on = self._beat_hand in ("left", "both")
        right_on = self._beat_hand in ("right", "both")

        for i in range(self._total_leds):
            panel = i // self._led_per_panel
            if (panel == 0 and left_on) or (panel == 1 and right_on):
                self._strip.setPixelColor(i, color)
            else:
                self._strip.setPixelColor(i, 0)

    def _render_breathing(self, now: float) -> None:
        """Render a gentle breathing animation.

        Brightness oscillates sinusoidally at a rate proportional to BPM.
        """
        # Breathing cycle: one full breath per BPM beat, or ~4 seconds at rest
        period_s = 60.0 / max(self._bpm, 15.0) if self._bpm > 0 else 4.0
        phase = (now % period_s) / period_s  # 0 to 1

        # Sinusoidal brightness
        brightness = math.sin(phase * 2 * math.pi) * 0.5 + 0.5
        brightness *= self._intensity * self._brightness_limit

        r = int(brightness * 100)
        g = int(brightness * 150)
        b = int(brightness * 255)

        color = self._Color(r, g, b) if hasattr(self, '_Color') else (r << 16) | (g << 8) | b

        # Light gesture panels with weight-based asymmetry
        for i in range(self._gesture_span()):
            panel = i // self._led_per_panel
            weight = self._left_weight if panel == 0 else self._right_weight
            panel_brightness = int(brightness * weight * 255)
            # Apply per-LED variation
            if hasattr(self, '_Color'):
                c = self._Color(
                    int(panel_brightness * 100 / 255),
                    int(panel_brightness * 150 / 255),
                    panel_brightness,
                )
            else:
                c = (int(panel_brightness * 100 / 255) << 16) | (int(panel_brightness * 150 / 255) << 8) | panel_brightness
            self._strip.setPixelColor(i, c)

    def _render_wave(self, now: float) -> None:
        """Render a wave animation sweeping across the gesture panels."""
        span = self._gesture_span()
        # Wave speed proportional to BPM
        speed = self._bpm / 60.0 * span / 4  # LEDs per second
        offset = int((now * speed) % span)

        for i in range(span):
            # Distance from wave front
            dist = (i - offset) % span
            # Gaussian falloff
            sigma = span / 8
            brightness = math.exp(-(dist**2) / (2 * sigma**2))
            brightness *= self._intensity * self._brightness_limit

            byte_val = int(brightness * 255)
            if hasattr(self, '_Color'):
                c = self._Color(byte_val // 2, byte_val, byte_val)
            else:
                c = (byte_val // 2 << 16) | (byte_val << 8) | byte_val
            self._strip.setPixelColor(i, c)

    def _render_idle(self) -> None:
        """Render idle state (very dim static)."""
        for i in range(self._total_leds):
            self._strip.setPixelColor(i, 0)

    # ---- Internal: Gesture animations (2D matrix) ----

    def _render_start(self, elapsed: float) -> None:
        """开始: green wipe from center outward — like raising the baton.

        One-shot over 1.5s, then holds the fully spread state.
        """
        progress = min(elapsed / 1.5, 1.0)
        center = self._cols // 2
        spread = progress * center

        for panel in self._gesture_panels():
            for row in range(self._rows):
                for col in range(self._cols):
                    dist = abs(col - center)
                    if dist <= spread:
                        # Bright at center, fading toward the edges
                        edge = 1.0 - (dist / max(spread, 1.0)) * 0.7
                        self._set_xy(panel, row, col, self._color(0, 255, 0, edge))
                    else:
                        self._set_xy(panel, row, col, self._color(0, 0, 0))

    def _render_stop(self, elapsed: float) -> None:
        """停止: red flash → exponential fade to black. One-shot over 1s."""
        progress = min(elapsed / 1.0, 1.0)

        if progress < 0.15:
            # Initial flash: full red
            self._fill_all(self._color(255, 0, 0))
        else:
            # Exponential decay to black
            fade = (progress - 0.15) / 0.85
            factor = math.exp(-fade * 5)  # e^(-5t)
            self._fill_all(self._color(255, 0, 0, factor))

    def _render_downbeat(self, elapsed: float) -> None:
        """强拍: white flash travelling top → bottom, 0.8s cycle.

        Attack-decay envelope: brightness peaks mid-cycle.
        """
        cycle = (elapsed % 0.8) / 0.8
        flash_row = cycle * self._rows
        envelope = 1.0 - abs(0.5 - cycle) * 2  # Triangle: 0→1→0

        for panel in self._gesture_panels():
            for row in range(self._rows):
                row_factor = max(0.0, 1.0 - abs(row - flash_row) * 0.4) * envelope
                for col in range(self._cols):
                    # Gentle horizontal falloff from center
                    col_factor = max(0.0, 1.0 - abs(col - self._cols / 2) * 0.03)
                    self._set_xy(panel, row, col,
                                 self._color(255, 255, 255, row_factor * col_factor))

    def _render_upbeat(self, elapsed: float) -> None:
        """弱拍: soft gold ripple rising bottom → top, 1.2s cycle."""
        cycle = (elapsed % 1.2) / 1.2
        ripple_center = (1.0 - cycle) * (self._rows - 1)
        ripple_width = 3.0
        fade = math.sin(cycle * math.pi)  # Fade in-out over the cycle

        for panel in self._gesture_panels():
            for row in range(self._rows):
                dist = abs(row - ripple_center)
                factor = max(0.0, 1.0 - dist / ripple_width) * 0.5 * fade
                for col in range(self._cols):
                    self._set_xy(panel, row, col, self._color(255, 200, 50, factor))

    # 流星雨共享参数（crescendo/diminuendo 共用）：手势板视为 8×(32×板数)
    # 画布，轨迹从左下（panel0 row7 col0）飞向右上（末板 row0 col31）。
    # split 模式下画布收缩为单板 8×32。
    _METEOR_SPAWN_S = 0.35    # 生成间隔（约 5 颗同屏）
    _METEOR_TRAVEL_S = 1.4    # 单颗全程飞行时间
    _METEOR_TAIL_S = 0.36     # 尾迹时长（12 个采样 × 30ms）
    _METEOR_TAIL_STEP_S = 0.03
    _METEOR_TAIL_SAMPLES = 12

    def _render_meteor_shower(self, elapsed: float, rgb: tuple, master: float) -> None:
        """Meteor shower bottom-left → top-right across both panels.

        Fully deterministic in `elapsed`: meteors are index-spawned with
        per-index pseudo-variation (no RNG → no frame-to-frame flicker).
        `master` (0-1) scales the whole shower (crescendo ramps up,
        diminuendo ramps down).
        """
        width = self._cols * len(self._gesture_panels())
        life = self._METEOR_TRAVEL_S + self._METEOR_TAIL_S
        buf = [[0.0] * width for _ in range(self._rows)]

        # 跳过早已消亡的流星（elapsed 无界增长时保持 O(同屏数量)）
        i = max(0, int((elapsed - life) / self._METEOR_SPAWN_S))
        while True:
            age = elapsed - i * self._METEOR_SPAWN_S
            if age < 0:
                break
            if age <= life:
                # 索引哈希出确定性的速度/行偏移，形成"阵雨"而非单线
                speed = 1.0 + 0.15 * (((i * 37) % 5) - 2) / 2.0   # 0.85–1.15
                row_bias = (((i * 53) % 5) - 2) * 0.5             # -1.0–1.0
                head = age / self._METEOR_TRAVEL_S * speed        # 进度 0→1+
                for k in range(self._METEOR_TAIL_SAMPLES + 1):
                    tk = head - k * (self._METEOR_TAIL_STEP_S / self._METEOR_TRAVEL_S) * speed
                    if tk < 0:
                        break
                    if tk <= 1.0:
                        fx = tk * (width - 1)
                        fy = (self._rows - 1) * (1.0 - tk) + row_bias
                        x, y = int(round(fx)), int(round(fy))
                        if 0 <= x < width and 0 <= y < self._rows:
                            b = (1.0 - k / self._METEOR_TAIL_SAMPLES) ** 2
                            if b > buf[y][x]:
                                buf[y][x] = b
            i += 1

        r, g, b = rgb
        black = self._color(0, 0, 0)
        for row in range(self._rows):
            for gx in range(width):
                intensity = buf[row][gx]
                panel, col = divmod(gx, self._cols)
                if intensity <= 0:
                    # 必须每帧全画布覆写：灯带是持久帧缓冲，跳过的像素
                    # 会永远残留（旧图案残影/流星尾巴拖住不消）
                    self._set_xy(panel, row, col, black)
                    continue
                # 亮核掺白，模拟流星头部的炽热感
                hot = max(0.0, (intensity - 0.72) / 0.28) * 0.55
                cr = r + (255 - r) * hot
                cg = g + (255 - g) * hot
                cb = b + (255 - b) * hot
                self._set_xy(panel, row, col, self._color(cr, cg, cb, intensity * master))

    def _render_crescendo(self, elapsed: float) -> None:
        """渐强: 蓝紫色流星雨左下→右上，3s 内整体渐亮。"""
        master = 0.30 + 0.70 * min(elapsed / 3.0, 1.0)
        self._render_meteor_shower(elapsed, (110, 50, 255), master)

    def _render_diminuendo(self, elapsed: float) -> None:
        """渐弱: 金黄色流星雨左下→右上，3s 内整体渐暗。"""
        master = 1.0 - 0.75 * min(elapsed / 3.0, 1.0)
        self._render_meteor_shower(elapsed, (255, 190, 40), master)

    def _render_left(self, elapsed: float) -> None:
        """左手提示: left panel blue flash, right panel dim. 1s cycle.

        Split mode: the gesture panel flashes blue; the music panel is
        left to the visualiser.
        """
        pulse = (math.sin(elapsed * 2 * math.pi) + 1) / 2
        self._fill_panel(0, self._color(0, 0, 255, 0.3 + 0.7 * pulse))
        if not self._music_panel_enabled:
            self._fill_panel(1, self._color(0, 0, 255, 0.08))

    def _render_right(self, elapsed: float) -> None:
        """右手提示: right panel pink flash, left panel dim. 1s cycle.

        Split mode: the gesture panel flashes pink; the music panel is
        left to the visualiser.
        """
        pulse = (math.sin(elapsed * 2 * math.pi) + 1) / 2
        if self._music_panel_enabled:
            self._fill_panel(0, self._color(255, 64, 160, 0.3 + 0.7 * pulse))
        else:
            self._fill_panel(0, self._color(255, 64, 160, 0.08))
            self._fill_panel(1, self._color(255, 64, 160, 0.3 + 0.7 * pulse))

    # 频谱柱参数（音乐律动，music 模式的双板 16×32 竖拼画布）
    _SPEC_FALL_ROWS_S = 10.0  # 柱高重力回落速度（画布行/秒，16 行比例）
    _SPEC_KICK_DECAY = 4.0    # kick 包络指数衰减率

    def _canvas_panels(self) -> list[int]:
        """竖拼画布的物理板顺序：[上半屏, 下半屏]。"""
        top = self._music_stack_top_panel % max(1, self._panel_count)
        if self._panel_count < 2:
            return [top]
        return [top, (top + 1) % self._panel_count]

    def _canvas_rows(self) -> int:
        """画布总行数：单板 8 行，双板竖拼 16 行。"""
        return self._rows * len(self._canvas_panels())

    def _canvas_set(self, col: int, row: int, color) -> None:
        """写 16×32 竖拼画布的一个像素（row 0=画布顶，row 15=画布底）。"""
        panels = self._canvas_panels()
        half = self._rows
        panel_idx = row // half
        if panel_idx >= len(panels):
            return
        self._set_xy(panels[panel_idx], row % half, col, color)

    def _render_music_spectrum(self, now: float) -> None:
        """Music-reactive spectrum bars over BOTH panels (music mode).

        Canvas is the two panels stacked vertically: 16 rows x 32 cols
        (top half = music_stack_top_panel). Column heights = slow
        pseudo-random base (deterministic, no RNG → no flicker) scaled by
        energy, plus a per-beat kick envelope. Instant attack, gravity
        fall. Bars grow from canvas bottom (row 15) upward; downbeat
        flashes the canvas bottom row white. Hue follows energy
        (blue → orange). All black when not playing. Writes every pixel
        of both panels every frame, so no other renderer can leak through.
        """
        if self._spec_last_t is None:
            dt = 0.0
        else:
            dt = min(0.1, max(0.0, now - self._spec_last_t))
        self._spec_last_t = now

        playing = self._music["playing"]
        energy = self._music["energy"] if playing else 0.0
        # Smooth the ~2 Hz energy updates so columns don't step visibly.
        self._music_energy_smooth += (energy - self._music_energy_smooth) * min(1.0, dt * 8.0)
        e = self._music_energy_smooth

        kick = self._kick_strength * math.exp(-(now - self._kick_at) * self._SPEC_KICK_DECAY)
        hue = 200.0 - 180.0 * e  # 200° blue (calm) → 20° orange/red (hot)
        rows, cols = self._canvas_rows(), self._cols

        for c in range(cols):
            # 静态列权重 + 各列独立摆动（无空间相位耦合 → 柱子原地弹跳，
            # 无左右漂移感）；kick 近似整板同步上跳，强调"从下往上"。
            w = 0.55 + 0.45 * self._hash01(c * 12.9898)
            wob = 1.0 + 0.18 * math.sin(
                now * (1.0 + 1.7 * self._hash01(c * 7.233))
                + self._hash01(c * 3.7) * 2 * math.pi
            )
            target = rows * ((0.15 + 0.85 * e) * w * wob
                             + 0.45 * kick * (0.7 + 0.3 * self._hash01(c * 5.31)))
            target = min(float(rows), max(0.0, target))
            if not playing:
                target = 0.0

            h = self._spec_heights[c]
            if target > h:
                h = target  # instant attack
            else:
                h = max(target, h - self._SPEC_FALL_ROWS_S * dt)
            self._spec_heights[c] = h

            r_col, g_col, b_col = self._hsv_to_rgb(hue, 0.85, 1.0)
            for r in range(rows):
                from_bottom = rows - 1 - r
                if from_bottom < h:
                    # Brighter toward the column tip
                    scale = max(0.45, 1.0 - 0.12 * (h - 1 - from_bottom))
                    self._canvas_set(c, r, self._color(r_col, g_col, b_col, scale))
                else:
                    self._canvas_set(c, r, self._color(0, 0, 0))

        # Downbeat: canvas bottom-row white flash riding on the kick envelope.
        if playing and self._kick_is_downbeat and kick > 0.35:
            for c in range(cols):
                self._canvas_set(c, rows - 1, self._color(255, 255, 255, min(1.0, kick)))

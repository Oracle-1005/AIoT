"""WS2812B LED controller — dual backend.

Controls two 8x32 WS2812B panels directly from a Raspberry Pi.
Backend is auto-detected at init:
- Pi 5: kernel ws2812-pio driver via /dev/leds0 (preferred; rpi_ws281x
  cannot drive the RP1 PWM). Enable with:
  dtoverlay=ws2812-pio,gpio=19,num_leds=512,brightness=0
- Pi 3/4: rpi_ws281x userspace library on a PWM GPIO (default 19).

LED control is entirely local — no serial protocol or network dependency.

Panel layout:
- Panel 0 (LEDs 0-255): left hand
- Panel 1 (LEDs 256-511): right hand
- Each panel is an 8(row) x 32(col) matrix wired serpentine (zigzag):
  row 0 runs left→right, row 1 right→left, and so on.

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
- 渐强/Crescendo   → blue→cyan→white, dim→bright (3s cycle)
- 渐弱/Diminuendo  → white→cyan→blue, bright→dim (3s cycle)
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
        self._bpm = 120.0
        self._intensity = 0.5
        self._left_weight = 0.5
        self._right_weight = 0.5
        self._connected = False
        self._error = None
        self._backend = "none"
        self._consecutive_errors = 0

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
            "fps": 50,
            "error": self._error,
        }

    # ---- Internal: 2D matrix helpers ----

    def _pixel_index(self, panel: int, row: int, col: int) -> int:
        """Map (panel, row, col) to strip index with serpentine correction.

        Odd rows are wired right→left, so their column order is reversed.
        """
        if row % 2 == 1:
            col = (self._cols - 1) - col
        return panel * self._led_per_panel + row * self._cols + col

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

        # Light both panels with weight-based asymmetry
        for i in range(self._total_leds):
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
        """Render a wave animation sweeping across both panels."""
        # Wave speed proportional to BPM
        speed = self._bpm / 60.0 * self._total_leds / 4  # LEDs per second
        offset = int((now * speed) % self._total_leds)

        for i in range(self._total_leds):
            # Distance from wave front
            dist = (i - offset) % self._total_leds
            # Gaussian falloff
            sigma = self._total_leds / 8
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

        for panel in range(self._panel_count):
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

        for panel in range(self._panel_count):
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

        for panel in range(self._panel_count):
            for row in range(self._rows):
                dist = abs(row - ripple_center)
                factor = max(0.0, 1.0 - dist / ripple_width) * 0.5 * fade
                for col in range(self._cols):
                    self._set_xy(panel, row, col, self._color(255, 200, 50, factor))

    def _render_crescendo(self, elapsed: float) -> None:
        """渐强: blue→cyan→white, dim→bright, 3s cycle.

        Vertical intensity wave reinforces the swelling feel.
        """
        cycle = (elapsed % 3.0) / 3.0
        hue = 240 - cycle * 60        # Blue → cyan
        saturation = 1.0 - cycle * 0.7  # → near-white
        value = 0.15 + cycle * 0.85   # Dim → bright
        r, g, b = self._hsv_to_rgb(hue, saturation, value)

        wave_phase = elapsed * 3.0
        for panel in range(self._panel_count):
            for row in range(self._rows):
                row_phase = row / self._rows
                wave = (math.sin(wave_phase + row_phase * 2 * math.pi) + 1) / 2
                factor = 0.5 + 0.5 * wave
                for col in range(self._cols):
                    self._set_xy(panel, row, col, self._color(r, g, b, factor))

    def _render_diminuendo(self, elapsed: float) -> None:
        """渐弱: white→cyan→blue, bright→dim, 3s cycle.

        Mirror of crescendo — endpoints match for smooth transitions.
        """
        cycle = (elapsed % 3.0) / 3.0
        hue = 180 + cycle * 60          # Cyan → blue
        saturation = 0.3 + cycle * 0.7  # Near-white → saturated
        value = 1.0 - cycle * 0.85      # Bright → dim
        r, g, b = self._hsv_to_rgb(hue, saturation, value)

        wave_phase = elapsed * 3.0
        for panel in range(self._panel_count):
            for row in range(self._rows):
                row_phase = row / self._rows
                wave = (math.sin(wave_phase + row_phase * 2 * math.pi) + 1) / 2
                factor = 0.5 + 0.5 * wave
                for col in range(self._cols):
                    self._set_xy(panel, row, col, self._color(r, g, b, factor))

    def _render_left(self, elapsed: float) -> None:
        """左手提示: left panel blue flash, right panel dim. 1s cycle."""
        pulse = (math.sin(elapsed * 2 * math.pi) + 1) / 2
        self._fill_panel(0, self._color(0, 0, 255, 0.3 + 0.7 * pulse))
        self._fill_panel(1, self._color(0, 0, 255, 0.08))

    def _render_right(self, elapsed: float) -> None:
        """右手提示: right panel blue flash, left panel dim. 1s cycle."""
        pulse = (math.sin(elapsed * 2 * math.pi) + 1) / 2
        self._fill_panel(0, self._color(0, 0, 255, 0.08))
        self._fill_panel(1, self._color(0, 0, 255, 0.3 + 0.7 * pulse))

"""WS2812B LED controller via rpi_ws281x.

Controls two 8x32 WS2812B panels directly from Raspberry Pi GPIO18.
LED control is entirely local — no serial protocol or network dependency.
"""

import logging
import math
import time

logger = logging.getLogger(__name__)


class LedController:
    """Controls two WS2812B 8x32 LED panels via GPIO18.

    Each panel has 256 LEDs (8x32), totaling 512 LEDs. Panels are mapped:
    - Panel 0 (LEDs 0-255): left hand
    - Panel 1 (LEDs 256-511): right hand

    Args:
        gpio: GPIO pin for data output (default 18, physical pin 12).
        panel_count: Number of WS2812B panels (default 2).
        led_per_panel: Number of LEDs per panel (256 for 8x32).
        brightness_limit: Maximum brightness 0-1 (default 0.25 for safety).
    """

    LED_FREQ_HZ = 800000
    LED_DMA = 10
    LED_INVERT = False

    def __init__(
        self,
        gpio: int = 18,
        panel_count: int = 2,
        led_per_panel: int = 256,
        brightness_limit: float = 0.25,
    ):
        self._gpio = gpio
        self._panel_count = panel_count
        self._led_per_panel = led_per_panel
        self._total_leds = panel_count * led_per_panel
        self._brightness_limit = brightness_limit
        self._brightness = 0.0

        # State
        self._current_pattern = "breathing"
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

    def clear(self) -> None:
        """Turn off all LEDs."""
        if self._connected and hasattr(self, '_strip'):
            for i in range(self._total_leds):
                self._strip.setPixelColor(i, 0)
            self._strip.show()

    def update(self) -> None:
        """Compute and display the current animation frame.

        Called at the configured refresh rate (typically 50Hz) by the
        main event loop.
        """
        if not self._connected:
            return

        try:
            self._update_animation()
        except Exception as e:
            logger.error("LED update error: %s", e, exc_info=True)

    def get_status(self) -> dict:
        """Return LED status for the status message."""
        return {
            "connected": self._connected,
            "backend": "rpi_ws281x",
            "gpio": self._gpio,
            "panel_count": self._panel_count,
            "total_leds": self._total_leds,
            "brightness_limit": self._brightness_limit,
            "actual_brightness": round(self._brightness, 3),
            "fps": 50,
            "error": self._error,
        }

    # ---- Internal: Animation ----

    def _update_animation(self) -> None:
        """Generate the current frame of the active animation pattern."""
        now = time.monotonic()

        # Check if a beat pulse is active
        beat_elapsed_ms = (now - self._last_beat_time) * 1000.0
        beat_active = beat_elapsed_ms < self._beat_duration_ms

        if beat_active:
            self._render_beat_pulse(beat_elapsed_ms)
        elif self._current_pattern == "breathing":
            self._render_breathing(now)
        elif self._current_pattern == "wave":
            self._render_wave(now)
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

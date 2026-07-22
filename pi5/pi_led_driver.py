#!/usr/bin/env python3
"""
Pi 5 LED Matrix Driver — MQTT Gesture → WS2812B LED Effects
=============================================================
Subscribes to MQTT gesture predictions and drives 2× 8×32 WS2812B LED matrices
via GPIO, rendering conducting gesture visualizations.

Architecture:
  MQTT: model/gesture → pi_led_driver → GPIO18 → 2× WS2812B 8×32 Matrix

LED Layout:
  Each matrix: 8 rows × 32 columns = 256 LEDs
  Matrix 0 (left):  index 0..255
  Matrix 1 (right): index 256..511
  Total strip: 512 WS2812B LEDs on GPIO 18

Gesture → Effect Mapping:
  - "静止/Idle"      : Breathing blue pulse
  - "开始/Start"     : Green wipe from center outward
  - "停止/Stop"      : Red flash → fade to black
  - "强拍/Downbeat"  : White flash from top to bottom
  - "弱拍/Upbeat"    : Soft yellow ripple
  - "渐强/Crescendo" : Color sweep dim→bright (blue→cyan→white)
  - "渐弱/Diminuendo": Color sweep bright→dim (white→cyan→blue)
  - "左手提示/Left"  : Left matrix highlight
  - "右手提示/Right" : Right matrix highlight
  - Unknown          : Slow rainbow idle

Prerequisites:
  - sudo apt install -y mosquitto mosquitto-clients
  - pip install paho-mqtt rpi_ws281x
  - GPIO 18 connected to WS2812B DIN
  - External 5V power supply for LEDs (Pi 5V pin can only handle ~100 LEDs)
  - Level shifter (3.3V → 5V) on data line recommended

Usage:
  sudo python pi_led_driver.py                    # GPIO requires root
  sudo python pi_led_driver.py --brightness 128   # 50% brightness
"""

import json
import math
import os
import sys
import time
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from typing import Optional

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# MQTT
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_GESTURE = "model/gesture"
MQTT_TOPIC_LED_COMMAND = "led/command"
MQTT_TOPIC_LED_STATUS = "led/status"

# LED Matrix
LED_GPIO_PIN = int(os.getenv("LED_GPIO_PIN", "18"))
LED_DMA_CHANNEL = int(os.getenv("LED_DMA_CHANNEL", "10"))
LED_PWM_FREQ = int(os.getenv("LED_PWM_FREQ", "800000"))  # 800 kHz
LED_ROWS = 8
LED_COLS = 32
NUM_MATRICES = 2
TOTAL_LEDS = LED_ROWS * LED_COLS * NUM_MATRICES  # 512

# Brightness (0-255)
DEFAULT_BRIGHTNESS = int(os.getenv("LED_BRIGHTNESS", "64"))  # 25% default
MAX_BRIGHTNESS = 255

# Gesture smoothing
GESTURE_HISTORY_SIZE = 5
GESTURE_HOLD_TIME = float(os.getenv("GESTURE_HOLD_TIME", "0.5"))  # seconds

# Animation frame rate
ANIMATION_FPS = 60
FRAME_INTERVAL = 1.0 / ANIMATION_FPS

# Status reporting interval
STATUS_INTERVAL = float(os.getenv("STATUS_INTERVAL", "10.0"))


# ---------------------------------------------------------------------------
# Color Utilities
# ---------------------------------------------------------------------------

@dataclass
class Color:
    r: int = 0
    g: int = 0
    b: int = 0

    @staticmethod
    def from_hsv(h: float, s: float = 1.0, v: float = 1.0) -> "Color":
        """Convert HSV (h: 0-360, s: 0-1, v: 0-1) to RGB."""
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
        return Color(
            r=int((r + m) * 255),
            g=int((g + m) * 255),
            b=int((b + m) * 255),
        )

    def scale(self, factor: float) -> "Color":
        """Scale brightness by factor (0.0-1.0)."""
        return Color(
            r=int(self.r * factor),
            g=int(self.g * factor),
            b=int(self.b * factor),
        )

    def to_int(self) -> int:
        """Convert to 24-bit color (GRB format for WS2812B)."""
        # WS2812B uses GRB byte order
        r = max(0, min(255, self.r))
        g = max(0, min(255, self.g))
        b = max(0, min(255, self.b))
        return (g << 16) | (r << 8) | b

    @staticmethod
    def black() -> "Color":
        return Color(0, 0, 0)

    @staticmethod
    def white() -> "Color":
        return Color(255, 255, 255)


# Predefined color palettes
PALETTE = {
    "red": Color(255, 0, 0),
    "green": Color(0, 255, 0),
    "blue": Color(0, 0, 255),
    "yellow": Color(255, 255, 0),
    "cyan": Color(0, 255, 255),
    "magenta": Color(255, 0, 255),
    "white": Color(255, 255, 255),
    "orange": Color(255, 128, 0),
    "gold": Color(255, 200, 50),
    "black": Color(0, 0, 0),
}


# ---------------------------------------------------------------------------
# Gesture Definitions
# ---------------------------------------------------------------------------

class GestureType(Enum):
    IDLE = auto()          # 静止
    START = auto()         # 开始
    STOP = auto()          # 停止
    DOWNBEAT = auto()      # 强拍
    UPBEAT = auto()        # 弱拍
    CRESCENDO = auto()     # 渐强
    DIMINUENDO = auto()    # 渐弱
    LEFT = auto()          # 左手提示
    RIGHT = auto()         # 右手提示
    UNKNOWN = auto()


# Mapping from Chinese/English gesture names to GestureType
GESTURE_MAP = {
    "静止": GestureType.IDLE,
    "idle": GestureType.IDLE,
    "开始": GestureType.START,
    "start": GestureType.START,
    "停止": GestureType.STOP,
    "stop": GestureType.STOP,
    "强拍": GestureType.DOWNBEAT,
    "downbeat": GestureType.DOWNBEAT,
    "弱拍": GestureType.UPBEAT,
    "upbeat": GestureType.UPBEAT,
    "渐强": GestureType.CRESCENDO,
    "crescendo": GestureType.CRESCENDO,
    "渐弱": GestureType.DIMINUENDO,
    "diminuendo": GestureType.DIMINUENDO,
    "左手提示": GestureType.LEFT,
    "left": GestureType.LEFT,
    "右手提示": GestureType.RIGHT,
    "right": GestureType.RIGHT,
}


def classify_gesture(gesture_name: str) -> GestureType:
    """Map gesture name string to GestureType enum."""
    if not gesture_name:
        return GestureType.UNKNOWN
    return GESTURE_MAP.get(gesture_name.lower(), GestureType.UNKNOWN)


# ---------------------------------------------------------------------------
# LED Strip Abstraction
# ---------------------------------------------------------------------------

class LEDStrip:
    """Wrapper around rpi_ws281x for 2× 8×32 WS2812B matrices."""

    def __init__(self, gpio_pin: int = LED_GPIO_PIN, brightness: int = DEFAULT_BRIGHTNESS):
        self.num_leds = TOTAL_LEDS
        self.rows = LED_ROWS
        self.cols = LED_COLS
        self.num_matrices = NUM_MATRICES
        self.brightness = brightness

        # Lazy import — only works on Raspberry Pi
        try:
            from rpi_ws281x import PixelStrip, ws

            LED_FREQ_HZ = LED_PWM_FREQ
            LED_DMA = LED_DMA_CHANNEL
            LED_INVERT = False
            LED_CHANNEL = 0

            self._strip = PixelStrip(
                self.num_leds,
                gpio_pin,
                LED_FREQ_HZ,
                LED_DMA,
                LED_INVERT,
                brightness,
                LED_CHANNEL,
                ws.WS2811_STRIP_GRB,
            )
            self._strip.begin()
            self._available = True
            print(f"[LED] rpi_ws281x initialized: {self.num_leds} LEDs on GPIO {gpio_pin}")
        except ImportError:
            print("[LED] rpi_ws281x not available — using simulated output")
            self._strip = None
            self._available = False
        except Exception as e:
            print(f"[LED] rpi_ws281x init failed: {e} — using simulated output")
            self._strip = None
            self._available = False

    @property
    def available(self) -> bool:
        return self._available

    def set_pixel(self, matrix: int, row: int, col: int, color: Color):
        """
        Set a single pixel.

        Args:
            matrix: 0 (left) or 1 (right)
            row: 0-7 (top to bottom)
            col: 0-31 (left to right)
            color: Color to set

        WS2812B matrices typically use serpentine (zigzag) layout:
        Row 0: left → right
        Row 1: right → left
        Row 2: left → right
        ...
        """
        if matrix < 0 or matrix >= self.num_matrices:
            return
        if row < 0 or row >= self.rows:
            return
        if col < 0 or col >= self.cols:
            return

        # Calculate LED index with serpentine (zigzag) correction
        if row % 2 == 0:
            pixel_col = col
        else:
            pixel_col = (self.cols - 1) - col

        index = matrix * (self.rows * self.cols) + row * self.cols + pixel_col
        self.set_led(index, color)

    def set_led(self, index: int, color: Color):
        """Set raw LED index to color."""
        if not self._available or not self._strip:
            return
        if index < 0 or index >= self.num_leds:
            return
        self._strip.setPixelColor(index, color.to_int())

    def fill_matrix(self, matrix: int, color: Color):
        """Fill an entire matrix with one color."""
        for row in range(self.rows):
            for col in range(self.cols):
                self.set_pixel(matrix, row, col, color)

    def fill_all(self, color: Color):
        """Fill both matrices with one color."""
        for m in range(self.num_matrices):
            self.fill_matrix(m, color)

    def clear(self):
        """Turn off all LEDs."""
        self.fill_all(Color.black())

    def show(self):
        """Push buffer to physical strip."""
        if self._available and self._strip:
            self._strip.show()

    def set_brightness(self, value: int):
        """Adjust global brightness (0-255)."""
        self.brightness = max(0, min(MAX_BRIGHTNESS, value))
        if self._available and self._strip:
            self._strip.setBrightness(self.brightness)


# ---------------------------------------------------------------------------
# Animation Engine
# ---------------------------------------------------------------------------

class AnimationEngine:
    """Manages gesture-driven LED animations with transitions."""

    def __init__(self, strip: LEDStrip):
        self.strip = strip
        self._current_gesture = GestureType.IDLE
        self._start_time = time.time()
        self._frame = 0
        self._running = False
        self._lock = threading.Lock()
        self._gesture_confidence = 0.0

    def update_gesture(self, gesture_type: GestureType, confidence: float = 0.0):
        """Switch to a new gesture animation."""
        with self._lock:
            if gesture_type != self._current_gesture:
                old = self._current_gesture
                self._current_gesture = gesture_type
                self._start_time = time.time()
                self._frame = 0
                print(f"[LED] Gesture: {old.name} → {gesture_type.name} (conf={confidence:.2f})")
            self._gesture_confidence = confidence

    @property
    def current_gesture(self) -> GestureType:
        with self._lock:
            return self._current_gesture

    def render_frame(self):
        """Render one animation frame based on current gesture."""
        self._frame += 1
        elapsed = time.time() - self._start_time

        with self._lock:
            gesture = self._current_gesture

        # Dispatch to animation function
        animator = {
            GestureType.IDLE:        self._anim_idle,
            GestureType.START:       self._anim_start,
            GestureType.STOP:        self._anim_stop,
            GestureType.DOWNBEAT:    self._anim_downbeat,
            GestureType.UPBEAT:      self._anim_upbeat,
            GestureType.CRESCENDO:   self._anim_crescendo,
            GestureType.DIMINUENDO:  self._anim_diminuendo,
            GestureType.LEFT:        self._anim_left,
            GestureType.RIGHT:       self._anim_right,
            GestureType.UNKNOWN:     self._anim_idle,
        }

        anim_fn = animator.get(gesture, self._anim_idle)
        anim_fn(elapsed)

    # ---- Animation Functions --------------------------------------------

    def _anim_idle(self, elapsed: float):
        """Breathing blue pulse — both matrices in sync."""
        phase = elapsed * 2.0  # 2-second cycle
        brightness = (math.sin(phase * math.pi) + 1) / 2  # 0..1
        color = Color(0, 0, int(40 + 40 * brightness))  # Dim blue breathing
        self.strip.fill_all(color)

    def _anim_start(self, elapsed: float):
        """Green wipe from center outward — like a conductor raising the baton."""
        progress = min(elapsed / 1.5, 1.0)  # 1.5s animation

        center_col = self.strip.cols // 2
        spread = int(progress * center_col)

        for m in range(self.strip.num_matrices):
            for row in range(self.strip.rows):
                for col in range(self.strip.cols):
                    dist = abs(col - center_col)
                    if dist <= spread:
                        # Fade from bright green at center to dim at edges
                        edge_factor = 1.0 - (dist / max(spread, 1)) * 0.7
                        c = PALETTE["green"].scale(edge_factor)
                        self.strip.set_pixel(m, row, col, c)
                    else:
                        self.strip.set_pixel(m, row, col, Color.black())

    def _anim_stop(self, elapsed: float):
        """Red flash → fade to black. Like a cutoff gesture."""
        total_duration = 1.0
        progress = min(elapsed / total_duration, 1.0)

        if progress < 0.15:
            # Flash: full bright red
            self.strip.fill_all(PALETTE["red"])
        else:
            # Exponential fade to black
            fade_progress = (progress - 0.15) / 0.85
            factor = math.exp(-fade_progress * 5)  # e^(-5t) decay
            color = PALETTE["red"].scale(factor)
            self.strip.fill_all(color)

    def _anim_downbeat(self, elapsed: float):
        """White flash traveling top → bottom. Strong beat, strong light."""
        cycle = elapsed % 0.8  # 0.8s per beat cycle
        progress = cycle / 0.8

        # Flash position travels downward
        flash_row = int(progress * self.strip.rows)

        # Brightness: attack-decay envelope
        envelope = 1.0 - abs(0.5 - progress) * 2  # Triangle: 0→1→0

        for m in range(self.strip.num_matrices):
            for row in range(self.strip.rows):
                dist = abs(row - flash_row)
                row_factor = max(0, 1.0 - dist * 0.4)
                factor = envelope * row_factor
                if factor > 0.02:
                    self.strip.set_pixel(m, row, self.strip.cols // 2,
                                         PALETTE["white"].scale(factor))

                # Horizontal spread from center
                for col in range(self.strip.cols):
                    col_dist = abs(col - self.strip.cols // 2)
                    col_factor = max(0, 1.0 - col_dist * 0.1) * max(0, 1.0 - dist * 0.5)
                    final = envelope * col_factor
                    if final > 0.02:
                        self.strip.set_pixel(m, row, col, PALETTE["white"].scale(final))

    def _anim_upbeat(self, elapsed: float):
        """Soft yellow ripple — gentle upward motion. Weak beat."""
        cycle = elapsed % 1.2
        progress = cycle / 1.2

        # Ripple moving upward (bottom to top)
        ripple_center = (1.0 - progress) * self.strip.rows
        ripple_width = 3.0

        for m in range(self.strip.num_matrices):
            for row in range(self.strip.rows):
                dist = abs(row - ripple_center)
                if dist < ripple_width:
                    factor = (1.0 - dist / ripple_width) * 0.4  # Soft, dim
                    factor *= math.sin(progress * math.pi)  # Fade in-out
                    if factor > 0.01:
                        self.strip.set_pixel(m, row, self.strip.cols // 2,
                                             PALETTE["gold"].scale(factor))

    def _anim_crescendo(self, elapsed: float):
        """Color sweep from dim blue → bright white. Gets louder/brighter."""
        cycle = elapsed % 3.0
        progress = cycle / 3.0

        # Hue: blue (240) → cyan (180) → white
        # Brightness: dim → bright
        hue = 240 - progress * 180  # Blue to cyan/white
        saturation = 1.0 - progress * 0.5  # More desaturated → white
        value = 0.15 + progress * 0.85   # Dim to bright

        color = Color.from_hsv(hue, saturation, value)

        # Intensity wave from bottom to top
        wave_phase = elapsed * 3.0
        for m in range(self.strip.num_matrices):
            for row in range(self.strip.rows):
                row_phase = row / self.strip.rows
                wave = (math.sin(wave_phase + row_phase * math.pi * 2) + 1) / 2
                wave_factor = 0.5 + 0.5 * wave
                self.strip.set_pixel(m, row, self.strip.cols // 2, color.scale(wave_factor))

    def _anim_diminuendo(self, elapsed: float):
        """Color sweep from bright white → dim blue. Gets softer/dimmer."""
        cycle = elapsed % 3.0
        progress = cycle / 3.0

        hue = 180 - progress * 60     # Cyan → blue
        saturation = 0.5 + progress * 0.5
        value = 0.85 - progress * 0.7   # Bright → dim

        color = Color.from_hsv(hue, saturation, value)
        self.strip.fill_all(color)

    def _anim_left(self, elapsed: float):
        """Left matrix highlight — blue flash on left, dim right."""
        cycle = elapsed % 1.0
        brightness = (math.sin(cycle * math.pi * 2) + 1) / 2  # 0..1

        self.strip.fill_matrix(0, PALETTE["blue"].scale(0.3 + brightness * 0.7))
        self.strip.fill_matrix(1, PALETTE["blue"].scale(0.1))

    def _anim_right(self, elapsed: float):
        """Right matrix highlight — blue flash on right, dim left."""
        cycle = elapsed % 1.0
        brightness = (math.sin(cycle * math.pi * 2) + 1) / 2

        self.strip.fill_matrix(0, PALETTE["blue"].scale(0.1))
        self.strip.fill_matrix(1, PALETTE["blue"].scale(0.3 + brightness * 0.7))


# ---------------------------------------------------------------------------
# Gesture Smoother
# ---------------------------------------------------------------------------

class GestureSmoother:
    """Smooths gesture predictions to avoid flickering."""

    def __init__(self, history_size: int = GESTURE_HISTORY_SIZE,
                 hold_time: float = GESTURE_HOLD_TIME):
        self._history: deque = deque(maxlen=history_size)
        self._hold_time = hold_time
        self._last_change = time.time()
        self._current: Optional[str] = None

    def update(self, gesture: str, confidence: float = 0.0) -> Optional[str]:
        """
        Add a new prediction. Returns the smoothed gesture if it changed.
        """
        self._history.append((gesture, confidence, time.time()))

        if len(self._history) < self._history.maxlen // 2:
            return None  # Not enough data yet

        # Count recent predictions
        from collections import Counter
        names = [g for g, _, _ in self._history]
        counter = Counter(names)
        most_common, count = counter.most_common(1)[0]

        # Require majority agreement
        if count >= len(self._history) * 0.6:
            now = time.time()
            if most_common != self._current:
                # Only change if hold time has elapsed since last change
                if now - self._last_change >= self._hold_time:
                    self._current = most_common
                    self._last_change = now
                    return most_common

        return None  # No change


# ---------------------------------------------------------------------------
# MQTT Subscriber
# ---------------------------------------------------------------------------

class MQTTSubscriber:
    """MQTT client for subscribing to gesture predictions and LED commands."""

    def __init__(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self.broker = broker
        self.port = port
        self._client = None
        self._on_gesture: Optional[callable] = None
        self._on_led_command: Optional[callable] = None

    def on_gesture(self, callback):
        """Register callback: fn(gesture_name: str, confidence: float)."""
        self._on_gesture = callback

    def on_led_command(self, callback):
        """Register callback: fn(command: dict)."""
        self._on_led_command = callback

    def connect_and_subscribe(self):
        import paho.mqtt.client as mqtt

        self._client = mqtt.Client(client_id=f"pi_led_driver_{os.getpid()}")

        def on_connect(client, userdata, flags, rc):
            if rc == 0:
                print(f"[MQTT] Connected to {self.broker}:{self.port}")
                client.subscribe(MQTT_TOPIC_GESTURE, qos=0)
                client.subscribe(MQTT_TOPIC_LED_COMMAND, qos=0)
                print(f"[MQTT] Subscribed to: {MQTT_TOPIC_GESTURE}, {MQTT_TOPIC_LED_COMMAND}")
            else:
                print(f"[MQTT] Connection failed: rc={rc}")

        def on_message(client, userdata, msg):
            try:
                payload = json.loads(msg.payload.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as e:
                print(f"[MQTT] Invalid JSON on {msg.topic}: {e}")
                return

            if msg.topic == MQTT_TOPIC_GESTURE:
                gesture_name = payload.get("gesture", "")
                confidence = payload.get("confidence", 0.0)
                if self._on_gesture:
                    self._on_gesture(gesture_name, confidence)

            elif msg.topic == MQTT_TOPIC_LED_COMMAND:
                if self._on_led_command:
                    self._on_led_command(payload)

        self._client.on_connect = on_connect
        self._client.on_message = on_message
        self._client.connect_async(self.broker, self.port, keepalive=60)
        self._client.loop_start()

    def publish_status(self, status: dict):
        """Publish LED driver status."""
        if self._client:
            self._client.publish(
                MQTT_TOPIC_LED_STATUS,
                json.dumps(status, ensure_ascii=False, separators=(",", ":")),
                qos=0,
            )

    def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None


# ---------------------------------------------------------------------------
# Main Driver
# ---------------------------------------------------------------------------

class LEDDriver:
    """Orchestrates MQTT subscription → gesture smoothing → LED animation."""

    def __init__(self, strip: LEDStrip, mqtt: MQTTSubscriber,
                 brightness: int = DEFAULT_BRIGHTNESS):
        self.strip = strip
        self.mqtt = mqtt
        self.animation = AnimationEngine(strip)
        self.smoother = GestureSmoother()
        self.running = False
        self._frame_count = 0
        self._status_thread: Optional[threading.Thread] = None

        # Wire MQTT callbacks
        self.mqtt.on_gesture(self._handle_gesture)
        self.mqtt.on_led_command(self._handle_led_command)

    def _handle_gesture(self, gesture_name: str, confidence: float):
        """Process incoming gesture prediction."""
        smoothed = self.smoother.update(gesture_name, confidence)
        if smoothed:
            gesture_type = classify_gesture(smoothed)
            self.animation.update_gesture(gesture_type, confidence)

    def _handle_led_command(self, command: dict):
        """Process direct LED commands from MQTT."""
        cmd_type = command.get("command", "")

        if cmd_type == "set_brightness":
            value = command.get("value", DEFAULT_BRIGHTNESS)
            self.strip.set_brightness(int(value))
            print(f"[LED] Brightness set to {value}")

        elif cmd_type == "fill":
            color_name = command.get("color", "black")
            matrix = command.get("matrix")  # None = both
            color = PALETTE.get(color_name, Color.black())
            if matrix is not None:
                self.strip.fill_matrix(int(matrix), color)
            else:
                self.strip.fill_all(color)
            print(f"[LED] Fill: {color_name} (matrix={matrix})")

        elif cmd_type == "clear":
            self.strip.clear()
            print("[LED] Cleared")

        elif cmd_type == "test":
            self._test_pattern()
            print("[LED] Test pattern")

        elif cmd_type == "gesture_override":
            gesture_type = classify_gesture(command.get("gesture", ""))
            self.animation.update_gesture(gesture_type, 1.0)
            print(f"[LED] Gesture override: {gesture_type.name}")

    def _test_pattern(self):
        """Quick test: R→G→B→W across both matrices."""
        colors = [PALETTE["red"], PALETTE["green"], PALETTE["blue"], PALETTE["white"]]
        for i, color in enumerate(colors):
            section = self.strip.num_leds // len(colors)
            for j in range(section):
                idx = i * section + j
                if idx < self.strip.num_leds:
                    self.strip.set_led(idx, color)
        self.strip.show()

    def start(self):
        """Start the main animation loop (blocking)."""
        print("=" * 60)
        print("[LED] Pi 5 LED Matrix Driver")
        print(f"[LED] {self.strip.num_leds} LEDs ({self.strip.num_matrices}×{self.strip.rows}×{self.strip.cols})")
        print(f"[LED] Brightness: {self.strip.brightness}/{MAX_BRIGHTNESS}")
        print(f"[LED] MQTT: {MQTT_BROKER}:{MQTT_PORT}")
        print("=" * 60)

        # Show startup test
        self._test_pattern()
        time.sleep(1.0)
        self.strip.clear()
        self.strip.show()
        print("[LED] Ready. Waiting for gestures...\n")

        self.mqtt.connect_and_subscribe()
        self.running = True

        # Start status reporter
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

        try:
            while self.running:
                frame_start = time.time()

                self.animation.render_frame()
                self.strip.show()
                self._frame_count += 1

                # Maintain frame rate
                elapsed = time.time() - frame_start
                sleep_time = FRAME_INTERVAL - elapsed
                if sleep_time > 0:
                    time.sleep(sleep_time)

        except KeyboardInterrupt:
            print("\n[LED] Shutting down...")
        finally:
            self.stop()

    def stop(self):
        """Graceful shutdown."""
        self.running = False
        self.strip.clear()
        self.strip.show()
        self.mqtt.disconnect()
        if self._status_thread and self._status_thread.is_alive():
            self._status_thread.join(timeout=2)
        print("[LED] Stopped.")

    def _status_loop(self):
        """Periodically report driver status."""
        while self.running:
            time.sleep(STATUS_INTERVAL)
            if not self.running:
                break
            self.mqtt.publish_status({
                "frames_rendered": self._frame_count,
                "current_gesture": self.animation.current_gesture.name,
                "brightness": self.strip.brightness,
                "available": self.strip.available,
                "timestamp": time.time(),
            })


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Pi 5 LED Matrix Driver — MQTT Gesture → WS2812B LED Effects",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT broker port")
    parser.add_argument("--brightness", type=int, default=DEFAULT_BRIGHTNESS,
                        help=f"LED brightness 0-255 (default: {DEFAULT_BRIGHTNESS})")
    parser.add_argument("--gpio", type=int, default=LED_GPIO_PIN,
                        help=f"GPIO pin for WS2812B data (default: {LED_GPIO_PIN})")
    parser.add_argument("--simulate", action="store_true",
                        help="Run without real LED hardware (prints to console)")
    parser.add_argument("--test", action="store_true",
                        help="Run test pattern and exit")
    args = parser.parse_args()

    print("=" * 60)
    print("[LED] Pi 5 LED Matrix Driver")
    print("=" * 60)

    # Initialize LED strip
    strip = LEDStrip(gpio_pin=args.gpio, brightness=args.brightness)

    if args.test:
        driver = LEDDriver(strip, MQTTSubscriber(), brightness=args.brightness)
        driver._test_pattern()
        time.sleep(3)
        strip.clear()
        strip.show()
        print("[LED] Test complete.")
        return

    if not strip.available:
        print("[LED] ⚠ Running in simulation mode (no physical LED strip detected)")
        print("[LED] GPIO root access may be required. Try: sudo python pi_led_driver.py")

    # Initialize MQTT
    mqtt = MQTTSubscriber(broker=args.broker, port=args.port)

    # Start driver
    driver = LEDDriver(strip, mqtt, brightness=args.brightness)
    driver.start()


if __name__ == "__main__":
    main()

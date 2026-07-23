#!/usr/bin/env python3
"""
Pi 5 LED Matrix Driver — MQTT Gesture → WS2812B LED Effects
=============================================================
Subscribes to MQTT gesture predictions and drives 2× 8×32 WS2812B LED matrices
via GPIO, rendering conducting gesture visualizations.

Architecture:
  MQTT: model/gesture → pi_led_driver → LedController → GPIO19 → 2× 8×32 Matrix

This driver is a thin MQTT front-end: all animation rendering (9 gesture
patterns, serpentine 2D matrix mapping, brightness-limit safety) lives in
the shared controller at hardware/raspberry_pi_iot/led/controller.py, which
is also what the team member's fusion stack drives. One renderer, two
front-ends — animations can never drift apart.

LED Layout:
  Each matrix: 8 rows × 32 columns = 256 LEDs
  Matrix 0 (left):  index 0..255
  Matrix 1 (right): index 256..511
  Total strip: 512 WS2812B LEDs on GPIO 19 (physical pin 35)

Gesture → Effect Mapping (defined in controller.py):
  - "静止/Idle"      : Breathing blue pulse
  - "开始/Start"     : Green wipe from center outward
  - "停止/Stop"      : Red flash → fade to black
  - "强拍/Downbeat"  : White flash from top to bottom
  - "弱拍/Upbeat"    : Soft gold ripple bottom → top
  - "渐强/Crescendo" : Color sweep dim→bright (blue→cyan→white)
  - "渐弱/Diminuendo": Color sweep bright→dim (white→cyan→blue)
  - "左手提示/Left"  : Left matrix blue flash, right dim
  - "右手提示/Right" : Right matrix blue flash, left dim

Prerequisites:
  - sudo apt install -y mosquitto mosquitto-clients
  - pip install paho-mqtt rpi_ws281x
  - GPIO 19 connected to WS2812B DIN
  - External 5V power supply for LEDs (Pi 5V pin can only handle ~100 LEDs)
  - Level shifter (3.3V → 5V) on data line recommended

Usage:
  sudo python pi_led_driver.py                    # GPIO requires root
  sudo python pi_led_driver.py --brightness 128   # 50% brightness
"""

import json
import os
import sys
import time
import threading
from collections import deque
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Optional

# Reuse the shared LED controller (9 gesture animations, 2D matrix mapping)
# from the team repo — this driver is now a thin MQTT front-end over it.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent
                       / "hardware" / "raspberry_pi_iot" / "led"))
from controller import LedController, GESTURE_PATTERN_MAP  # noqa: E402

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
LED_GPIO_PIN = int(os.getenv("LED_GPIO_PIN", "19"))  # physical pin 35, PWM1
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

# Animation frame rate (LedController.update() pumps time-based animations)
ANIMATION_FPS = 50
FRAME_INTERVAL = 1.0 / ANIMATION_FPS

# Status reporting interval
STATUS_INTERVAL = float(os.getenv("STATUS_INTERVAL", "10.0"))


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


# Kept for external imports; the canonical name→pattern mapping now lives
# in hardware/raspberry_pi_iot/led/controller.py (GESTURE_PATTERN_MAP).
GESTURE_MAP = {name: GestureType[pattern.upper()] if pattern.upper() in GestureType.__members__ else GestureType.IDLE
               for name, pattern in GESTURE_PATTERN_MAP.items()}


def classify_gesture(gesture_name: str) -> GestureType:
    """Map gesture name string to GestureType enum."""
    if not gesture_name:
        return GestureType.UNKNOWN
    return GESTURE_MAP.get(gesture_name.lower(), GestureType.UNKNOWN)


# ---------------------------------------------------------------------------
# Palette (MQTT led/command "fill" color names)
# ---------------------------------------------------------------------------

@dataclass
class Color:
    r: int = 0
    g: int = 0
    b: int = 0


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
# LED Strip Abstraction — delegates rendering to the shared LedController
# ---------------------------------------------------------------------------

class LEDStrip:
    """Thin wrapper giving LedController the old LEDStrip interface.

    All animation rendering (9 gesture patterns, serpentine 2D mapping,
    brightness-limit scaling) happens inside LedController; this class
    only adapts fill/clear/test-pattern commands used by led/command.
    """

    def __init__(self, gpio_pin: int = LED_GPIO_PIN, brightness: int = DEFAULT_BRIGHTNESS):
        self.brightness = brightness
        self._controller = LedController(
            gpio=gpio_pin,
            panel_count=NUM_MATRICES,
            led_per_panel=LED_ROWS * LED_COLS,
            brightness_limit=max(1, brightness) / 255.0,
            rows=LED_ROWS,
            cols=LED_COLS,
        )
        status = self._controller.get_status()
        self._available = status["connected"]
        if self._available:
            print(f"[LED] LedController initialized: {status['total_leds']} LEDs on GPIO {gpio_pin}")
        elif status["error"] == "rpi_ws281x not installed":
            print("[LED] rpi_ws281x not available — using simulated output")
        else:
            print(f"[LED] LED init failed: {status['error']} — using simulated output")

    @property
    def available(self) -> bool:
        return self._available

    @property
    def controller(self) -> LedController:
        return self._controller

    def render(self):
        """Advance the animation one frame (call at ANIMATION_FPS)."""
        self._controller.update()

    def fill_all(self, color: Color):
        """Fill both matrices with one color (immediate, one-shot)."""
        if self._available:
            self._controller._fill_all(self._to_strip_color(color))
            self._controller._strip.show()

    def fill_matrix(self, matrix: int, color: Color):
        """Fill one matrix (0=left, 1=right) with one color."""
        if self._available and 0 <= matrix < NUM_MATRICES:
            self._controller._fill_panel(matrix, self._to_strip_color(color))
            self._controller._strip.show()

    def clear(self):
        """Turn off all LEDs."""
        self._controller.clear()

    def show(self):
        """Present — animations self-present via render(); no-op otherwise."""
        if self._available:
            self._controller._strip.show()

    def set_brightness(self, value: int):
        """Adjust global brightness (0-255)."""
        self.brightness = max(0, min(MAX_BRIGHTNESS, value))
        if self._available:
            self._controller._strip.setBrightness(self.brightness)

    def _to_strip_color(self, color: Color):
        """Build a raw 0-255 color for one-shot fills (no brightness_limit)."""
        if self._available and hasattr(self._controller, "_Color"):
            return self._controller._Color(
                max(0, min(255, color.r)),
                max(0, min(255, color.g)),
                max(0, min(255, color.b)),
            )
        return 0


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
            applied = self.strip.controller.show_gesture(smoothed, confidence)
            if applied:
                print(f"[LED] Gesture: {smoothed} (conf={confidence:.2f})")

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
            color = PALETTE.get(color_name, PALETTE["black"])
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
            gesture = command.get("gesture", "")
            applied = self.strip.controller.show_gesture(gesture, 1.0)
            print(f"[LED] Gesture override: {gesture!r} → {'applied' if applied else 'unknown'}")

    def _test_pattern(self):
        """Quick test: R→G→B→W across both matrices."""
        colors = [PALETTE["red"], PALETTE["green"], PALETTE["blue"], PALETTE["white"]]
        for name, color in (("red", colors[0]), ("green", colors[1]),
                            ("blue", colors[2]), ("white", colors[3])):
            print(f"[LED]   all panels {name} (0.5s)")
            self.strip.fill_all(color)
            time.sleep(0.5)
        self.strip.clear()
        print("[LED] Test pattern done")

    def start(self):
        """Start the main animation loop (blocking)."""
        status = self.strip.controller.get_status()
        print("=" * 60)
        print("[LED] Pi 5 LED Matrix Driver")
        print(f"[LED] {status['total_leds']} LEDs ({status['panel_count']}×{LED_ROWS}×{LED_COLS})")
        print(f"[LED] Brightness: {self.strip.brightness}/{MAX_BRIGHTNESS}")
        print(f"[LED] MQTT: {MQTT_BROKER}:{MQTT_PORT}")
        print("=" * 60)

        # Show startup test
        self._test_pattern()
        print("[LED] Ready. Waiting for gestures...\n")

        self.mqtt.connect_and_subscribe()
        self.running = True

        # Start status reporter
        self._status_thread = threading.Thread(target=self._status_loop, daemon=True)
        self._status_thread.start()

        try:
            while self.running:
                frame_start = time.time()

                self.strip.render()
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
                "current_pattern": self.strip.controller.get_status()["current_pattern"],
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

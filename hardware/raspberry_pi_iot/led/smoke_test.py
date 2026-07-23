#!/usr/bin/env python3
"""Standalone WS2812B hardware smoke test — no camera / BLE / MQTT / fusion.

Verifies the physical LED chain step by step, using only LedController's
public API (clear / show_beat / set_state / show_gesture / update).

Phases:
  basic    — clear, then beat pulses: left → right → both
             (confirms power, data line, and panel order)
  scan     — light one row at a time, top → bottom, left panel first
             (confirms 8x32 serpentine orientation and panel boundaries)
  gestures — cycle all 9 RF gestures via show_gesture() with the real
             Chinese labels the model publishes
  state    — breathing pattern driven by set_state() (bpm / intensity /
             left-right weights), the fusion-stack code path

Run on the Pi from anywhere (imports controller.py from this directory):
  sudo ~/aiot_conductor/project/camera_to_Pi/.venv/bin/python smoke_test.py
  sudo ... python smoke_test.py --phase gestures --seconds 4
  sudo ... python smoke_test.py --brightness-limit 0.1   # extra-dim first light

Requires rpi_ws281x in the active venv and root (GPIO/DMA access).
"""

import argparse
import logging
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from controller import LedController  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger("smoke_test")

FPS = 50

# The 9 RF gestures, in demo order, with what you should see on the panels.
GESTURE_TOUR = [
    ("静止",   "both panels: slow blue breathing"),
    ("开始",   "both panels: green wipe center → outward (one-shot, holds)"),
    ("强拍",   "both panels: white flash travelling top → bottom"),
    ("弱拍",   "both panels: soft gold ripple rising bottom → top"),
    ("渐强",   "both panels: blue→cyan→white, dim → bright (3s cycle)"),
    ("渐弱",   "both panels: white→cyan→blue, bright → dim (3s cycle)"),
    ("左手提示", "LEFT panel blue flashing, right panel nearly dark"),
    ("右手提示", "RIGHT panel blue flashing, left panel nearly dark"),
    ("停止",   "both panels: red flash → exponential fade to black (one-shot)"),
]


def run_for(controller: LedController, seconds: float) -> None:
    """Pump update() at 50Hz for the given duration."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        controller.update()
        time.sleep(1.0 / FPS)


def phase_basic(controller: LedController) -> None:
    print("\n=== Phase: basic (clear + beat pulses) ===")
    print("clear → all LEDs OFF for 1s")
    controller.clear()
    time.sleep(1.0)

    for hand in ("left", "right", "both"):
        print(f"show_beat({hand!r}, strength=1.0) → {hand} panel(s) flash white-blue")
        controller.show_beat(hand=hand, strength=1.0, duration_ms=300)
        run_for(controller, 0.6)
    controller.clear()


def phase_scan(controller: LedController) -> None:
    print("\n=== Phase: scan (row-by-row orientation check) ===")
    print("Expect: LEFT panel lights row by row top→bottom, then RIGHT panel.")
    print("(If rows light in a different order, the panel wiring differs from")
    print(" the assumed 8x32 row-serpentine layout — note what you see.)")
    strip = controller._strip  # smoke test only: direct buffer access
    for panel in range(controller._panel_count):
        for row in range(controller._rows):
            controller.clear()
            for col in range(controller._cols):
                idx = controller._pixel_index(panel, row, col)
                strip.setPixelColor(idx, controller._color(0, 128, 255))
            strip.show()
            print(f"  panel={panel} ({'left' if panel == 0 else 'right'}) row={row}", end="\r")
            time.sleep(0.4)
    print()
    controller.clear()


def phase_gestures(controller: LedController, seconds: float) -> None:
    print("\n=== Phase: gestures (9 RF gestures via show_gesture) ===")
    for gesture, description in GESTURE_TOUR:
        print(f"[{gesture}] → {description}")
        controller.show_gesture(gesture, confidence=1.0)
        run_for(controller, seconds)
    controller.clear()


def phase_state(controller: LedController) -> None:
    print("\n=== Phase: state (breathing driven by set_state) ===")
    controller.set_pattern("breathing")

    steps = [
        (dict(bpm=60, intensity=0.3, left_weight=1.0, right_weight=1.0),
         "bpm=60 intensity=0.3 — slow dim breathing, both panels even"),
        (dict(bpm=120, intensity=0.8, left_weight=1.0, right_weight=0.3),
         "bpm=120 intensity=0.8 — faster brighter, LEFT panel dominant"),
        (dict(bpm=120, intensity=0.8, left_weight=0.3, right_weight=1.0),
         "bpm=120 intensity=0.8 — RIGHT panel dominant"),
        (dict(bpm=180, intensity=1.0, left_weight=1.0, right_weight=1.0),
         "bpm=180 intensity=1.0 — fastest brightest"),
    ]
    for kwargs, description in steps:
        print(f"set_state({kwargs}) → {description}")
        controller.set_state(**kwargs)
        run_for(controller, 3.0)
    controller.clear()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--gpio", type=int, default=19, help="data GPIO (default 19)")
    parser.add_argument("--panels", type=int, default=2, help="panel count (default 2)")
    parser.add_argument("--brightness-limit", type=float, default=0.25,
                        help="0-1, keep ≤0.25 for first light (default 0.25)")
    parser.add_argument("--phase", choices=["all", "basic", "scan", "gestures", "state"],
                        default="all", help="which phase to run (default: all)")
    parser.add_argument("--seconds", type=float, default=3.0,
                        help="seconds per gesture in the gestures phase (default 3)")
    args = parser.parse_args()

    print("=" * 60)
    print("WS2812B smoke test — standalone, no camera/BLE/MQTT")
    print(f"gpio={args.gpio} panels={args.panels} brightness_limit={args.brightness_limit}")
    print("=" * 60)

    controller = LedController(
        gpio=args.gpio,
        panel_count=args.panels,
        brightness_limit=args.brightness_limit,
    )
    status = controller.get_status()
    print(f"controller status: {status}")
    if not status["connected"]:
        print("\nERROR: LED strip not connected. Likely causes:")
        print("  - rpi_ws281x not installed in THIS venv (check: pip show rpi-ws281x)")
        print("  - not running as root (GPIO/DMA needs sudo)")
        print("  - another process holds the PWM GPIO (e.g. an old LED/BLE script)")
        return 1

    try:
        if args.phase in ("all", "basic"):
            phase_basic(controller)
        if args.phase in ("all", "scan"):
            phase_scan(controller)
        if args.phase in ("all", "gestures"):
            phase_gestures(controller, args.seconds)
        if args.phase in ("all", "state"):
            phase_state(controller)
    except KeyboardInterrupt:
        print("\ninterrupted — clearing LEDs")
    finally:
        controller.clear()

    print("\nsmoke test done. Panels are OFF.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Tests for LedController music mode (dual-panel 16x32 stacked canvas).

2026-07-26 22:05 decision + 2026-07-27 user layout spec: BOTH panels run
the music spectrum visualiser, stacked VERTICALLY into a 16-row x 32-col
canvas (not 8x64 horizontal). Gesture patterns get an empty canvas in
music mode (gesture feedback moved to the frontend).

Covers:
  1. Music mode: gesture renderers produce no pixels (both panels owned
     by the spectrum); not playing -> whole strip black, even with kicks.
  2. Spectrum: playing + kick lights columns from the canvas bottom up
     (bottom panel first, tall columns cross into the top panel); heights
     decay; stop fades to black; downbeat flashes the canvas bottom row.
  3. Canvas mapping: rows 0-7 -> top panel, 8-15 -> bottom panel,
     serpentine-corrected; music_stack_top_panel flips the halves.
  4. Legacy mode (music_panel_enabled=False) unchanged (regression).
  5. Pattern-switch pixel hygiene in music mode + legacy meteor behavior.

Runs offline: a FakeStrip is injected, no /dev/leds0 or rpi_ws281x needed.

Usage:
    cd hardware/raspberry_pi_iot/led
    python test_music_panel.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

# hardware/ on sys.path (same convention as fusion_pipeline tests)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from raspberry_pi_iot.led.controller import LedController

_passed = 0
_failed = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global _passed, _failed
    if condition:
        _passed += 1
        print(f"  PASS  {name}")
    else:
        _failed += 1
        print(f"  FAIL  {name}  {detail}")


class FakeStrip:
    """PixelStrip stand-in: records the latest color per LED."""

    def __init__(self, num_leds: int = 512) -> None:
        self.buf = [0] * num_leds
        self.shows = 0

    def setPixelColor(self, i: int, color: int) -> None:
        self.buf[i] = color

    def show(self) -> None:
        self.shows += 1


def make_controller(music_panel: bool, top_panel: int = 0) -> tuple[LedController, FakeStrip]:
    """Real __init__ (fails to find hardware offline), then inject FakeStrip."""
    ctl = LedController(music_panel_enabled=music_panel,
                        music_stack_top_panel=top_panel)
    strip = FakeStrip()
    ctl._strip = strip
    ctl._connected = True
    ctl._backend = "fake"
    return ctl, strip


def panel_lit(buf: list[int], panel: int) -> int:
    """Count of non-zero LEDs in one 256-LED panel."""
    start = panel * 256
    return sum(1 for v in buf[start:start + 256] if v != 0)


def strip_index(panel: int, row: int, col: int) -> int:
    """Mirror of controller._pixel_index (column-major serpentine)."""
    if col % 2 == 1:
        row = 7 - row
    return panel * 256 + col * 8 + row


# ── 1. Music mode: gesture renderers produce nothing ──────────────────────

def test_gesture_renderers_empty() -> None:
    print("\n[1] Music mode: gesture renderers own no pixels")
    ctl, strip = make_controller(music_panel=True)
    ctl.set_music_state(playing=False)

    mid_cycle = {"start": 0.75, "downbeat": 0.4, "upbeat": 0.6,
                 "left": 0.25, "right": 0.25, "stop": 0.1,
                 "crescendo": 1.0, "diminuendo": 1.0}
    for pattern, jump in mid_cycle.items():
        ctl.set_pattern(pattern)
        ctl._pattern_start -= jump
        strip.buf = [0] * 512
        ctl.update()
        lit = sum(1 for v in strip.buf if v != 0)
        check(f"{pattern}: whole strip black (not playing)", lit == 0,
              f"lit={lit}")

    # Beat pulses are overwritten by the spectrum in the same frame too
    ctl.set_pattern("breathing")
    ctl.show_beat("both", 1.0, 120)
    strip.buf = [0] * 512
    ctl.update()
    check("beat pulse invisible under music canvas",
          all(v == 0 for v in strip.buf))

    # 1D renderers (breathing/wave) confined the same way
    for pattern in ("breathing", "wave"):
        ctl.set_pattern(pattern)
        ctl.set_state(bpm=120.0)
        strip.buf = [0] * 512
        ctl.update()
        check(f"{pattern}: no pixels in music mode",
              all(v == 0 for v in strip.buf))


# ── 2. Dual-panel spectrum behaviour ──────────────────────────────────────

def test_music_spectrum() -> None:
    print("\n[2] Music spectrum over the stacked 16x32 canvas")
    ctl, strip = make_controller(music_panel=True)  # top panel = 0

    # Not playing → spectrum stays black even after kicks
    ctl.set_music_state(playing=False, energy=0.9)
    ctl.music_kick(1.0)
    strip.buf = [0] * 512
    ctl.update()
    check("not playing: both panels black despite kick",
          all(v == 0 for v in strip.buf))

    # Playing + kick → columns light up. Warm up the energy smoother
    # first (~8/s convergence) so the decay assertion below isn't
    # confounded by the energy ramp attacking columns upwards.
    ctl.set_music_state(playing=True, energy=0.8)
    for _ in range(40):
        ctl.update()
        ctl._spec_last_t -= 0.05

    ctl.music_kick(1.0)
    ctl._spec_last_t -= 0.05
    strip.buf = [0] * 512
    ctl.update()
    bottom_lit = panel_lit(strip.buf, 1)   # canvas rows 8-15
    check("playing + kick: bottom panel lit", bottom_lit > 0,
          f"lit={bottom_lit}")
    heights_after_kick = max(ctl._spec_heights)
    check("kick raises column heights", heights_after_kick > 2.0,
          f"max height={heights_after_kick:.2f}")
    check("some columns cross into top panel (height > 8)",
          heights_after_kick > 8.0,
          f"max height={heights_after_kick:.2f}")

    # Bars grow from the canvas bottom: with a tiny height only the
    # canvas bottom row (panel 1 row 7) may be lit.
    ctl._spec_heights = [0.5] * 32
    ctl._kick_strength = 0.0
    ctl._music_energy_smooth = 0.0
    strip.buf = [0] * 512
    ctl.update()
    bottom_row = [strip.buf[strip_index(1, 7, c)] for c in range(32)]
    check("growth starts at canvas bottom row (panel 1 row 7)",
          all(v != 0 for v in bottom_row))
    top_panel_lit = panel_lit(strip.buf, 0)
    check("top panel still black at small heights", top_panel_lit == 0,
          f"lit={top_panel_lit}")

    # Downbeat: canvas bottom row flashes white while kick is hot
    # (white at brightness_limit 0.25 -> 0x3F3F3F per channel)
    ctl.set_music_state(playing=True, energy=0.8)
    ctl.music_kick(1.0)  # downbeat
    strip.buf = [0] * 512
    ctl.update()
    white_row = [strip.buf[strip_index(1, 7, c)] for c in range(32)]
    check("downbeat: canvas bottom row white flash",
          all(v == 0x3F3F3F for v in white_row),
          f"row={[hex(v) for v in white_row[:6]]}")

    # Decay: re-converge the energy smoother, kick to the peak, then age
    # the kick 0.5 s — mean height must fall (gravity + envelope decay).
    for _ in range(40):
        ctl.update()
        ctl._spec_last_t -= 0.05
    ctl.music_kick(1.0)
    ctl._spec_last_t -= 0.05
    ctl.update()
    mean_before = sum(ctl._spec_heights) / len(ctl._spec_heights)
    ctl._kick_at -= 0.5
    ctl._spec_last_t -= 0.5
    ctl.update()
    mean_after = sum(ctl._spec_heights) / len(ctl._spec_heights)
    check("heights decay after kick", mean_after < mean_before,
          f"mean {mean_before:.2f} -> {mean_after:.2f}")

    # Stop → columns fall to zero over ~2 s of frames
    ctl.set_music_state(playing=False)
    for _ in range(120):  # 120 frames x dt~0.017-0.1 s is plenty
        ctl._spec_last_t -= 0.05
        ctl.update()
    check("stop: columns fall back to zero", max(ctl._spec_heights) < 0.05,
          f"max height={max(ctl._spec_heights):.3f}")
    strip.buf = [0] * 512
    ctl.update()
    check("stop: both panels black again", all(v == 0 for v in strip.buf))


def test_kick_stacking() -> None:
    print("\n[2b] music_kick stacking / downbeat flag")
    ctl, _ = make_controller(music_panel=True)

    ctl.music_kick(1.0)
    check("downbeat flagged at strength 1.0", ctl._kick_is_downbeat is True)

    # Weaker kick 0.5 s later: remnant decays below 0.45 → new strength wins
    ctl._kick_at -= 0.5
    ctl.music_kick(0.45)
    check("stronger new kick wins", abs(ctl._kick_strength - 0.45) < 1e-6,
          f"strength={ctl._kick_strength}")
    check("0.45 is not a downbeat", ctl._kick_is_downbeat is False)

    # Strong remnant (recent kick) beats a weak new kick
    ctl.music_kick(1.0)
    ctl._kick_at -= 0.05  # remnant ~ e^-0.2 ~ 0.82
    ctl.music_kick(0.45)
    check("decaying remnant kept over weak kick", ctl._kick_strength > 0.7,
          f"strength={ctl._kick_strength}")

    # bpm passthrough and clamping
    ctl.music_kick(2.5, bpm=108.0)
    check("strength clamped to 1.0", ctl._kick_strength == 1.0)
    check("bpm recorded", ctl._music["bpm"] == 108.0)


# ── 3. Canvas mapping (16-row stack + flip) ───────────────────────────────

def test_canvas_mapping() -> None:
    print("\n[3] 16x32 canvas mapping and stack flip")
    ctl, strip = make_controller(music_panel=True, top_panel=0)

    check("canvas has 16 rows", ctl._canvas_rows() == 16)
    ctl._canvas_set(0, 0, 0x101010)    # canvas top -> panel 0 row 0
    ctl._canvas_set(0, 7, 0x202020)    # -> panel 0 row 7
    ctl._canvas_set(0, 8, 0x303030)    # canvas bottom half -> panel 1 row 0
    ctl._canvas_set(0, 15, 0x404040)   # canvas bottom -> panel 1 row 7
    check("row 0 -> panel 0 row 0", strip.buf[strip_index(0, 0, 0)] == 0x101010)
    check("row 7 -> panel 0 row 7", strip.buf[strip_index(0, 7, 0)] == 0x202020)
    check("row 8 -> panel 1 row 0", strip.buf[strip_index(1, 0, 0)] == 0x303030)
    check("row 15 -> panel 1 row 7", strip.buf[strip_index(1, 7, 0)] == 0x404040)

    # Serpentine: odd columns run bottom-up inside their panel
    strip.buf = [0] * 512
    ctl._canvas_set(1, 0, 0x505050)    # col 1 odd -> physical row 7
    check("col 1 (odd) row 0 -> flipped physical row",
          strip.buf[strip_index(0, 0, 1)] == 0x505050)

    # Flipped stack: top_panel=1 swaps the halves
    ctl2, strip2 = make_controller(music_panel=True, top_panel=1)
    ctl2._canvas_set(0, 0, 0x606060)
    ctl2._canvas_set(0, 15, 0x707070)
    check("flip: row 0 -> panel 1 row 0",
          strip2.buf[strip_index(1, 0, 0)] == 0x606060)
    check("flip: row 15 -> panel 0 row 7",
          strip2.buf[strip_index(0, 7, 0)] == 0x707070)


# ── 4. Legacy mode regression ─────────────────────────────────────────────

def test_legacy_mode() -> None:
    print("\n[4] Legacy mode (music_panel_enabled=False) unchanged")
    ctl, strip = make_controller(music_panel=False)

    ctl.set_pattern("start")
    strip.buf = [0] * 512
    ctl.update()
    check("start still mirrors to panel 1", panel_lit(strip.buf, 1) > 0)
    check("spectrum never rendered", ctl._spec_last_t is None)

    # Music messages accepted but have no visual effect
    ctl.set_music_state(playing=True, energy=0.9)
    ctl.music_kick(1.0)
    strip.buf = [0] * 512
    ctl.update()
    check("no spectrum render in legacy mode", ctl._spec_last_t is None)

    # get_status exposes the music fields
    status = ctl.get_status()
    check("status has music fields",
          status["music_panel_enabled"] is False
          and status["music_stack_top_panel"] == 0
          and status["music"]["playing"] is True)


# ── 5. Pixel hygiene (music mode + legacy meteor) ─────────────────────────

def test_pattern_switch_clears() -> None:
    print("\n[5] Pattern switch pixel hygiene")
    SENTINEL = 0x123456

    # 5a. Music mode: gesture span is empty so set_pattern clears nothing,
    # but the spectrum fully overwrites the strip on the very next frame.
    ctl, strip = make_controller(music_panel=True)
    strip.buf = [SENTINEL] * 512
    ctl.set_pattern("crescendo")
    ctl.update()   # not playing -> spectrum writes everything black
    check("music mode: one frame after switch, no stale pixels",
          all(v == 0 for v in strip.buf))

    # 5b. Legacy mode: switching INTO the meteor renderer must fully
    # overwrite the gesture canvas on the first frame (dark meteor pixels
    # must not freeze the old pattern).
    ctl1, strip1 = make_controller(music_panel=False)
    strip1.buf = [SENTINEL] * 512
    ctl1.set_pattern("crescendo")
    ctl1._pattern_start -= 0.7  # meteor 0 mid-flight
    strip1.buf = [SENTINEL] * 512  # re-dirty AFTER the set_pattern clear
    ctl1.update()
    check("legacy meteor: no stale pixels anywhere",
          all(v != SENTINEL for v in strip1.buf))
    check("legacy meteor: some pixels lit mid-flight",
          panel_lit(strip1.buf, 0) > 0)

    # 5c. Meteor tails actually expire (legacy canvas, both panels)
    ctl2, strip2 = make_controller(music_panel=False)
    original_spawn = ctl2._METEOR_SPAWN_S
    try:
        ctl2._METEOR_SPAWN_S = 1000.0  # only meteor 0 ever exists
        ctl2.set_pattern("crescendo")
        ctl2._pattern_start -= 0.7   # meteor 0 mid-flight
        ctl2.update()
        lit = {i for i, v in enumerate(strip2.buf) if v != 0}
        check("meteor: trail lit while alive", len(lit) > 0, f"lit={len(lit)}")
        ctl2._pattern_start -= 2.0   # meteor 0 now dead (age > travel+tail)
        ctl2.update()
        still_lit = [i for i in lit if strip2.buf[i] != 0]
        check("meteor: dead trail written black", still_lit == [],
              f"stuck at {still_lit[:8]}")
    finally:
        ctl2._METEOR_SPAWN_S = original_spawn

    # 5d. Legacy mode: clear covers both panels
    ctl3, strip3 = make_controller(music_panel=False)
    strip3.buf = [SENTINEL] * 512
    ctl3.set_pattern("downbeat")
    check("legacy: whole strip zeroed on switch",
          all(v == 0 for v in strip3.buf))


def main() -> int:
    test_gesture_renderers_empty()
    test_music_spectrum()
    test_kick_stacking()
    test_canvas_mapping()
    test_legacy_mode()
    test_pattern_switch_clears()

    print(f"\n{'=' * 50}\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

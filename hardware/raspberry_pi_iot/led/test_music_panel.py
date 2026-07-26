#!/usr/bin/env python3
"""Tests for LedController split mode (gesture panel + music spectrum panel).

Covers:
  1. Split mode confines gesture patterns (incl. meteor shower, cues) to
     panel 0 — indices 256-511 are never written by gesture renderers.
  2. Music spectrum: black when not playing, lights on kick while playing,
     heights decay over time, kick stacking by max().
  3. Legacy mode (music_panel_enabled=False) is unchanged (regression).

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


def make_controller(music_panel: bool) -> tuple[LedController, FakeStrip]:
    """Real __init__ (fails to find hardware offline), then inject FakeStrip."""
    ctl = LedController(music_panel_enabled=music_panel)
    strip = FakeStrip()
    ctl._strip = strip
    ctl._connected = True
    ctl._backend = "fake"
    return ctl, strip


def panel_lit(buf: list[int], panel: int) -> int:
    """Count of non-zero LEDs in one 256-LED panel."""
    start = panel * 256
    return sum(1 for v in buf[start:start + 256] if v != 0)


# ── 1. Split-mode gesture confinement ─────────────────────────────────────

def test_gesture_confinement() -> None:
    print("\n[1] Split mode: gesture patterns stay on panel 0")
    ctl, strip = make_controller(music_panel=True)

    # downbeat/upbeat envelopes start at zero — jump to mid-cycle instead
    mid_cycle = {"start": 0.75, "downbeat": 0.4, "upbeat": 0.6,
                 "left": 0.25, "right": 0.25}
    for pattern in ("start", "downbeat", "upbeat", "left", "right"):
        ctl.set_pattern(pattern)
        ctl._pattern_start -= mid_cycle[pattern]
        strip.buf = [0] * 512
        ctl.update()
        check(f"{pattern}: panel 0 lit", panel_lit(strip.buf, 0) > 0)
        check(f"{pattern}: panel 1 untouched (not playing)",
              panel_lit(strip.buf, 1) == 0,
              f"panel1 lit={panel_lit(strip.buf, 1)}")

    # Meteor shower (crescendo/diminuendo) renders within an 8x32 canvas now
    strip.buf = [0] * 512
    ctl._render_meteor_shower(2.0, (110, 50, 255), 1.0)
    check("meteor: panel 0 lit", panel_lit(strip.buf, 0) > 0)
    check("meteor: never crosses to panel 1", panel_lit(strip.buf, 1) == 0,
          f"panel1 lit={panel_lit(strip.buf, 1)}")

    # 1D renderers (breathing/wave) are also confined
    for pattern in ("breathing", "wave"):
        ctl.set_pattern(pattern)
        ctl.set_state(bpm=120.0)
        strip.buf = [0] * 512
        ctl.update()
        check(f"{pattern}: panel 1 untouched", panel_lit(strip.buf, 1) == 0)


# ── 2. Music spectrum behaviour ───────────────────────────────────────────

def test_music_spectrum() -> None:
    print("\n[2] Music spectrum renderer")
    ctl, strip = make_controller(music_panel=True)
    ctl.set_pattern("idle")  # gesture side dark, isolate panel 1

    # Not playing → spectrum stays black even after kicks
    ctl.set_music_state(playing=False, energy=0.9)
    ctl.music_kick(1.0)
    strip.buf = [0] * 512
    ctl.update()
    check("not playing: panel 1 black despite kick", panel_lit(strip.buf, 1) == 0)

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
    lit = panel_lit(strip.buf, 1)
    check("playing + kick: panel 1 lit", lit > 0, f"lit={lit}")
    heights_after_kick = max(ctl._spec_heights)
    check("kick raises column heights", heights_after_kick > 2.0,
          f"max height={heights_after_kick:.2f}")

    # Decay: simulate 0.5 s passing — mean height must fall (gravity +
    # kick envelope decay). dt is clamped to 0.1 s per frame.
    mean_before = sum(ctl._spec_heights) / len(ctl._spec_heights)
    ctl._kick_at -= 0.5
    ctl._spec_last_t -= 0.5
    ctl.update()
    mean_after = sum(ctl._spec_heights) / len(ctl._spec_heights)
    check("heights decay after kick", mean_after < mean_before,
          f"mean {mean_before:.2f} → {mean_after:.2f}")

    # Stop → columns fall to zero over ~2 s of frames
    ctl.set_music_state(playing=False)
    for _ in range(120):  # 120 frames × dt≈0.017-0.1 s is plenty
        ctl._spec_last_t -= 0.05
        ctl.update()
    check("stop: columns fall back to zero", max(ctl._spec_heights) < 0.05,
          f"max height={max(ctl._spec_heights):.3f}")
    strip.buf = [0] * 512
    ctl.update()
    check("stop: panel 1 black again", panel_lit(strip.buf, 1) == 0)


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
    ctl._kick_at -= 0.05  # remnant ≈ e^-0.2 ≈ 0.82
    ctl.music_kick(0.45)
    check("decaying remnant kept over weak kick", ctl._kick_strength > 0.7,
          f"strength={ctl._kick_strength}")

    # bpm passthrough and clamping
    ctl.music_kick(2.5, bpm=108.0)
    check("strength clamped to 1.0", ctl._kick_strength == 1.0)
    check("bpm recorded", ctl._music["bpm"] == 108.0)


# ── 3. Legacy mode regression ─────────────────────────────────────────────

def test_legacy_mode() -> None:
    print("\n[3] Legacy mode (music_panel_enabled=False) unchanged")
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

    # get_status exposes the new fields
    status = ctl.get_status()
    check("status has music fields",
          status["music_panel_enabled"] is False and status["music"]["playing"] is True)


def main() -> int:
    test_gesture_confinement()
    test_music_spectrum()
    test_kick_stacking()
    test_legacy_mode()

    print(f"\n{'=' * 50}\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())

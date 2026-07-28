"""Tests for gesture/action names mapping to Sonic Pi commands.

Script-style: run directly from backend or repository root. No Sonic Pi needed;
OSC sends are captured by monkeypatching SonicPiOscAdapter._send.
"""

from __future__ import annotations

import time

import sonic_pi
import state
from gesture_mapping import map_gesture_label


def main() -> None:
    adapter = sonic_pi.sonic_pi_adapter
    original_send = adapter._send
    original_live_state = sonic_pi.live_state
    sent: list[tuple[str, tuple]] = []

    def fake_send(path: str, *args) -> bool:
        sent.append((path, args))
        return True

    sonic_pi.live_state = state.LiveState()
    adapter._send = fake_send
    adapter._last_pong_at = time.time()
    try:
        assert adapter.send_gesture_command("start") is True
        assert sent[-1][0] == "/conductor/transport"
        assert sent[-1][1][1] == "start"
        music = sonic_pi.live_state.get_music()
        assert music["playing"] is True and music["current_gesture"] == "start"

        assert adapter.send_gesture_command("stop") is True
        assert sent[-1][0] == "/conductor/transport"
        assert sent[-1][1][1] == "stop"
        music = sonic_pi.live_state.get_music()
        assert music["playing"] is False and music["current_gesture"] == "stop"

        assert adapter.send_gesture_command("bpm_up") is True
        assert sent[-1][0] == "/conductor/bpm"
        assert sent[-1][1][1] == 104.0
        assert sonic_pi.live_state.get_music()["bpm"] == 104

        assert adapter.send_gesture_command("tempo_down") is True
        assert sent[-1][0] == "/conductor/bpm"
        assert sent[-1][1][1] == 96.0
        assert sonic_pi.live_state.get_music()["bpm"] == 96

        assert adapter.send_gesture_command("vol_up") is True
        assert sent[-1][0] == "/conductor/volume"
        assert round(sent[-1][1][1], 2) == 0.86
        assert sonic_pi.live_state.get_music()["volume"] == 0.86

        assert adapter.send_gesture_command("decrescendo") is True
        assert sent[-1][0] == "/conductor/volume"
        assert round(sent[-1][1][1], 2) == 0.8
        assert sonic_pi.live_state.get_music()["volume"] == 0.8

        assert adapter.send_gesture_command("style", {"direction": "next"}) is True
        assert sent[-1][0] == "/conductor/style"
        assert sent[-1][1][1] == "next"
        assert sonic_pi.live_state.get_music()["style"] == "tropical_house"

        assert adapter.send_gesture_command("zone_off", {"layer": "drums", "enabled": False}) is True
        assert sent[-1][0] == "/conductor/layer"
        assert sent[-1][1][1:] == ("drums", 0.0)
        assert sonic_pi.live_state.get_music()["layers"]["drums"] is False

        sonic_pi.live_state = state.LiveState()
        sent.clear()
        sonic_pi.live_state.set_music_bpm(104)
        adapter.publish_prediction({"gesture": "tempo_up", "confidence": 0.9}, sonic_pi.live_state.get_music())
        assert sent[-1][0] == "/conductor/bpm"
        assert sent[-1][1][1] == 104.0

        sent.clear()
        sonic_pi.live_state.set_music_volume(0.72)
        adapter.publish_prediction({"gesture": "crescendo", "confidence": 0.9}, sonic_pi.live_state.get_music())
        assert sent[-1][0] == "/conductor/volume"
        assert sent[-1][1][1] == 0.72

        sent.clear()
        adapter.publish_control_event({"event": {"type": "style_switch"}}, sonic_pi.live_state.get_music())
        assert sent[-1][0] == "/conductor/style"
        assert sent[-1][1][1] == "next"
        sent.clear()
        adapter.publish_control_event(
            {
                "event": {"type": "right_wrist_strike", "confidence": 0.9, "strength": 0.9},
                "music_control": {"estimated_bpm": 118, "volume": 0.7, "intensity": 0.8},
            },
            sonic_pi.live_state.get_music(),
        )
        assert [item[0] for item in sent] == [
            "/conductor/transport",
            "/conductor/state",
            "/conductor/accent",
        ], sent
        assert sent[0][1][1] == "start"
        assert sent[1][1][1] == 118.0
        assert sent[2][1][2] == "right_wrist_strike"

        sonic_pi.live_state = state.LiveState()
        adapter._last_pong_at = None
        sent.clear()
        assert adapter.send_gesture_command("start") is True
        assert sent[-1][0] == "/conductor/transport"
        assert sent[-1][1][1] == "start"
        music = sonic_pi.live_state.get_music()
        assert music["playing"] is False
        assert music["current_gesture"] == "idle"
        assert "command channel is not ready" in adapter.status()["last_error"]
        assert map_gesture_label("volume_up") == "vol_up"
        assert map_gesture_label("speed_down") == "tempo_down"
        assert map_gesture_label("style_next") == "style_switch"
        print("All gesture music command tests passed.")
    finally:
        adapter._send = original_send
        sonic_pi.live_state = original_live_state


if __name__ == "__main__":
    main()
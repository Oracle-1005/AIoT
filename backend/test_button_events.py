"""Tests for micro:bit button (control_event) handling fixes.

Covers:
  1. state.apply_control_event: style_switch actually cycles music style.
  2. sonic_pi.send_state_from_music: style rides /conductor/state as the
     12th (appended, backward-compatible) OSC arg.
  3. message_router: button events emit LED feedback downlink with the
     designed effect mapping; unknown gestures / disabled switch stay silent.
  4. route_uplink_message full control_event path wires the LED feedback.

Script-style (same convention as test_led_auto.py): run directly.
"""

from __future__ import annotations

import time

import message_router
import sonic_pi
import state


def _control_payload(gesture: str) -> dict:
    return {
        "event": {"type": gesture, "source": "microbit_left", "strength": 1.0},
        "music_control": {},
    }


def main() -> None:
    # 1. style_switch 真循环风格（此前是空操作，只改 current_gesture）
    ls = state.LiveState()
    seen = []
    for _ in range(4):
        ls.apply_control_event(_control_payload("style_switch"), time.time())
        seen.append(ls.get_music()["style"])
    assert seen == ["tropical_house", "festival_edm", "acoustic_pop", "tropical_house"], seen
    assert ls.get_music()["current_gesture"] == "style_switch"
    print("PASS 1 style_switch button cycles single-song styles")

    # 1b. 其他按键语义不受影响
    ls2 = state.LiveState()
    ls2.apply_control_event(_control_payload("stop"), time.time())
    assert ls2.get_music()["playing"] is False
    ls2.apply_control_event(_control_payload("resume"), time.time())
    assert ls2.get_music()["playing"] is True
    print("PASS 1b stop/resume 语义不变")

    # 2. /conductor/state 第 12 参带 style
    sent: list[tuple] = []
    original_send = sonic_pi.sonic_pi_adapter._send
    sonic_pi.sonic_pi_adapter._send = lambda path, *args: sent.append((path, args)) or True
    try:
        sonic_pi.sonic_pi_adapter.send_state_from_music(
            {"bpm": 108, "volume": 0.8, "energy": 0.6, "style": "brass"}, {}
        )
        assert sent[-1][0] == "/conductor/state"
        assert sent[-1][1][-1] == "brass", sent[-1][1]
        assert len(sent[-1][1]) == 12, len(sent[-1][1])
        # 无 style 时默认 piano
        sonic_pi.sonic_pi_adapter.send_state_from_music({"bpm": 108}, {})
        assert sent[-1][1][-1] == "piano"
        # overrides 优先
        sonic_pi.sonic_pi_adapter.send_state_from_music(
            {"style": "piano"}, {"style": "strings"}
        )
        assert sent[-1][1][-1] == "strings"
    finally:
        sonic_pi.sonic_pi_adapter._send = original_send
    print("PASS 2 /conductor/state 追加 style 第 12 参")

    # 3. 按键 → LED 下行映射
    led_calls: list[tuple[str, dict]] = []
    original_route_send = message_router.send_pi_command
    message_router.send_pi_command = lambda mt, p, **k: led_calls.append((mt, p)) or True
    original_enabled = message_router.CONTROL_EVENT_LED_ENABLED
    try:
        message_router.CONTROL_EVENT_LED_ENABLED = True
        expected = {
            "resume": "gesture_start",
            "cutoff": "off",
            "stop": "stop",
            "style_switch": "wave",
            "gesture_start": "gesture_start",
        }
        for gesture, effect in expected.items():
            led_calls.clear()
            message_router._maybe_send_control_event_led(_control_payload(gesture))
            assert len(led_calls) == 1, (gesture, led_calls)
            mt, payload = led_calls[0]
            assert mt == "led_command"
            assert payload["effect"] == effect, (gesture, payload)
            assert 0.0 <= payload["brightness"] <= 1.0
            assert payload["duration_ms"] >= 0
        print("PASS 3 五个按键各映射到设计的 LED 反馈")

        # 3b. 无 LED 语义的手势 / 畸形 payload 静默
        led_calls.clear()
        message_router._maybe_send_control_event_led(_control_payload("downbeat"))
        message_router._maybe_send_control_event_led({"music_control": {}})
        message_router._maybe_send_control_event_led({"event": "bad"})
        assert led_calls == []
        print("PASS 3b 无 LED 语义事件静默")

        # 3c. 开关关闭不发
        message_router.CONTROL_EVENT_LED_ENABLED = False
        led_calls.clear()
        message_router._maybe_send_control_event_led(_control_payload("stop"))
        assert led_calls == []
        print("PASS 3c AIOT_BUTTON_LED_ENABLED=0 关闭")
    finally:
        message_router.send_pi_command = original_route_send
        message_router.CONTROL_EVENT_LED_ENABLED = original_enabled

    # 4. route_uplink_message 全链路：control_event 触发 LED 反馈
    led_calls2: list[tuple[str, dict]] = []
    original_insert = message_router.insert_pi_message
    original_record = message_router.live_state.record_pi_message
    original_apply = message_router.live_state.apply_control_event
    original_publish = message_router.sonic_pi_adapter.publish_control_event
    original_send2 = message_router.send_pi_command
    message_router.insert_pi_message = lambda *a, **k: None
    message_router.live_state.record_pi_message = lambda *a, **k: None
    message_router.live_state.apply_control_event = lambda *a, **k: None
    message_router.sonic_pi_adapter.publish_control_event = lambda *a, **k: None
    message_router.send_pi_command = lambda mt, p, **k: led_calls2.append((mt, p)) or True
    try:
        message_router.route_uplink_message(
            {
                "message_type": "control_event",
                "payload": _control_payload("style_switch"),
            },
            ("127.0.0.1", 9999),
        )
        assert len(led_calls2) == 1 and led_calls2[0][1]["effect"] == "wave", led_calls2
    finally:
        message_router.insert_pi_message = original_insert
        message_router.live_state.record_pi_message = original_record
        message_router.live_state.apply_control_event = original_apply
        message_router.sonic_pi_adapter.publish_control_event = original_publish
        message_router.send_pi_command = original_send2
    print("PASS 4 route_uplink_message 全链路按键 → LED")

    print("\nAll button-event tests passed.")


if __name__ == "__main__":
    main()

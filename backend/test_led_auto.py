"""Tests for the auto led_command wiring in integration._maybe_send_led.

Script-style (same convention as test_backend.py): run directly.
All tests monkeypatch integration.send_pi_command — no Pi needed.
"""

from __future__ import annotations

import time

import integration


def _capture():
    calls: list[tuple[str, dict]] = []

    def fake_send(message_type: str, payload: dict, **metadata):
        calls.append((message_type, payload))
        return True

    return calls, fake_send


def _capture_offline():
    calls: list[tuple[str, dict]] = []

    def fake_send(message_type: str, payload: dict, **metadata):
        calls.append((message_type, payload))
        return False  # Pi 离线

    return calls, fake_send


def _reset_auto():
    integration._led_auto_last["at"] = 0.0
    integration._led_auto_last["gesture"] = None


def _result(gesture: str, confidence: float) -> dict:
    return {
        "gesture": gesture,
        "confidence": confidence,
        "gesture_id": 1,
        "timestamp": time.time(),
        "features_used": 2,
        "all_probs": {gesture: confidence},
    }


def main() -> None:
    original_send = integration.send_pi_command
    original_enabled = integration.LED_AUTO_ENABLED
    original_min_conf = integration.LED_AUTO_MIN_CONFIDENCE
    original_cooldown = integration.LED_AUTO_COOLDOWN_S
    original_preempt = integration.LED_AUTO_PREEMPT_MIN_S
    try:
        # 1. 默认关闭：任何预测都不发
        integration.LED_AUTO_ENABLED = False
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.95)) is False
        assert calls == []
        print("PASS 1 默认关闭不发")

        integration.LED_AUTO_ENABLED = True
        integration.LED_AUTO_MIN_CONFIDENCE = 0.6
        integration.LED_AUTO_COOLDOWN_S = 1.0
        integration.LED_AUTO_PREEMPT_MIN_S = 0.5

        # 2. 达标预测 → 发出契约格式 led_command
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is True
        assert len(calls) == 1
        message_type, payload = calls[0]
        assert message_type == "led_command"
        assert payload["effect"] == "downbeat"
        assert 0.0 <= payload["brightness"] <= 1.0
        assert payload["duration_ms"] >= 0
        assert payload["source"] == "backend-auto"
        print("PASS 2 达标预测发出契约 led_command")

        # 3. idle 被跳过
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("idle", 0.99)) is False
        assert calls == []
        print("PASS 3 idle 跳过")

        # 4. 低置信度被跳过
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("upbeat", 0.3)) is False
        assert calls == []
        print("PASS 4 低置信度跳过")

        # 5. 同一手势：冷却窗口内重复被抑制；冷却过后放行
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is True
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is False
        assert len(calls) == 1
        integration._led_auto_last["at"] -= integration.LED_AUTO_COOLDOWN_S + 1
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is True
        assert len(calls) == 2
        print("PASS 5 同手势冷却抑制 + 冷却结束放行")

        # 6. Pi 离线（send=False）不占用冷却，下个周期自动重试
        calls, fake = _capture_offline()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is False
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is False
        assert len(calls) == 2  # 两次都尝试了（未冷却）
        print("PASS 6 离线不占用冷却")

        # 7. accept_prediction 全链路：LED 失败不影响既有的落库/状态/OSC
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        original_insert = integration.insert_prediction
        original_set = integration.live_state.set_prediction
        original_publish = integration.sonic_pi_adapter.publish_prediction
        integration.insert_prediction = lambda *a, **k: None
        integration.live_state.set_prediction = lambda *a, **k: None
        integration.sonic_pi_adapter.publish_prediction = lambda *a, **k: None
        try:
            integration.accept_prediction(_result("left_cue", 0.88))
        finally:
            integration.insert_prediction = original_insert
            integration.live_state.set_prediction = original_set
            integration.sonic_pi_adapter.publish_prediction = original_publish
        assert len(calls) == 1 and calls[0][1]["effect"] == "left_cue"
        print("PASS 7 accept_prediction 全链路联动")

        # 8. 非字符串/缺失 gesture 不炸
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led({"confidence": 0.9}) is False
        assert integration._maybe_send_led(_result("downbeat", 0.9) | {"confidence": "bad"}) is False
        assert calls == []
        print("PASS 8 畸形输入静默跳过")

        # 9. 不同手势：PREEMPT_MIN 后立即打断（不受同手势冷却约束）
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is True
        # 0.6s 后（> PREEMPT_MIN 0.5，< COOLDOWN 1.0）换手势 → 立即抢占
        integration._led_auto_last["at"] = time.time() - 0.6
        assert integration._maybe_send_led(_result("upbeat", 0.9)) is True
        assert len(calls) == 2
        assert calls[1][1]["effect"] == "upbeat"
        print("PASS 9 不同手势冷却期内立即打断")

        # 10. 不同手势：PREEMPT_MIN 内仍被抑制（防频闪下限）
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is True
        integration._led_auto_last["at"] = time.time() - 0.2  # < PREEMPT_MIN
        assert integration._maybe_send_led(_result("upbeat", 0.9)) is False
        assert len(calls) == 1
        print("PASS 10 打断下限内换手势仍抑制")

        # 11. 打断后新手势占用自己的冷却：立刻重复新手势被抑制
        calls, fake = _capture()
        integration.send_pi_command = fake
        _reset_auto()
        assert integration._maybe_send_led(_result("downbeat", 0.9)) is True
        integration._led_auto_last["at"] = time.time() - 0.6
        assert integration._maybe_send_led(_result("upbeat", 0.9)) is True
        assert integration._maybe_send_led(_result("upbeat", 0.9)) is False  # 同手势冷却
        assert len(calls) == 2
        print("PASS 11 打断后同手势冷却独立生效")

        # 12. per-gesture 门槛：gesture_start 单独抬高，其他手势不受影响
        original_map = integration.LED_AUTO_GESTURE_MIN
        integration.LED_AUTO_GESTURE_MIN = {"gesture_start": 0.75}
        try:
            calls, fake = _capture()
            integration.send_pi_command = fake
            _reset_auto()
            assert integration._maybe_send_led(_result("gesture_start", 0.7)) is False
            assert integration._maybe_send_led(_result("gesture_start", 0.8)) is True
            _reset_auto()
            assert integration._maybe_send_led(_result("downbeat", 0.65)) is True
        finally:
            integration.LED_AUTO_GESTURE_MIN = original_map
        print("PASS 12 gesture_start 单独置信度门槛")
    finally:
        integration.send_pi_command = original_send
        integration.LED_AUTO_ENABLED = original_enabled
        integration.LED_AUTO_MIN_CONFIDENCE = original_min_conf
        integration.LED_AUTO_COOLDOWN_S = original_cooldown
        integration.LED_AUTO_PREEMPT_MIN_S = original_preempt
        _reset_auto()

    print("\nAll auto-LED tests passed.")


if __name__ == "__main__":
    main()

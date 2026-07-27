"""Tests for the auto music (OSC) throttling in integration._maybe_publish_music.

Script-style (same convention as test_led_auto.py): run directly.
publish_prediction / set_prediction are monkeypatched — no Sonic Pi needed.
"""

from __future__ import annotations

import time

import integration


def _capture():
    calls: list[dict] = []

    def fake_publish(result: dict, music_state: dict) -> None:
        calls.append(result)

    return calls, fake_publish


def _reset_auto():
    integration._music_auto_last["at"] = 0.0
    integration._music_auto_last["gesture"] = None


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
    original_publish = integration.sonic_pi_adapter.publish_prediction
    original_enabled = integration.MUSIC_AUTO_ENABLED
    original_min_conf = integration.MUSIC_AUTO_MIN_CONFIDENCE
    original_cooldown = integration.MUSIC_AUTO_EVENT_COOLDOWN_S
    original_preempt = integration.MUSIC_AUTO_PREEMPT_MIN_S
    original_rate = integration.MUSIC_AUTO_CONT_RATE_S
    try:
        integration.MUSIC_AUTO_MIN_CONFIDENCE = 0.6
        integration.MUSIC_AUTO_EVENT_COOLDOWN_S = 1.0
        integration.MUSIC_AUTO_PREEMPT_MIN_S = 0.5
        integration.MUSIC_AUTO_CONT_RATE_S = 0.5

        # 1. 关闭：任何预测都不推 OSC
        integration.MUSIC_AUTO_ENABLED = False
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("downbeat", 0.95)) is False
        assert calls == []
        print("PASS 1 关闭不推 OSC")

        integration.MUSIC_AUTO_ENABLED = True

        # 2. 达标事件手势 → 推 OSC
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("downbeat", 0.9)) is True
        assert len(calls) == 1 and calls[0]["gesture"] == "downbeat"
        print("PASS 2 达标预测推 OSC")

        # 3. idle 跳过
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("idle", 0.99)) is False
        assert calls == []
        print("PASS 3 idle 跳过")

        # 4. 低置信度跳过
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("upbeat", 0.3)) is False
        assert calls == []
        print("PASS 4 低置信度跳过")

        # 5. 事件手势：同手势冷却内连发被抑制（"响个不停"场景），冷却结束放行
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("downbeat", 0.9)) is True
        for _ in range(9):  # 模拟 10 次/秒预测连发
            assert integration._maybe_publish_music(_result("downbeat", 0.9)) is False
        assert len(calls) == 1
        integration._music_auto_last["at"] -= integration.MUSIC_AUTO_EVENT_COOLDOWN_S + 1
        assert integration._maybe_publish_music(_result("downbeat", 0.9)) is True
        assert len(calls) == 2
        print("PASS 5 事件手势冷却抑制连发 + 冷却结束放行")

        # 6. 连续类手势（渐弱）：按 CONT_RATE_S 限速（比事件冷却快），形成斜坡
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("decrescendo", 0.9)) is True
        assert integration._maybe_publish_music(_result("decrescendo", 0.9)) is False
        assert len(calls) == 1
        # 0.6s 后（> CONT_RATE 0.5，< EVENT_COOLDOWN 1.0）→ 连续类放行
        integration._music_auto_last["at"] = time.time() - 0.6
        assert integration._maybe_publish_music(_result("decrescendo", 0.9)) is True
        assert len(calls) == 2
        print("PASS 6 连续类手势限速斜坡（0.5s/次）")

        # 7. 不同手势：PREEMPT_MIN 后立即打断
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("decrescendo", 0.9)) is True
        integration._music_auto_last["at"] = time.time() - 0.6
        assert integration._maybe_publish_music(_result("downbeat", 0.9)) is True
        assert len(calls) == 2 and calls[1]["gesture"] == "downbeat"
        print("PASS 7 不同手势冷却期内立即打断")

        # 8. 不同手势：PREEMPT_MIN 内仍被抑制
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music(_result("downbeat", 0.9)) is True
        integration._music_auto_last["at"] = time.time() - 0.2
        assert integration._maybe_publish_music(_result("upbeat", 0.9)) is False
        assert len(calls) == 1
        print("PASS 8 打断下限内换手势仍抑制")

        # 9. 畸形输入静默跳过
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        assert integration._maybe_publish_music({"confidence": 0.9}) is False
        assert integration._maybe_publish_music(_result("downbeat", 0.9) | {"confidence": "bad"}) is False
        assert calls == []
        print("PASS 9 畸形输入静默跳过")

        # 10. accept_prediction 全链路：过节流才应用音乐副作用
        set_calls: list[tuple[dict, bool]] = []
        original_insert = integration.insert_prediction
        original_set = integration.live_state.set_prediction
        integration.insert_prediction = lambda *a, **k: None
        integration.live_state.set_prediction = (
            lambda result, apply_music=True: set_calls.append((result, apply_music))
        )
        calls, fake = _capture()
        integration.sonic_pi_adapter.publish_prediction = fake
        _reset_auto()
        try:
            integration.accept_prediction(_result("downbeat", 0.9))   # 过节流
            integration.accept_prediction(_result("downbeat", 0.9))   # 冷却内
            integration.accept_prediction(_result("idle", 0.99))      # 跳过
        finally:
            integration.insert_prediction = original_insert
            integration.live_state.set_prediction = original_set
        assert set_calls[0][1] is False, f"first call apply_music: {set_calls}"
        assert all(c[1] is False for c in set_calls[1:]), f"later calls: {set_calls}"
        assert len(calls) == 1
        print("PASS 10 accept_prediction 仅过节流时应用音乐副作用")

        # 11. per-gesture 门槛：gesture_start 单独抬高（防右拳误触发），其他手势不受影响
        original_map = integration.MUSIC_AUTO_GESTURE_MIN
        integration.MUSIC_AUTO_GESTURE_MIN = {"gesture_start": 0.8}
        try:
            calls, fake = _capture()
            integration.sonic_pi_adapter.publish_prediction = fake
            _reset_auto()
            assert integration._maybe_publish_music(_result("gesture_start", 0.7)) is False
            assert integration._maybe_publish_music(_result("gesture_start", 0.85)) is True
            _reset_auto()
            assert integration._maybe_publish_music(_result("downbeat", 0.65)) is True
        finally:
            integration.MUSIC_AUTO_GESTURE_MIN = original_map
        print("PASS 11 gesture_start 单独置信度门槛")

        # 12. 门槛映射解析器：畸形项静默丢弃、数值钳到 0..1
        parsed = integration._parse_gesture_min_map("gesture_start:0.8, bad, x:abc, up:1.5, low:-0.2")
        assert parsed == {"gesture_start": 0.8, "up": 1.0, "low": 0.0}, parsed
        assert integration._parse_gesture_min_map("") == {}
        print("PASS 12 门槛映射解析器健壮性")
    finally:
        integration.sonic_pi_adapter.publish_prediction = original_publish
        integration.MUSIC_AUTO_ENABLED = original_enabled
        integration.MUSIC_AUTO_MIN_CONFIDENCE = original_min_conf
        integration.MUSIC_AUTO_EVENT_COOLDOWN_S = original_cooldown
        integration.MUSIC_AUTO_PREEMPT_MIN_S = original_preempt
        integration.MUSIC_AUTO_CONT_RATE_S = original_rate
        _reset_auto()

    print("\nAll auto-music tests passed.")


if __name__ == "__main__":
    main()

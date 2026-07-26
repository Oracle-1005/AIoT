"""Tests for hard layer gating (New World zone-conducting demo).

Covers:
  1. state: layers default all-on, set_music_layer valid/invalid.
  2. state: apply_sonic_pi_layers coerces rb's 0/1 feedback (rb authoritative).
  3. sonic_pi.send_layer OSC payload (/conductor/layer command_id layer 0|1).
  4. sonic_pi._handle_layers syncs state.
  5. POST /api/music/layers endpoint: 200/400/503 paths.
  6. new_world is the default track and its metadata matches the rb script.

Script-style (same convention as test_button_events.py): run directly.
"""

from __future__ import annotations

import time

import app as app_module
import sonic_pi
import state


def main() -> None:
    # 1. layers 默认全开；set_music_layer 有效/无效
    ls = state.LiveState()
    assert ls.get_music()["layers"] == {
        "melody": True, "harmony": True, "bass": True, "drums": True,
    }, ls.get_music()["layers"]
    assert ls.set_music_layer("drums", False) is True
    assert ls.get_music()["layers"]["drums"] is False
    assert ls.get_music()["layers"]["melody"] is True  # 其他不受影响
    assert ls.set_music_layer("violas", True) is False
    print("PASS 1 layers 默认全开 + set_music_layer 校验")

    # 2. rb 反馈 0/1 强转为 bool（rb 为准）
    ls.apply_sonic_pi_layers(melody=1, harmony=0, bass=1.0, drums=0.0,
                             received_at=time.time())
    assert ls.get_music()["layers"] == {
        "melody": True, "harmony": False, "bass": True, "drums": False,
    }, ls.get_music()["layers"]
    print("PASS 2 apply_sonic_pi_layers 反馈同步")

    # 3. send_layer OSC 报文
    sent: list[tuple] = []
    original_send = sonic_pi.sonic_pi_adapter._send
    sonic_pi.sonic_pi_adapter._send = lambda path, *args: sent.append((path, args)) or True
    try:
        sonic_pi.sonic_pi_adapter.send_layer("drums", False)
        path, args = sent[-1]
        assert path == "/conductor/layer", path
        assert args[1] == "drums" and args[2] == 0.0, args
        sonic_pi.sonic_pi_adapter.send_layer("melody", True)
        assert sent[-1][1][2] == 1.0
    finally:
        sonic_pi.sonic_pi_adapter._send = original_send
    print("PASS 3 send_layer OSC 报文格式")

    # 4. _handle_layers → state 同步（用独立 LiveState 替身避免污染单例）
    ls2 = state.LiveState()
    original_live_state = sonic_pi.live_state
    sonic_pi.live_state = ls2
    try:
        sonic_pi.sonic_pi_adapter._handle_layers("/music/layers", 0, 1, 1, 0)
    finally:
        sonic_pi.live_state = original_live_state
    assert ls2.get_music()["layers"] == {
        "melody": False, "harmony": True, "bass": True, "drums": False,
    }, ls2.get_music()["layers"]
    print("PASS 4 _handle_layers 同步 rb 门状态")

    # 5. /api/music/layers 端点
    flask_app = app_module.create_app()
    client = flask_app.test_client()
    sent2: list[tuple] = []
    original_send2 = sonic_pi.sonic_pi_adapter.send_layer
    sonic_pi.sonic_pi_adapter.send_layer = (
        lambda layer, enabled: sent2.append((layer, enabled)) or True
    )
    try:
        resp = client.post("/api/music/layers",
                           json={"layer": "harmony", "enabled": False})
        assert resp.status_code == 200, resp.status_code
        body = resp.get_json()
        assert body["sent"] is True
        assert body["layers"]["harmony"] is False
        assert sent2 == [("harmony", False)], sent2

        resp = client.post("/api/music/layers",
                           json={"layer": "violas", "enabled": True})
        assert resp.status_code == 400, resp.status_code

        sonic_pi.sonic_pi_adapter.send_layer = lambda layer, enabled: False
        resp = client.post("/api/music/layers",
                           json={"layer": "bass", "enabled": True})
        assert resp.status_code == 503, resp.status_code
    finally:
        sonic_pi.sonic_pi_adapter.send_layer = original_send2
    # 还原单例状态，避免影响其他测试
    state.live_state.set_music_layer("harmony", True)
    state.live_state.set_music_layer("bass", True)
    print("PASS 5 /api/music/layers 端点 200/400/503")

    # 6. new_world 是默认曲目且元数据与 rb 一致
    assert state.SONIC_PI_TRACK_ORDER[0] == "new_world"
    track = state.SONIC_PI_TRACKS["new_world"]
    assert track["key"] == "E Minor" and track["bpm"] == 138
    assert track["total_bars"] == 8 and track["beats_per_bar"] == 4
    assert state.SONIC_PI_DEFAULT_TRACK_ID == "new_world"
    print("PASS 6 new_world 默认曲目元数据")

    print("\nAll music-layer tests passed.")


if __name__ == "__main__":
    main()

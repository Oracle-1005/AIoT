"""Tests for the rule-based coordinate gesture recognizer.

Covers (design: session-summary 8.0-8.3):
  1. hand classification: fist/palm via openness EMA + finger_states vote
  2. right fist held -> start, once per appearance (re-arm on release)
  3. left fist held -> stop; left fist push-up -> bpm_up instead of stop
  4. right fist push-down -> bpm_down (repeat while held)
  5. single palm pushes -> volume up/down
  6. two palms in same band -> zone_on (layer enable), dead-zone re-arm
  7. two fists in same band -> zone_off; height separation -> style prev/next
  8. style gesture suppresses zone_off (no double action)
  9. swap_hands mirrors left/right
 10. brief detection gaps do not reset sustain counters
 11. disabled recognizer is inert

Script-style (same convention as test_music_layers.py): run directly.
"""

from __future__ import annotations

import coordinate_recognizer as cr

DT = 1.0 / 16.0   # 实测帧率 ~16Hz


def make_frame(hands: list[dict], *, anchor: object = True) -> dict:
    frame = {"camera": {"hands": hands}}
    if anchor is True:
        # micro:bit 锚点（门控默认开）：测试帧默认带双侧活性锚点。
        # 用线上真实形状：microbits 为列表，available 由 Pi 端对齐器判定。
        frame["microbits"] = [
            {"hand": "left", "available": True, "time_delta_ms": 12.3},
            {"hand": "right", "available": True, "time_delta_ms": 15.1},
        ]
    elif anchor == "stale":
        frame["microbits"] = [
            {"hand": "left", "available": False, "time_delta_ms": 9000.0},
            {"hand": "right", "available": False, "time_delta_ms": 9000.0},
        ]
    elif anchor == "dict-live":
        # 向后兼容：status 消息式字典形态（age_ms < 阈值 = 活）
        frame["microbits"] = {
            "left": {"age_ms": 50}, "right": {"age_ms": 50},
        }
    elif anchor == "dict-stale":
        frame["microbits"] = {
            "left": {"age_ms": 9000}, "right": {"age_ms": 9000},
        }
    return frame


def hand(
    side: str,
    *,
    openness: float,
    y: float = 0.5,
    vy: float = 0.0,
    extended: int | None = None,
) -> dict:
    if extended is None:
        extended = 0 if openness < 0.4 else 5
    return {
        "hand_id": side,
        "handedness": side,
        "features": {
            "openness": openness,
            "finger_states": [1] * extended + [0] * (5 - extended),
            "wrist_position": [0.5, y, 0.0],
            "wrist_velocity": [0.0, vy, 0.0],
        },
    }


def fist(side: str, y: float = 0.5, vy: float = 0.0) -> dict:
    return hand(side, openness=0.1, y=y, vy=vy)


def palm(side: str, y: float = 0.5, vy: float = 0.0) -> dict:
    return hand(side, openness=0.9, y=y, vy=vy)


class Rig:
    """识别器 + 动作收集 + 假时钟。"""

    def __init__(self, **kwargs) -> None:
        self.events: list[tuple[str, dict]] = []
        self.rec = cr.CoordinateRecognizer(
            action_sink=lambda name, detail: self.events.append((name, detail)),
            **kwargs,
        )
        self.t = 1000.0

    def feed(self, frames: list[dict], count: int = 1, *, anchor: object = True) -> None:
        for _ in range(count):
            self.t += DT
            self.rec.process_frame(make_frame(frames, anchor=anchor), self.t)

    def feed_motion(
        self,
        maker,
        side: str,
        *,
        start_y: float,
        step_y: float,
        vy: float,
        count: int,
        anchor: object = True,
    ) -> None:
        for index in range(count):
            self.feed([maker(side, y=start_y + step_y * index, vy=vy)], 1, anchor=anchor)

    def names(self) -> list[str]:
        return [name for name, _ in self.events]

    def introduce(self, side: str, count: int = 3) -> None:
        """先以掌出现 N 帧——满足"握拳必须有握的过程"(seen_palm)。"""
        self.feed([palm(side)], count)


def main() -> None:
    # 1. 手型分类：拳/掌 + 迟滞
    rig = Rig()
    rig.feed([fist("left")], 3)
    left = rig.rec._hands["left"]
    assert left.label == "fist", left.label
    rig.feed([palm("left")], 3)
    assert left.label == "palm", left.label
    # 中间值（证据不足）保持上次手型
    rig.feed([hand("left", openness=0.48, extended=2)], 3)
    assert left.label == "palm", left.label
    print("PASS 1 手型分类（拳/掌/迟滞）")

    # 2. 右拳静置 -> start，每拳一次，松开后重新武装
    rig = Rig()
    rig.introduce("right")
    rig.feed([fist("right")], 1)                  # 手型迟滞过渡帧
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT - 1)
    assert rig.events == [], rig.events
    rig.feed([fist("right")], 1)
    assert rig.names() == ["start"], rig.events
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 5)
    assert rig.names() == ["start"], rig.events   # 不重复
    rig.feed([], cr.REARM_FRAMES + 2)             # 手离开 -> re-arm（再现需重新见掌）
    rig.introduce("right")
    rig.feed([fist("right")], 1)
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT)
    assert rig.names() == ["start", "start"], rig.events
    print("PASS 2 右拳=start（边沿一次 + re-arm）")

    # 3. 左拳静置 -> stop；左拳上推 -> bpm_up 且 stop 不触发
    rig = Rig()
    rig.introduce("left")
    rig.feed([fist("left")], 2)
    rig.feed([fist("left")], cr.HOLD_FRAMES_TRANSPORT)
    assert rig.names() == ["stop"], rig.events
    rig2 = Rig()
    rig2.introduce("left")
    rig2.feed([fist("left")], 3)                  # 先静置 3 帧
    rig2.feed_motion(fist, "left", start_y=0.50, step_y=-0.025, vy=-0.8, count=cr.HOLD_FRAMES_PUSH + 5)
    assert "bpm_up" in rig2.names(), rig2.events
    assert "stop" not in rig2.names(), rig2.events
    print("PASS 3 左拳=stop / 左拳上推=BPM+（互斥正确）")

    # 4. 右拳下推 -> bpm_down 持续重复
    rig = Rig()
    rig.introduce("right")
    rig.feed_motion(fist, "right", start_y=0.50, step_y=0.025, vy=0.8, count=cr.HOLD_FRAMES_PUSH + 5)
    assert rig.names() == ["bpm_down"], rig.events
    # 继续按住：不到重复间隔不再发，超过 0.45s 后再发
    rig.feed_motion(fist, "right", start_y=0.72, step_y=0.025, vy=0.8, count=3)          # ~0.19s
    assert rig.names() == ["bpm_down"], rig.events
    rig.feed_motion(fist, "right", start_y=0.80, step_y=0.025, vy=0.8, count=8)          # 累计 ~0.56s
    assert rig.names().count("bpm_down") == 2, rig.events
    assert "start" not in rig.names(), rig.events
    print("PASS 4 右拳下推=BPM-（按住重复）")

    # 5. 单掌推音量：左掌上推 vol_up / 右掌下推 vol_down；静置不发
    rig = Rig()
    rig.feed_motion(palm, "left", start_y=0.50, step_y=-0.025, vy=-0.8, count=cr.HOLD_FRAMES_PUSH + 5)
    assert rig.names() == ["vol_up"], rig.events
    rig.feed([palm("left", vy=0.0)], cr.HOLD_FRAMES_PUSH + 3)
    assert rig.names() == ["vol_up"], rig.events   # 静置不重复
    rig2 = Rig()
    rig2.feed_motion(palm, "right", start_y=0.50, step_y=0.025, vy=0.8, count=cr.HOLD_FRAMES_PUSH + 5)
    assert rig2.names() == ["vol_down"], rig2.events
    print("PASS 5 单掌推=音量±（静置不误触）")

    # 6. 双手掌同带 -> 开声部；死区重新武装
    rig = Rig()
    rig.feed([palm("left", y=0.10), palm("right", y=0.12)],
             cr.HOLD_FRAMES_ZONE - 1)
    assert rig.events == [], rig.events
    rig.feed([palm("left", y=0.10), palm("right", y=0.12)], 1)
    assert rig.events == [("zone_on", {"layer": "melody", "enabled": True})], \
        rig.events
    rig.feed([palm("left", y=0.10), palm("right", y=0.12)],
             cr.HOLD_FRAMES_ZONE + 3)
    assert len(rig.events) == 1, rig.events        # 同带不重复
    rig.feed([palm("left", y=0.25), palm("right", y=0.25)], 4)   # 死区 re-arm（EMA 收敛）
    rig.feed([palm("left", y=0.60), palm("right", y=0.62)],
             cr.HOLD_FRAMES_ZONE + 4)              # 换带 + EMA 收敛
    assert rig.events[-1] == ("zone_on", {"layer": "bass", "enabled": True}), \
        rig.events
    print("PASS 6 双手掌同带=开声部（Z1=melody Z3=bass，死区 re-arm）")

    # 7. 双手拳同带 -> 关声部；异带且高度差小 -> 无动作
    rig = Rig()
    rig.feed([palm("left"), palm("right")], 3)
    rig.feed([fist("left", y=0.82), fist("right", y=0.85)], 1)
    rig.feed([fist("left", y=0.82), fist("right", y=0.85)],
             cr.HOLD_FRAMES_ZONE + 2)   # +2：手型迟滞 + y-EMA 收敛
    assert rig.events == [("zone_off", {"layer": "drums", "enabled": False})], \
        rig.events
    rig2 = Rig()
    rig2.feed([palm("left"), palm("right")], 3)
    rig2.feed([fist("left", y=0.10), fist("right", y=0.35)],
             cr.HOLD_FRAMES_ZONE + 3)   # 异带但高度差 0.25 >= 风格阈值 -> 风格
    assert ("zone_off", {"layer": "melody", "enabled": False}) not in rig2.events
    print("PASS 7 双手拳同带=关声部（Z4=drums）")

    # 8. 双手拳高度差 -> 风格：左高=previous 右高=next；不误触区域关
    rig = Rig()
    rig.feed([palm("left"), palm("right")], 3)
    rig.feed([fist("left", y=0.15), fist("right", y=0.55)], 1)
    rig.feed([fist("left", y=0.15), fist("right", y=0.55)],
             cr.HOLD_FRAMES_STYLE - 1)
    assert rig.events == [], rig.events
    rig.feed([fist("left", y=0.15), fist("right", y=0.55)], 1)
    assert rig.events == [("style", {"direction": "previous"})], rig.events
    rig.feed([fist("left", y=0.15), fist("right", y=0.55)],
             cr.HOLD_FRAMES_STYLE + 3)
    assert len(rig.events) == 1, rig.events        # 保持不重复
    rig.feed([fist("left", y=0.45), fist("right", y=0.50)], 10)  # 差<重置 -> re-arm + 过冷却
    rig.feed([fist("left", y=0.60), fist("right", y=0.20)],
             cr.HOLD_FRAMES_STYLE + 2)
    assert ("style", {"direction": "next"}) in rig.events, rig.events
    print("PASS 8 双手拳高度差=风格上下（左高 previous / 右高 next）")

    # 9. swap_hands：物理左拳 -> 逻辑右手 -> start（而非 stop）
    rig = Rig(swap_hands=True)
    rig.introduce("left")
    rig.feed([fist("left")], 2)
    rig.feed([fist("left")], cr.HOLD_FRAMES_TRANSPORT)
    assert rig.names() == ["start"], rig.events
    print("PASS 9 handedness swap 开关")

    # 10. 短暂缺帧（<0.30s）计数保持不重置
    rig = Rig()
    rig.introduce("right")
    rig.feed([fist("right")], 2)
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT - 2)
    rig.feed([], 2)                                # ~0.125s 缺帧 < 0.30s
    rig.feed([fist("right")], 2)
    assert rig.names() == ["start"], rig.events
    print("PASS 10 检测缺帧容缺")

    # 11. 关闭状态不动作
    rig = Rig(enabled=False)
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 5)
    assert rig.events == [], rig.events
    print("PASS 11 enabled=False 惰性")

    # 12. 区域带边界：死区内任何高度都不触发
    rig = Rig()
    rig.feed([palm("left", y=0.25), palm("right", y=0.25)],
             cr.HOLD_FRAMES_ZONE + 3)
    rig.feed([palm("left", y=0.50), palm("right", y=0.50)],
             cr.HOLD_FRAMES_ZONE + 3)
    assert rig.events == [], rig.events
    print("PASS 12 死区（带间/边界）不触发")

    # 13. micro:bit 锚点门控：无锚点/锚点过期不识别任何手势；
    #     中途丢锚点在途计数清零（恢复后不续命）；恢复后正常触发
    rig = Rig()
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 5, anchor=False)
    assert rig.events == [], rig.events
    rig2 = Rig()
    rig2.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 2, anchor="stale")
    assert rig2.events == [], rig2.events
    rig3 = Rig()
    rig3.introduce("right")
    rig3.feed([fist("right")], 1)
    rig3.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT - 1)
    rig3.feed([fist("right")], 3, anchor=False)      # 丢锚：计数清零
    rig3.feed([fist("right")], 1)                     # 恢复 1 帧不够
    assert rig3.events == [], rig3.events
    rig3.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT - 1)
    assert rig3.names() == ["start"], rig3.events
    print("PASS 13 micro:bit 锚点门控（无锚点不识别 + 丢锚不续命）")

    # 14. 锚点数据形状兼容：线上列表形态（available）与 status 字典形态
    #     （age_ms）都能正确判定活性
    rig = Rig()
    rig.introduce("right")
    rig.feed([fist("right")], 2)
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT, anchor="dict-live")
    assert rig.names() == ["start"], rig.events
    rig2 = Rig()
    rig2.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 2, anchor="dict-stale")
    assert rig2.events == [], rig2.events
    print("PASS 14 锚点形状兼容（列表 available / 字典 age_ms）")

    # 15. "握"的过程：以拳姿态直接出现不触发；掌→拳 才触发（防误入 stop）
    rig = Rig()
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 5)
    assert rig.events == [], rig.events               # 出现即拳 ≠ 握
    rig.feed([palm("right")], 3)                      # 张开=有了"握"的前提
    rig.feed([fist("right")], 2)
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT)
    assert rig.names() == ["start"], rig.events
    print("PASS 15 握拳必须有握的过程（出现即拳不触发）")

    # 16. "握"证据保质期：短暂离场（<TTL）证据保留；超 TTL 离场需重新张开
    rig = Rig()
    rig.introduce("right")
    rig.feed([], int(cr.SEEN_PALM_TTL_S * 16) - 8)    # 短暂离场 < 2s
    rig.feed([fist("right")], 1)
    rig.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT)
    assert rig.names() == ["start"], rig.events       # 证据在保质期内
    rig2 = Rig()
    rig2.introduce("right")
    rig2.feed([], int(cr.SEEN_PALM_TTL_S * 16) + 8)   # 离场 > TTL
    rig2.feed([fist("right")], cr.HOLD_FRAMES_TRANSPORT + 5)
    assert rig2.events == [], rig2.events             # 证据过期，出现即拳不触发
    print("PASS 16 seen_palm 保质期（短离场保留 / 超 TTL 过期）")

    print("\nAll coordinate_recognizer tests passed.")


if __name__ == "__main__":
    main()

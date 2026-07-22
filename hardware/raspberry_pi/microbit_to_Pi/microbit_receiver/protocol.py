"""Microbit_to_Pi_v01.md 对应的二进制协议定义与纯函数解析器。"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from enum import IntEnum
from typing import Any


# < 表示小端序；B/H/I/h 分别表示 uint8/uint16/uint32/int16。
SENSOR_STATE_STRUCT = struct.Struct("<BHIhhhhh")
CONTROL_EVENT_STRUCT = struct.Struct("<BHIBBBB")

assert SENSOR_STATE_STRUCT.size == 17
assert CONTROL_EVENT_STRUCT.size == 11


class ProtocolError(ValueError):
    """收到的 payload 不符合接口文档时抛出。"""


class MessageType(IntEnum):
    SENSOR_STATE = 1
    CONTROL_EVENT = 2


class Hand(IntEnum):
    LEFT = 0
    RIGHT = 1

    @property
    def label(self) -> str:
        return "left" if self is Hand.LEFT else "right"

    @classmethod
    def from_label(cls, label: str) -> "Hand":
        try:
            return {"left": cls.LEFT, "right": cls.RIGHT}[label.lower()]
        except KeyError as exc:
            raise ValueError("hand 必须是 'left' 或 'right'") from exc


class EventCode(IntEnum):
    A_SHORT_PRESS = 0x01
    B_SHORT_PRESS = 0x02
    B_LONG_PRESS = 0x03
    AB_LONG_PRESS = 0x04


# 文档确定的候选控制语义。键为 (hand, event_code)。
EVENT_RULES: dict[tuple[Hand, EventCode], tuple[int, str]] = {
    (Hand.LEFT, EventCode.A_SHORT_PRESS): (40, "start_or_resume"),
    (Hand.LEFT, EventCode.B_SHORT_PRESS): (60, "pause"),
    (Hand.RIGHT, EventCode.A_SHORT_PRESS): (20, "style_switch"),
    (Hand.RIGHT, EventCode.B_LONG_PRESS): (100, "emergency_stop"),
    (Hand.LEFT, EventCode.AB_LONG_PRESS): (60, "recalibrate"),
    (Hand.RIGHT, EventCode.AB_LONG_PRESS): (60, "recalibrate"),
}


def decode_header(header: int) -> tuple[MessageType, Hand]:
    """解析组合头，并拒绝非零保留位或保留消息类型。"""
    if header & 0b1111_1000:
        raise ProtocolError(f"header 保留位必须为 0，实际为 0x{header:02x}")
    try:
        message_type = MessageType(header & 0x03)
    except ValueError as exc:
        raise ProtocolError(f"不支持的 message_type: {header & 0x03}") from exc
    return message_type, Hand((header >> 2) & 0x01)


@dataclass(frozen=True, slots=True)
class SensorState:
    hand: Hand
    sample_sequence: int
    device_timestamp_ms: int
    pi_rx_monotonic_ns: int
    ax_mg: int
    ay_mg: int
    az_mg: int
    pitch_deg: int
    roll_deg: int

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": "microbit_sensor_state",
            "source": self.hand.label,
            "message_type": int(MessageType.SENSOR_STATE),
            "hand": int(self.hand),
            "sample_sequence": self.sample_sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "pi_rx_monotonic_ns": self.pi_rx_monotonic_ns,
            "raw": {
                "ax_mg": self.ax_mg,
                "ay_mg": self.ay_mg,
                "az_mg": self.az_mg,
                "pitch_deg": self.pitch_deg,
                "roll_deg": self.roll_deg,
            },
            "time_alignment": None,
        }


@dataclass(frozen=True, slots=True)
class ControlEvent:
    hand: Hand
    event_sequence: int
    device_timestamp_ms: int
    pi_rx_monotonic_ns: int
    event_code: EventCode
    priority: int
    repeat_index: int
    repeat_total: int
    mapped_candidate: str

    @property
    def dedup_key(self) -> tuple[Hand, int]:
        return self.hand, self.event_sequence

    @property
    def immutable_signature(self) -> tuple[int, int, int, int]:
        """重复副本除 repeat_index 外必须完全一致。"""
        return (
            self.device_timestamp_ms,
            int(self.event_code),
            self.priority,
            self.repeat_total,
        )

    def to_dict(self, *, duplicate: bool = False) -> dict[str, Any]:
        return {
            "type": "microbit_control_event",
            "source": self.hand.label,
            "message_type": int(MessageType.CONTROL_EVENT),
            "hand": int(self.hand),
            "event_sequence": self.event_sequence,
            "device_timestamp_ms": self.device_timestamp_ms,
            "pi_rx_monotonic_ns": self.pi_rx_monotonic_ns,
            "event_code": self.event_code.name,
            "priority": self.priority,
            "repeat_index": self.repeat_index,
            "repeat_total": self.repeat_total,
            "duplicate": duplicate,
            "mapped_candidate": self.mapped_candidate,
            "time_alignment": None,
        }


Packet = SensorState | ControlEvent


def parse_packet(
    payload: bytes | bytearray,
    *,
    expected_hand: Hand,
    pi_rx_monotonic_ns: int,
) -> Packet:
    """
    按首字节分流并完成协议级校验。

    expected_hand 来自当前 BLE 连接的配置；它与包内 hand 必须一致，
    从而避免左右设备配置错误后仍把数据送入融合模块。
    """
    if not payload:
        raise ProtocolError("payload 不能为空")

    message_type, hand = decode_header(payload[0])
    if hand is not expected_hand:
        raise ProtocolError(
            f"来源设备配置为 {expected_hand.label}，包内 hand 却是 {hand.label}"
        )

    if message_type is MessageType.SENSOR_STATE:
        return _parse_sensor_state(bytes(payload), hand, pi_rx_monotonic_ns)
    return _parse_control_event(bytes(payload), hand, pi_rx_monotonic_ns)


def _parse_sensor_state(payload: bytes, hand: Hand, rx_ns: int) -> SensorState:
    if len(payload) != SENSOR_STATE_STRUCT.size:
        raise ProtocolError(
            f"sensor_state 必须为 17 B，实际为 {len(payload)} B"
        )

    (_header, sequence, timestamp_ms, ax, ay, az, pitch, roll) = (
        SENSOR_STATE_STRUCT.unpack(payload)
    )

    # ±8 g 是设计允许的最大测试量程；姿态角由 MakeCode 返回 -180~180°。
    if any(not -8000 <= value <= 8000 for value in (ax, ay, az)):
        raise ProtocolError(f"加速度越界: {(ax, ay, az)} mg")
    if not -180 <= pitch <= 180 or not -180 <= roll <= 180:
        raise ProtocolError(f"姿态角越界: pitch={pitch}, roll={roll}")

    return SensorState(
        hand=hand,
        sample_sequence=sequence,
        device_timestamp_ms=timestamp_ms,
        pi_rx_monotonic_ns=rx_ns,
        ax_mg=ax,
        ay_mg=ay,
        az_mg=az,
        pitch_deg=pitch,
        roll_deg=roll,
    )


def _parse_control_event(payload: bytes, hand: Hand, rx_ns: int) -> ControlEvent:
    if len(payload) != CONTROL_EVENT_STRUCT.size:
        raise ProtocolError(
            f"control_event 必须为 11 B，实际为 {len(payload)} B"
        )

    (_header, sequence, timestamp_ms, raw_code, priority,
     repeat_index, repeat_total) = CONTROL_EVENT_STRUCT.unpack(payload)

    try:
        event_code = EventCode(raw_code)
    except ValueError as exc:
        raise ProtocolError(f"未定义的 event_code: 0x{raw_code:02x}") from exc

    rule = EVENT_RULES.get((hand, event_code))
    if rule is None:
        raise ProtocolError(
            f"{hand.label} 不允许发送事件 {event_code.name}"
        )
    expected_priority, mapped_candidate = rule
    if priority != expected_priority:
        raise ProtocolError(
            f"{hand.label}/{event_code.name} 的 priority 应为 "
            f"{expected_priority}，实际为 {priority}"
        )
    if repeat_total <= 0:
        raise ProtocolError("repeat_total 必须大于 0")
    if repeat_index >= repeat_total:
        raise ProtocolError(
            f"repeat_index={repeat_index} 必须小于 repeat_total={repeat_total}"
        )

    return ControlEvent(
        hand=hand,
        event_sequence=sequence,
        device_timestamp_ms=timestamp_ms,
        pi_rx_monotonic_ns=rx_ns,
        event_code=event_code,
        priority=priority,
        repeat_index=repeat_index,
        repeat_total=repeat_total,
        mapped_candidate=mapped_candidate,
    )

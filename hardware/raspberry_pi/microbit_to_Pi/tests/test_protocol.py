from __future__ import annotations

import struct

import pytest

from microbit_receiver.protocol import (
    CONTROL_EVENT_STRUCT,
    SENSOR_STATE_STRUCT,
    ControlEvent,
    Hand,
    ProtocolError,
    SensorState,
    parse_packet,
)
from microbit_receiver.tracking import EventDeduplicator, SequenceTracker


def test_parse_left_sensor_state() -> None:
    payload = SENSOR_STATE_STRUCT.pack(0x01, 1821, 73452, 112, -934, 287, -18, 42)
    packet = parse_packet(payload, expected_hand=Hand.LEFT, pi_rx_monotonic_ns=123)
    assert isinstance(packet, SensorState)
    assert packet.sample_sequence == 1821
    assert packet.ay_mg == -934
    assert packet.roll_deg == 42


def test_parse_right_emergency_stop() -> None:
    payload = CONTROL_EVENT_STRUCT.pack(0x06, 215, 82411, 0x03, 100, 0, 3)
    packet = parse_packet(payload, expected_hand=Hand.RIGHT, pi_rx_monotonic_ns=456)
    assert isinstance(packet, ControlEvent)
    assert packet.mapped_candidate == "emergency_stop"


@pytest.mark.parametrize(
    "payload, expected",
    [
        (b"", "payload"),
        (b"\x09" + bytes(16), "保留位"),
        (b"\x01" + bytes(15), "17 B"),
        (SENSOR_STATE_STRUCT.pack(0x05, 1, 1, 0, 0, 1000, 0, 0), "包内 hand"),
    ],
)
def test_reject_invalid_packets(payload: bytes, expected: str) -> None:
    with pytest.raises(ProtocolError, match=expected):
        parse_packet(payload, expected_hand=Hand.LEFT, pi_rx_monotonic_ns=0)


def test_reject_wrong_priority() -> None:
    payload = CONTROL_EVENT_STRUCT.pack(0x06, 1, 100, 0x03, 60, 0, 3)
    with pytest.raises(ProtocolError, match="priority 应为 100"):
        parse_packet(payload, expected_hand=Hand.RIGHT, pi_rx_monotonic_ns=0)


def make_state(sequence: int, timestamp: int) -> SensorState:
    return SensorState(Hand.LEFT, sequence, timestamp, 0, 0, 0, 1000, 0, 0)


def test_sequence_gap_duplicate_and_wraparound() -> None:
    tracker = SequenceTracker()
    assert tracker.observe(make_state(65534, 100)).accept
    gap = tracker.observe(make_state(0, 180))
    assert gap.accept and gap.missing_sample_count == 1
    duplicate = tracker.observe(make_state(0, 180))
    assert not duplicate.accept and duplicate.reason == "duplicate"
    assert tracker.observe(make_state(1, 220)).accept


def test_event_dedup_and_inconsistent_copy() -> None:
    first = ControlEvent(Hand.RIGHT, 9, 1000, 1, 3, 100, 0, 3, "emergency_stop")
    copy = ControlEvent(Hand.RIGHT, 9, 1000, 2, 3, 100, 1, 3, "emergency_stop")
    bad_copy = ControlEvent(Hand.RIGHT, 9, 1000, 3, 3, 60, 2, 3, "emergency_stop")
    dedup = EventDeduplicator(10)
    assert dedup.is_duplicate(first) is False
    assert dedup.is_duplicate(copy) is True
    with pytest.raises(ProtocolError, match="内容不一致"):
        dedup.is_duplicate(bad_copy)

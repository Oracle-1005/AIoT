"""状态序号跟踪和控制事件 TTL 去重。"""

from __future__ import annotations

import time
from dataclasses import dataclass

from .protocol import ControlEvent, Hand, ProtocolError, SensorState


@dataclass(frozen=True, slots=True)
class SequenceDecision:
    accept: bool
    reason: str
    missing_sample_count: int = 0
    device_restarted: bool = False


class SequenceTracker:
    """每只手独立追踪 uint16 样本序号，并正确处理 65535 -> 0 回绕。"""

    def __init__(self) -> None:
        self._last: dict[Hand, tuple[int, int]] = {}

    def clear(self, hand: Hand) -> None:
        self._last.pop(hand, None)

    def observe(self, state: SensorState) -> SequenceDecision:
        previous = self._last.get(state.hand)
        current = (state.sample_sequence, state.device_timestamp_ms)
        if previous is None:
            self._last[state.hand] = current
            return SequenceDecision(True, "first_sample")

        last_sequence, last_timestamp = previous
        forward = (state.sample_sequence - last_sequence) & 0xFFFF

        if forward == 0:
            return SequenceDecision(False, "duplicate")
        if forward == 1:
            self._last[state.hand] = current
            return SequenceDecision(True, "in_order")
        if 1 < forward < 0x8000:
            self._last[state.hand] = current
            return SequenceDecision(
                True,
                "sequence_gap",
                missing_sample_count=forward - 1,
            )

        # 设备时间戳显著回退时，将序号回退解释为 micro:bit 重启。
        # 1 秒容差避免极端延迟或轻微乱序造成误判。
        if state.device_timestamp_ms + 1000 < last_timestamp:
            self._last[state.hand] = current
            return SequenceDecision(True, "device_restart", device_restarted=True)

        return SequenceDecision(False, "out_of_order")


class EventDeduplicator:
    """以 (hand, event_sequence) 去重，并核对三份副本的一致性。"""

    def __init__(self, ttl_seconds: float = 10.0) -> None:
        self._ttl_ns = int(ttl_seconds * 1_000_000_000)
        self._seen: dict[tuple[Hand, int], tuple[int, tuple[int, int, int, int]]] = {}

    def clear(self, hand: Hand) -> None:
        self._seen = {
            key: value for key, value in self._seen.items() if key[0] is not hand
        }

    def is_duplicate(self, event: ControlEvent) -> bool:
        now_ns = time.monotonic_ns()
        self._expire(now_ns)
        existing = self._seen.get(event.dedup_key)

        if existing is None:
            self._seen[event.dedup_key] = (
                now_ns + self._ttl_ns,
                event.immutable_signature,
            )
            return False

        _expires_ns, signature = existing
        if signature != event.immutable_signature:
            raise ProtocolError(
                "同一 (hand, event_sequence) 的重复包内容不一致"
            )
        return True

    def _expire(self, now_ns: int) -> None:
        self._seen = {
            key: value for key, value in self._seen.items() if value[0] > now_ns
        }

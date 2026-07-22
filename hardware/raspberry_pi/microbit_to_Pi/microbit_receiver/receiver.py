"""Bleak 双连接管理、通知回调与 sensor/control 双队列分流。"""

from __future__ import annotations

import asyncio
import itertools
import logging
import time
from dataclasses import dataclass
from typing import Any

from bleak import BleakClient, BleakScanner
from bleak.backends.device import BLEDevice

from .protocol import ControlEvent, Hand, ProtocolError, SensorState, parse_packet
from .tracking import EventDeduplicator, SequenceTracker


LOGGER = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class DeviceConfig:
    hand: Hand
    address: str | None = None
    name: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "DeviceConfig":
        hand = Hand.from_label(str(data.get("hand", "")))
        address = data.get("address")
        name = data.get("name")
        if not address and not name:
            raise ValueError(f"{hand.label} 设备至少要配置 address 或 name")
        return cls(hand=hand, address=address, name=name)


class DualMicrobitReceiver:
    """维护协议状态；每个 DeviceConfig 由一个独立协程负责重连。"""

    def __init__(
        self,
        *,
        tx_characteristic_uuid: str,
        sensor_queue_size: int = 256,
        event_dedup_ttl_seconds: float = 10.0,
    ) -> None:
        self.tx_characteristic_uuid = tx_characteristic_uuid
        self.sensor_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=sensor_queue_size
        )
        # PriorityQueue 使用 (-priority, arrival_order, event_dict)，负号令高优先级先出队。
        self.control_queue: asyncio.PriorityQueue[
            tuple[int, int, dict[str, Any]]
        ] = asyncio.PriorityQueue()
        self.sequence_tracker = SequenceTracker()
        self.event_deduplicator = EventDeduplicator(event_dedup_ttl_seconds)
        self._arrival_counter = itertools.count()
        self._connect_lock = asyncio.Lock()

    async def run_device(
        self,
        config: DeviceConfig,
        stop_event: asyncio.Event,
    ) -> None:
        """连接单只手；断线后清理该手状态并按退避时间重连。"""
        retry_seconds = 1.0
        while not stop_event.is_set():
            disconnected = asyncio.Event()
            client: BleakClient | None = None
            try:
                def on_disconnect(_client: BleakClient) -> None:
                    disconnected.set()

                async with self._connect_lock:
                    target = await self._resolve_target(config)
                    client = BleakClient(
                        target,
                        disconnected_callback=on_disconnect,
                        timeout=20.0,
                    )
                    await client.connect()
                    LOGGER.info("%s micro:bit 已连接: %s", config.hand.label, target)
                    self.reset_hand(config.hand)

                    def on_notify(_sender: Any, data: bytearray) -> None:
                        # 必须在回调入口立即记录树莓派单调时钟，而不是排队后再记录。
                        rx_ns = time.monotonic_ns()
                        self.handle_notification(config.hand, bytes(data), rx_ns)

                    await client.start_notify(self.tx_characteristic_uuid, on_notify)

                retry_seconds = 1.0
                stop_task = asyncio.create_task(stop_event.wait())
                disconnect_task = asyncio.create_task(disconnected.wait())
                done, pending = await asyncio.wait(
                    {stop_task, disconnect_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)
                if stop_task in done and stop_task.result():
                    return

            except asyncio.CancelledError:
                raise
            except Exception as exc:  # BLE/BlueZ 错误需要重连而不是退出整个程序。
                LOGGER.warning(
                    "%s micro:bit 连接失败: %s；%.1f 秒后重试",
                    config.hand.label,
                    exc,
                    retry_seconds,
                )
            finally:
                if client is not None:
                    try:
                        if client.is_connected:
                            await client.stop_notify(self.tx_characteristic_uuid)
                    except Exception:
                        pass
                    try:
                        if client.is_connected:
                            await client.disconnect()
                    except Exception:
                        pass
                self.reset_hand(config.hand)

            try:
                await asyncio.wait_for(stop_event.wait(), timeout=retry_seconds)
            except asyncio.TimeoutError:
                pass
            retry_seconds = min(retry_seconds * 2, 10.0)

    async def _resolve_target(self, config: DeviceConfig) -> BLEDevice:
        """每次连接前必须重新扫描，避免 BlueZ random address 缓存造成服务发现失败。"""
        if config.address:
            device = await BleakScanner.find_device_by_address(
                config.address, timeout=10.0
            )
            if device is None:
                raise RuntimeError(f"扫描不到地址为 {config.address!r} 的设备")
            return device

        assert config.name is not None
        device = await BleakScanner.find_device_by_name(config.name, timeout=10.0)
        if device is None:
            raise RuntimeError(f"扫描不到名称为 {config.name!r} 的设备")
        return device

    def reset_hand(self, hand: Hand) -> None:
        """按文档要求在 BLE 重连/断线时清除序号与事件去重状态。"""
        self.sequence_tracker.clear(hand)
        self.event_deduplicator.clear(hand)

    def handle_notification(
        self,
        expected_hand: Hand,
        payload: bytes,
        pi_rx_monotonic_ns: int,
    ) -> None:
        """解析一个 BLE 通知。此函数不做耗时处理，防止阻塞 Bleak 回调。"""
        try:
            packet = parse_packet(
                payload,
                expected_hand=expected_hand,
                pi_rx_monotonic_ns=pi_rx_monotonic_ns,
            )
            if isinstance(packet, SensorState):
                self._route_sensor(packet)
            else:
                self._route_control(packet)
        except ProtocolError as exc:
            LOGGER.error(
                "丢弃 %s 非法包 (%d B, %s): %s",
                expected_hand.label,
                len(payload),
                payload.hex(" "),
                exc,
            )

    def _route_sensor(self, state: SensorState) -> None:
        decision = self.sequence_tracker.observe(state)
        if not decision.accept:
            LOGGER.debug(
                "丢弃 %s 状态 seq=%d: %s",
                state.hand.label,
                state.sample_sequence,
                decision.reason,
            )
            return

        item = state.to_dict()
        item["sequence_status"] = decision.reason
        item["missing_sample_count"] = decision.missing_sample_count
        item["device_restarted"] = decision.device_restarted

        # 状态队列满时丢最旧包，确保下游优先处理新鲜姿态。
        if self.sensor_queue.full():
            try:
                self.sensor_queue.get_nowait()
                self.sensor_queue.task_done()
            except asyncio.QueueEmpty:
                pass
        self.sensor_queue.put_nowait(item)

        if decision.device_restarted:
            self.event_deduplicator.clear(state.hand)

    def _route_control(self, event: ControlEvent) -> None:
        duplicate = self.event_deduplicator.is_duplicate(event)
        if duplicate:
            LOGGER.debug(
                "忽略重复控制事件 %s/%d，第 %d 份",
                event.hand.label,
                event.event_sequence,
                event.repeat_index,
            )
            return

        item = event.to_dict(duplicate=False)
        self.control_queue.put_nowait(
            (-event.priority, next(self._arrival_counter), item)
        )

"""命令行入口：连接双 micro:bit，并以 JSON Lines 输出两类数据。"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import signal
import sys
from pathlib import Path
from typing import Any

from .receiver import DeviceConfig, DualMicrobitReceiver


LOGGER = logging.getLogger(__name__)


def load_config(path: Path) -> tuple[DualMicrobitReceiver, list[DeviceConfig]]:
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    devices = [DeviceConfig.from_dict(item) for item in data["devices"]]
    hands = {device.hand for device in devices}
    if not devices or len(devices) > 2 or len(hands) != len(devices):
        raise ValueError("devices 必须包含一到两个设备，且 hand 不能重复")

    receiver = DualMicrobitReceiver(
        tx_characteristic_uuid=data.get(
            "tx_characteristic_uuid",
            "6e400002-b5a3-f393-e0a9-e50e24dcca9e",
        ),
        sensor_queue_size=int(data.get("sensor_queue_size", 256)),
        event_dedup_ttl_seconds=float(
            data.get("event_dedup_ttl_seconds", 10.0)
        ),
    )
    return receiver, devices


def write_json_line(item: dict[str, Any]) -> None:
    """stdout 只输出机器可读 JSON；运行日志统一写 stderr。"""
    print(json.dumps(item, ensure_ascii=False, separators=(",", ":")), flush=True)


async def consume_sensor(receiver: DualMicrobitReceiver) -> None:
    while True:
        item = await receiver.sensor_queue.get()
        try:
            # 后续可在这里调用时间同步/滤波入口；目前按设计保留 time_alignment=null。
            write_json_line(item)
        finally:
            receiver.sensor_queue.task_done()


async def consume_control(receiver: DualMicrobitReceiver) -> None:
    while True:
        _negative_priority, _arrival_order, item = await receiver.control_queue.get()
        try:
            # 紧急停止在独立消费者中直接输出，不等待状态滤波或摄像头融合。
            write_json_line(item)
        finally:
            receiver.control_queue.task_done()


async def async_main(config_path: Path) -> None:
    receiver, devices = load_config(config_path)
    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()

    for signame in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(signame, stop_event.set)
        except NotImplementedError:
            pass

    tasks = [
        asyncio.create_task(receiver.run_device(device, stop_event))
        for device in devices
    ]
    tasks.extend(
        [
            asyncio.create_task(consume_sensor(receiver)),
            asyncio.create_task(consume_control(receiver)),
        ]
    )

    try:
        await stop_event.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="双 micro:bit BLE 数据接收器")
    parser.add_argument("--config", type=Path, required=True, help="JSON 配置文件")
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=("DEBUG", "INFO", "WARNING", "ERROR"),
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    try:
        asyncio.run(async_main(args.config))
    except (KeyError, ValueError, json.JSONDecodeError) as exc:
        parser.error(f"配置错误: {exc}")


if __name__ == "__main__":
    main()

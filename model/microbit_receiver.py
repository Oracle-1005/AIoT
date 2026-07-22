"""
PC 端 Micro:bit 数据接收模块
=============================
支持两种模式：
  1. USB Serial (CDC) — 数据采集阶段推荐（可靠、免配对）
  2. BLE UART — 最终演示使用（无线腕带）

用法：
  python microbit_receiver.py --mode serial   # USB 串口模式
  python microbit_receiver.py --mode ble      # BLE 模式
"""

import asyncio
import sys
import time
import csv
import json
import struct
from dataclasses import dataclass, field
from typing import Optional, Callable
from collections import deque


# ============================================================
# 数据结构
# ============================================================

@dataclass
class AccelSample:
    """单次加速度采样"""
    device_id: str           # "A" = 左手, "B" = 右手
    acc_x: float             # mg (milli-g)
    acc_y: float
    acc_z: float
    timestamp_ms: int        # Micro:bit running_time()
    pc_timestamp: float      # PC 端 time.time() (用于同步校准)

    @property
    def acc_norm(self) -> float:
        """加速度模长 (mg)"""
        return (self.acc_x**2 + self.acc_y**2 + self.acc_z**2) ** 0.5


@dataclass
class AccelBuffer:
    """滑动窗口缓冲区（每个设备独立）"""
    device_id: str
    samples: deque = field(default_factory=lambda: deque(maxlen=250))  # 5s @ 50Hz

    def push(self, sample: AccelSample):
        self.samples.append(sample)

    def get_window(self, duration_ms: int = 500) -> list[AccelSample]:
        """取最近 duration_ms 毫秒内的样本"""
        if not self.samples:
            return []
        cutoff = self.samples[-1].timestamp_ms - duration_ms
        return [s for s in self.samples if s.timestamp_ms >= cutoff]

    @property
    def latest(self) -> Optional[AccelSample]:
        return self.samples[-1] if self.samples else None


# ============================================================
# 串口接收器 (USB CDC)
# ============================================================

class SerialReceiver:
    """通过 USB 串口接收 Micro:bit 数据"""

    def __init__(self, port: str = "auto", baudrate: int = 115200):
        self.port = port
        self.baudrate = baudrate
        self.buffers: dict[str, AccelBuffer] = {}
        self._callbacks: list[Callable] = []
        self._ser = None

    def on_sample(self, callback: Callable[[AccelSample], None]):
        """注册数据回调"""
        self._callbacks.append(callback)

    def _parse_line(self, line: str, pc_ts: float) -> Optional[AccelSample]:
        """
        解析一行数据: "A,1234,-56,789,12345678"
                       DEVICE_ID, x, y, z, timestamp_ms
        """
        line = line.strip()
        if not line or line.startswith('#'):
            return None
        try:
            parts = line.split(',')
            if len(parts) != 5:
                return None
            device_id = parts[0].strip()
            acc_x = float(parts[1])
            acc_y = float(parts[2])
            acc_z = float(parts[3])
            ts = int(parts[4])
            return AccelSample(
                device_id=device_id,
                acc_x=acc_x, acc_y=acc_y, acc_z=acc_z,
                timestamp_ms=ts,
                pc_timestamp=pc_ts,
            )
        except (ValueError, IndexError):
            return None

    def _handle_sample(self, sample: AccelSample):
        """将样本推入缓冲区并触发回调"""
        if sample.device_id not in self.buffers:
            self.buffers[sample.device_id] = AccelBuffer(device_id=sample.device_id)
        self.buffers[sample.device_id].push(sample)
        for cb in self._callbacks:
            try:
                cb(sample)
            except Exception as e:
                print(f"[WARN] callback error: {e}")

    def list_ports(self) -> list[str]:
        """列出可用串口"""
        import serial.tools.list_ports
        ports = serial.tools.list_ports.comports()
        print("Available serial ports:")
        for p in ports:
            print(f"  {p.device} — {p.description}")
        return [p.device for p in ports]

    def start(self):
        """启动串口接收（阻塞）"""
        import serial
        import serial.tools.list_ports

        if self.port == "auto":
            ports = serial.tools.list_ports.comports()
            # Micro:bit CDC 通常带 "USB Serial Device" 或 "mbed" 描述
            microbit_ports = [p.device for p in ports
                            if 'microbit' in p.description.lower()
                            or 'mbed' in p.description.lower()
                            or 'usb serial' in p.description.lower()]
            if not microbit_ports:
                print("[ERROR] No Micro:bit serial port found. Try specifying manually:")
                self.list_ports()
                return
            self.port = microbit_ports[0]
            print(f"[INFO] Auto-detected Micro:bit at {self.port}")

        self._ser = serial.Serial(self.port, self.baudrate, timeout=1)
        print(f"[INFO] Connected to {self.port} @ {self.baudrate} baud")

        try:
            while True:
                line = self._ser.readline().decode('utf-8', errors='replace')
                if line:
                    sample = self._parse_line(line, time.time())
                    if sample:
                        self._handle_sample(sample)
        except KeyboardInterrupt:
            print("\n[INFO] Stopped.")
        finally:
            self._ser.close()


# ============================================================
# BLE 接收器 (Bluetooth Low Energy)
# ============================================================

class BLEReceiver:
    """通过 BLE UART 接收 Micro:bit 数据"""

    # MakeCode Bluetooth UART uses Nordic UART Service (NUS)
    # TX = 6e400002 (indicate), RX = 6e400003 (write)
    NUS_TX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Micro:bit → PC (indicate)
    NUS_RX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # PC → Micro:bit (write)

    def __init__(self, device_names: list[str] = None):
        """
        device_names: 要连接的 Micro:bit BLE 名称列表
                      默认 ["uBit-A", "uBit-B"] (左右手)
        """
        self.device_names = device_names or ["uBit-A", "uBit-B"]
        self.buffers: dict[str, AccelBuffer] = {}
        self._callbacks: list[Callable] = []
        self._clients: dict[str, object] = {}  # device_name → BleakClient

    def on_sample(self, callback: Callable[[AccelSample], None]):
        """注册数据回调"""
        self._callbacks.append(callback)

    def _parse_line(self, line: str) -> Optional[AccelSample]:
        """同 SerialReceiver._parse_line"""
        line = line.strip()
        if not line:
            return None
        try:
            parts = line.split(',')
            if len(parts) != 5:
                return None
            return AccelSample(
                device_id=parts[0].strip(),
                acc_x=float(parts[1]),
                acc_y=float(parts[2]),
                acc_z=float(parts[3]),
                timestamp_ms=int(parts[4]),
                pc_timestamp=time.time(),
            )
        except (ValueError, IndexError):
            return None

    def _handle_notification(self, device_name: str, data: bytearray):
        """BLE notify 回调"""
        text = data.decode('utf-8', errors='replace')
        for line in text.split('\n'):
            sample = self._parse_line(line)
            if sample:
                if sample.device_id not in self.buffers:
                    self.buffers[sample.device_id] = AccelBuffer(device_id=sample.device_id)
                self.buffers[sample.device_id].push(sample)
                for cb in self._callbacks:
                    try:
                        cb(sample)
                    except Exception as e:
                        print(f"[WARN] callback error: {e}")

    async def _connect_device(self, device_name: str):
        """连接单个 Micro:bit"""
        from bleak import BleakScanner, BleakClient

        print(f"[BLE] Scanning for {device_name}...")
        device = await BleakScanner.find_device_by_name(device_name, timeout=10.0)

        if device is None:
            print(f"[WARN] {device_name} not found. Retrying...")
            return False

        print(f"[BLE] Found {device_name} at {device.address}, connecting...")
        client = BleakClient(device.address)

        try:
            await client.connect()
            print(f"[BLE] {device_name} connected!")

            # 订阅 TX characteristic (Notify → Micro:bit 发数据)
            def notification_handler(sender, data):
                self._handle_notification(device_name, data)

            await client.start_notify(self.NUS_TX_UUID, notification_handler)
            self._clients[device_name] = client
            return True

        except Exception as e:
            print(f"[ERROR] Failed to connect {device_name}: {e}")
            return False

    async def start(self):
        """启动 BLE 接收（异步）"""
        print("[BLE] Starting BLE receiver...")
        print(f"[BLE] Looking for devices: {self.device_names}")

        # 并行连接所有设备
        tasks = [self._connect_device(name) for name in self.device_names]
        results = await asyncio.gather(*tasks)

        connected = [name for name, ok in zip(self.device_names, results) if ok]
        print(f"[BLE] Connected to {len(connected)}/{len(self.device_names)} devices: {connected}")

        if not connected:
            print("[ERROR] No devices connected!")
            return

        # 保持连接
        try:
            while True:
                await asyncio.sleep(1)
                # 打印统计
                for name in connected:
                    buf = self.buffers.get(name[5:])  # "uBit-A" → "A"
                    if buf and buf.latest:
                        s = buf.latest
                        print(f"\r[{name}] x={s.acc_x:6.0f} y={s.acc_y:6.0f} z={s.acc_z:6.0f} | norm={s.acc_norm:6.0f}mg", end='')
                print('', end='\r')
        except KeyboardInterrupt:
            print("\n[BLE] Disconnecting...")
        finally:
            for name, client in self._clients.items():
                await client.disconnect()
            print("[BLE] All disconnected.")


# ============================================================
# 便捷入口
# ============================================================

async def main():
    import argparse
    parser = argparse.ArgumentParser(description="Micro:bit Accelerometer Receiver")
    parser.add_argument("--mode", choices=["serial", "ble"], default="serial",
                        help="接收模式: serial (USB) 或 ble (蓝牙)")
    parser.add_argument("--port", default="auto",
                        help="串口路径 (默认自动检测)")
    parser.add_argument("--output", default=None,
                        help="输出 CSV 文件路径 (可选)")
    parser.add_argument("--duration", type=int, default=0,
                        help="采集时长（秒），0=无限")
    args = parser.parse_args()

    # 数据回调：打印到终端
    sample_count = [0]

    def print_sample(s: AccelSample):
        sample_count[0] += 1
        if sample_count[0] % 50 == 1:  # 每 50 个样本 (~1秒) 打印一次
            print(f"[{s.device_id}] x={s.acc_x:6.0f} y={s.acc_y:6.0f} z={s.acc_z:6.0f} | norm={s.acc_norm:6.0f}mg | ts={s.timestamp_ms}")

    if args.mode == "serial":
        receiver = SerialReceiver(port=args.port)
        receiver.on_sample(print_sample)
        receiver.start()
    else:
        receiver = BLEReceiver()
        receiver.on_sample(print_sample)
        await receiver.start()


if __name__ == "__main__":
    asyncio.run(main())

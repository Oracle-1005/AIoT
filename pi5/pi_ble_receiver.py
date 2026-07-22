#!/usr/bin/env python3
"""
Pi 5 BLE Receiver — Micro:bit ×2 → MQTT
=========================================
Connects to 2× Micro:bit via BLE UART (Nordic SoftDevice → Linux BlueZ),
parses 50Hz accelerometer data, and publishes to MQTT topics.

Architecture:
  Micro:bit A (left wrist)  ──BLE──▶  pi_ble_receiver  ──MQTT──▶  microbit/accel/A
  Micro:bit B (right wrist) ──BLE──▶  pi_ble_receiver  ──MQTT──▶  microbit/accel/B

Prerequisites:
  - sudo apt install -y mosquitto mosquitto-clients
  - pip install bleak paho-mqtt
  - Micro:bit firmware: ble_uart_final.js (MakeCode, BLE UART, ~66Hz)
  - Micro:bit BLE device names: "uBit-A" (left), "uBit-B" (right)

Usage:
  python pi_ble_receiver.py
  python pi_ble_receiver.py --broker localhost --no-audio

Data Format (published to MQTT):
  {
    "device_id": "A",
    "acc_x": 1234,       # milli-g
    "acc_y": -56,
    "acc_z": 789,
    "timestamp_ms": 12345678,    # Micro:bit running_time()
    "pc_timestamp": 1234567890.123,   # Pi time.time()
    "acc_norm": 1456.2   # sqrt(x²+y²+z²)
  }
"""

import asyncio
import json
import os
import signal
import sys
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional, Callable

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Expected MakeCode BLE UART device names
# The MakeCode BLE extension uses BBC micro:bit naming:
# "BBC micro:bit [xxxx]" — 5 alphanumeric chars from the friendly name
# We identify by prefix "BBC micro:bit" and optionally by the suffix.
DEFAULT_DEVICE_PREFIX = "BBC micro:bit"  # Generic MakeCode BLE name
DEFAULT_DEVICE_NAMES = ["uBit-A", "uBit-B"]  # Fallback: try friendly names

# Nordic UART Service (NUS) UUIDs — standard across MakeCode BLE
NUS_TX_UUID = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # Micro:bit → Pi (notify)
NUS_RX_UUID = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # Pi → Micro:bit (write)

# MQTT defaults
MQTT_BROKER = os.getenv("MQTT_BROKER", "localhost")
MQTT_PORT = int(os.getenv("MQTT_PORT", "1883"))
MQTT_TOPIC_ACCEL = "microbit/accel"          # → microbit/accel/A, microbit/accel/B
MQTT_TOPIC_STATUS = "microbit/status"

# BLE connection retry
SCAN_TIMEOUT = float(os.getenv("BLE_SCAN_TIMEOUT", "15.0"))
RECONNECT_DELAY = float(os.getenv("BLE_RECONNECT_DELAY", "3.0"))
CONNECTION_TIMEOUT = float(os.getenv("BLE_CONNECTION_TIMEOUT", "10.0"))

# Data rate
EXPECTED_SAMPLE_INTERVAL_MS = 15  # ~66Hz from ble_uart_final.js
MAX_SAMPLES_PER_SECOND = 80


# ---------------------------------------------------------------------------
# Data Classes
# ---------------------------------------------------------------------------

@dataclass
class AccelSample:
    """Single accelerometer sample from Micro:bit."""
    device_id: str            # "A" = left, "B" = right
    acc_x: float              # milli-g
    acc_y: float
    acc_z: float
    timestamp_ms: int         # Micro:bit running_time() ms
    pc_timestamp: float       # Pi time.time()

    @property
    def acc_norm(self) -> float:
        """Acceleration magnitude in milli-g."""
        return (self.acc_x**2 + self.acc_y**2 + self.acc_z**2) ** 0.5

    def to_dict(self) -> dict:
        return {
            "device_id": self.device_id,
            "acc_x": self.acc_x,
            "acc_y": self.acc_y,
            "acc_z": self.acc_z,
            "timestamp_ms": self.timestamp_ms,
            "pc_timestamp": self.pc_timestamp,
            "acc_norm": round(self.acc_norm, 2),
        }


@dataclass
class DeviceStats:
    """Per-device connection + data statistics."""
    device_name: str
    device_id: str            # parsed from data: "A" or "B"
    address: str = ""
    connected: bool = False
    samples_received: int = 0
    last_sample_ts: float = 0.0
    last_data_ts: int = 0     # Micro:bit timestamp
    connection_attempts: int = 0
    connected_at: float = 0.0
    sample_rate: float = 0.0
    _recent_count: deque = field(default_factory=lambda: deque(maxlen=80))
    _recent_start: float = 0.0


# ---------------------------------------------------------------------------
# MQTT Publisher
# ---------------------------------------------------------------------------

class MQTTPublisher:
    """Async-friendly MQTT client using paho-mqtt thread loop."""

    def __init__(self, broker: str = MQTT_BROKER, port: int = MQTT_PORT):
        self.broker = broker
        self.port = port
        self._client = None

    def connect(self):
        import paho.mqtt.client as mqtt
        self._client = mqtt.Client(client_id=f"pi_ble_receiver_{os.getpid()}")
        self._client.connect_async(self.broker, self.port, keepalive=60)
        self._client.loop_start()
        print(f"[MQTT] Connected to {self.broker}:{self.port}")

    def publish(self, topic: str, payload: dict, qos: int = 0):
        """Publish JSON payload to MQTT topic."""
        if self._client:
            data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            self._client.publish(topic, data, qos=qos)

    def disconnect(self):
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            self._client = None


# ---------------------------------------------------------------------------
# BLE Receiver
# ---------------------------------------------------------------------------

class PiBLEReceiver:
    """BLE UART receiver for Micro:bit accelerometer data on Linux BlueZ."""

    def __init__(
        self,
        mqtt: MQTTPublisher,
        device_names: Optional[list[str]] = None,
        device_addresses: Optional[dict[str, str]] = None,
    ):
        """
        Args:
            mqtt: MQTT publisher instance.
            device_names: BLE device friendly names to scan for.
            device_addresses: dict mapping device_id ("A"/"B") → BLE MAC address.
                              If provided, skips scanning and connects directly.
        """
        self.mqtt = mqtt
        self.device_names = device_names or DEFAULT_DEVICE_NAMES
        self.device_addresses = device_addresses or {}
        self.stats: dict[str, DeviceStats] = {}  # device_name → stats
        self._clients: dict[str, object] = {}    # device_name → BleakClient
        self._running = False
        self._shutdown_event = asyncio.Event()

        # Callbacks
        self._on_sample_callbacks: list[Callable] = []

    def on_sample(self, callback: Callable[[AccelSample], None]):
        """Register callback for each received AccelSample."""
        self._on_sample_callbacks.append(callback)

    # ---- Parsing -------------------------------------------------------

    @staticmethod
    def parse_line(line: str) -> Optional[AccelSample]:
        """
        Parse one line of BLE UART data.

        Expected format (MakeCode ble_uart_final.js):
          "A,1234,-56,789,12345678\\n"
          DEVICE_ID, acc_x, acc_y, acc_z, running_time_ms
        """
        line = line.strip()
        if not line:
            return None
        try:
            parts = line.split(",")
            if len(parts) != 5:
                return None
            device_id = parts[0].strip()
            # Validate device_id — must be "A" or "B"
            if device_id not in ("A", "B"):
                # If it starts with "BBC micro:bit", this is a system message
                if device_id.startswith("BBC"):
                    return None
                # Otherwise try to recover: if length 1, use as-is
                if len(device_id) > 2:
                    return None
            return AccelSample(
                device_id=device_id,
                acc_x=float(parts[1]),
                acc_y=float(parts[2]),
                acc_z=float(parts[3]),
                timestamp_ms=int(parts[4]),
                pc_timestamp=time.time(),
            )
        except (ValueError, IndexError):
            return None

    # ---- BLE Notification Handler --------------------------------------

    def _handle_notification(self, device_name: str, data: bytearray):
        """Called by Bleak when a notification arrives on the NUS TX characteristic."""
        text = data.decode("utf-8", errors="replace")
        stat = self.stats.get(device_name)
        now = time.time()

        for line in text.split("\n"):
            sample = self.parse_line(line)
            if sample is None:
                continue

            # Update stats
            if stat:
                stat.samples_received += 1
                stat.last_sample_ts = now
                stat.last_data_ts = sample.timestamp_ms
                # Track sample rate
                if stat._recent_start == 0:
                    stat._recent_start = now
                stat._recent_count.append(now)
                elapsed = now - stat._recent_start
                if elapsed >= 1.0:
                    stat.sample_rate = len(stat._recent_count) / elapsed
                    stat._recent_count.clear()
                    stat._recent_start = now

            # Publish to MQTT
            self.mqtt.publish(
                f"{MQTT_TOPIC_ACCEL}/{sample.device_id}",
                sample.to_dict(),
                qos=0,
            )

            # Fire callbacks
            for cb in self._on_sample_callbacks:
                try:
                    cb(sample)
                except Exception:
                    pass

    # ---- BLE Connection -------------------------------------------------

    async def _scan_device(self, device_name: str) -> Optional[object]:
        """Scan for a specific BLE device. Returns Bleak device or None."""
        from bleak import BleakScanner

        print(f"[BLE] Scanning for '{device_name}' (timeout={SCAN_TIMEOUT}s)...")

        # Try exact name match first
        device = await BleakScanner.find_device_by_name(
            device_name, timeout=SCAN_TIMEOUT
        )
        if device:
            print(f"[BLE] Found '{device_name}' at {device.address}")
            return device

        # If name match fails, scan for all BBC micro:bit devices
        print(f"[BLE] Exact name not found, scanning for all BBC micro:bit devices...")
        devices = await BleakScanner.discover(timeout=SCAN_TIMEOUT, return_adv=True)
        candidates = []
        for d, adv in devices:
            name = d.name or adv.local_name or ""
            if "BBC micro:bit" in name or "micro:bit" in name.lower():
                candidates.append((d, name))
                print(f"[BLE]   Found: {name} [{d.address}] rssi={adv.rssi}")

        if candidates:
            # Pick the first one (often there's only one)
            # TODO: If 2 devices and both names are generic, use RSSI-based pairing
            chosen = candidates[0]
            print(f"[BLE] Selected: {chosen[1]} [{chosen[0].address}]")
            return chosen[0]

        return None

    async def _connect_device(self, device_name: str) -> bool:
        """Connect to a single Micro:bit, subscribe to NUS TX, and maintain connection."""
        from bleak import BleakClient

        # Initialize stats
        if device_name not in self.stats:
            self.stats[device_name] = DeviceStats(device_name=device_name, device_id="?")
        stat = self.stats[device_name]
        stat.connection_attempts += 1

        # Check for hardcoded address
        if device_name in self.device_addresses:
            address = self.device_addresses[device_name]
            print(f"[BLE] Using cached address for '{device_name}': {address}")
        else:
            device = await self._scan_device(device_name)
            if device is None:
                print(f"[BLE] Device '{device_name}' not found.")
                return False
            address = device.address
            stat.address = address

        # Connect
        print(f"[BLE] Connecting to '{device_name}' [{address}]...")
        client = BleakClient(
            address,
            timeout=CONNECTION_TIMEOUT,
            disconnected_callback=lambda c: self._on_disconnect(device_name, c),
        )

        try:
            await client.connect()
            stat.connected = True
            stat.connected_at = time.time()
            print(f"[BLE] ✓ Connected to '{device_name}' [{address}]")

            # Subscribe to NUS TX characteristic (notify/indicate)
            await client.start_notify(NUS_TX_UUID, self._handle_notification_factory(device_name))
            print(f"[BLE] ✓ Subscribed to NUS TX for '{device_name}'")

            self._clients[device_name] = client
            return True

        except Exception as e:
            print(f"[BLE] ✗ Connection failed for '{device_name}': {e}")
            stat.connected = False
            try:
                await client.disconnect()
            except Exception:
                pass
            return False

    def _handle_notification_factory(self, device_name: str):
        """Create a notification handler closure for a specific device."""
        def handler(sender, data):
            self._handle_notification(device_name, data)
        return handler

    async def _on_disconnect(self, device_name: str, client):
        """Handle unexpected BLE disconnection."""
        print(f"[BLE] Disconnected: '{device_name}'")
        stat = self.stats.get(device_name)
        if stat:
            stat.connected = False

        # Remove client from tracking
        self._clients.pop(device_name, None)

        # Try to reconnect if still running
        if self._running and not self._shutdown_event.is_set():
            print(f"[BLE] Will attempt reconnect for '{device_name}' in {RECONNECT_DELAY}s...")
            await asyncio.sleep(RECONNECT_DELAY)
            if self._running:
                await self._connect_device(device_name)

    # ---- Status Reporting -----------------------------------------------

    async def _status_loop(self, interval: float = 5.0):
        """Periodically publish device status to MQTT."""
        while self._running and not self._shutdown_event.is_set():
            await asyncio.sleep(interval)
            for name, stat in self.stats.items():
                self.mqtt.publish(f"{MQTT_TOPIC_STATUS}/{name}", {
                    "device_name": name,
                    "device_id": stat.device_id,
                    "address": stat.address,
                    "connected": stat.connected,
                    "samples_received": stat.samples_received,
                    "sample_rate": round(stat.sample_rate, 1),
                    "connected_at": stat.connected_at,
                    "connection_attempts": stat.connection_attempts,
                    "timestamp": time.time(),
                })

    # ---- Main Loop ------------------------------------------------------

    async def start(self):
        """Connect to all configured devices and start forwarding."""
        from bleak import BleakScanner

        print("=" * 60)
        print("[BLE] Pi 5 BLE Receiver starting...")
        print(f"[BLE] MQTT broker: {MQTT_BROKER}:{MQTT_PORT}")
        print(f"[BLE] Looking for devices: {self.device_names}")
        print(f"[BLE] Hardcoded addresses: {self.device_addresses}")
        print("=" * 60)

        self._running = True
        self.mqtt.connect()

        # Connect to all devices (parallel)
        tasks = [self._connect_device(name) for name in self.device_names]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        connected = [
            name for name, ok in zip(self.device_names, results)
            if ok is True
        ]
        print(f"[BLE] Initial connections: {len(connected)}/{len(self.device_names)} → {connected}")

        if not connected:
            print("[BLE] ⚠ No devices connected initially. Will keep scanning...")

        # Start status reporter
        status_task = asyncio.create_task(self._status_loop())

        # Main loop: keep running, handle reconnections
        try:
            while self._running and not self._shutdown_event.is_set():
                # Check for disconnected devices and try reconnect
                for name in self.device_names:
                    if name not in self._clients or not self._clients[name].is_connected:
                        if self.stats.get(name) and self.stats[name].connected:
                            self.stats[name].connected = False
                        print(f"[BLE] '{name}' not connected, attempting reconnect...")
                        await self._connect_device(name)

                await asyncio.sleep(RECONNECT_DELAY)

        except asyncio.CancelledError:
            pass
        finally:
            await self.stop()
            status_task.cancel()

    async def stop(self):
        """Graceful shutdown."""
        print("[BLE] Shutting down...")
        self._running = False
        self._shutdown_event.set()

        for name, client in list(self._clients.items()):
            try:
                await client.disconnect()
                print(f"[BLE] Disconnected '{name}'")
            except Exception as e:
                print(f"[BLE] Error disconnecting '{name}': {e}")
        self._clients.clear()

        self.mqtt.disconnect()
        print("[BLE] Stopped.")


# ---------------------------------------------------------------------------
# CLI Entry Point
# ---------------------------------------------------------------------------

async def main():
    import argparse

    parser = argparse.ArgumentParser(
        description="Pi 5 BLE Receiver — Micro:bit ×2 → MQTT",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--broker", default=MQTT_BROKER, help="MQTT broker address")
    parser.add_argument("--port", type=int, default=MQTT_PORT, help="MQTT broker port")
    parser.add_argument("--device", action="append", dest="devices",
                        help="Add a BLE device name (repeatable, e.g. --device 'uBit-A' --device 'uBit-B')")
    parser.add_argument("--address", action="append", dest="addresses",
                        help="Hardcoded BLE address for device (format: DEVICE_ID=MAC, e.g. A=FD:15:9A:47:7F:8F)")
    parser.add_argument("--scan-timeout", type=float, default=SCAN_TIMEOUT,
                        help=f"BLE scan timeout in seconds (default: {SCAN_TIMEOUT})")
    parser.add_argument("--no-status", action="store_true", help="Disable periodic status reporting")
    args = parser.parse_args()

    # Parse device names
    device_names = args.devices if args.devices else DEFAULT_DEVICE_NAMES

    # Parse hardcoded addresses
    device_addresses = {}
    if args.addresses:
        for entry in args.addresses:
            try:
                dev_id, mac = entry.split("=", 1)
                device_addresses[dev_id.strip()] = mac.strip()
            except ValueError:
                print(f"[WARN] Invalid --address format: '{entry}'. Expected DEVICE_ID=MAC")

    # Override global settings
    global SCAN_TIMEOUT
    SCAN_TIMEOUT = args.scan_timeout

    # Create components
    mqtt = MQTTPublisher(broker=args.broker, port=args.port)
    receiver = PiBLEReceiver(
        mqtt=mqtt,
        device_names=device_names,
        device_addresses=device_addresses,
    )

    # Log received samples to console (throttled)
    last_print = [0.0]

    def print_sample(s: AccelSample):
        now = time.time()
        if now - last_print[0] >= 1.0:  # Print once per second
            print(f"  [{s.device_id}] x={s.acc_x:6.0f} y={s.acc_y:6.0f} z={s.acc_z:6.0f}  "
                  f"|norm|={s.acc_norm:6.0f}mg  ts={s.timestamp_ms}")
            last_print[0] = now

    receiver.on_sample(print_sample)

    # Handle graceful shutdown
    loop = asyncio.get_event_loop()

    def shutdown():
        print("\n[BLE] Received shutdown signal...")
        receiver._shutdown_event.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, shutdown)
        except NotImplementedError:
            # Windows compatibility
            signal.signal(sig, lambda s, f: shutdown())

    await receiver.start()


if __name__ == "__main__":
    asyncio.run(main())

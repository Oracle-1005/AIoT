"""Multi-device BLE connection manager using Bleak.

Manages connections to multiple micro:bit devices, handles binary notification
callbacks, sends text commands (SYNC, START, STOP, etc.), and provides
auto-reconnection with exponential backoff.

Key design decision: We use BleakClient.start_notify() directly with raw
bytearray callbacks rather than going through BleUartDevice.enable_uart_receive(),
because enable_uart_receive decodes bytes to string (via decodeBleUartPayload),
which corrupts our 20-byte binary packets.
"""

import asyncio
import logging
import time
from collections.abc import Callable

from bleak import BleakScanner, BleakClient

logger = logging.getLogger(__name__)

# micro:bit UART Service UUIDs
UART_SERVICE_UUID = "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
UART_TX_CHAR_UUID = "6e400002-b5a3-f393-e0a9-e50e24dcca9e"  # RPi -> micro:bit (write)
UART_RX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"  # micro:bit -> RPi (notify)


class BleManager:
    """Manages multiple BLE micro:bit connections.

    Each device is tracked by its logical device_id. The manager handles
    scanning, connecting, notification subscription, command sending, and
    auto-reconnection.

    Args:
        device_configs: List of dicts with keys: device_id, hand, address
        on_packet: Callback(device_id, raw_bytes, pi_receive_ns) invoked on
                   each BLE notification with raw bytearray.
    """

    def __init__(
        self,
        device_configs: list[dict],
        on_packet: Callable[[str, bytearray, int], None],
        on_text: Callable[[str, str, int], None] | None = None,
    ):
        """Initialize the BLE manager.

        Args:
            device_configs: List of dicts with keys: device_id, hand, address
            on_packet: Callback(device_id, raw_bytes, pi_receive_ns) for binary
                       sensor data packets.
            on_text: Optional callback(device_id, text, pi_receive_ns) for text
                     notifications (e.g. SYNC_ACK responses).
        """
        self._device_cfgs: dict[str, dict] = {}
        for cfg in device_configs:
            self._device_cfgs[cfg["device_id"]] = cfg

        self._on_packet = on_packet
        self._on_text = on_text
        self._clients: dict[str, BleakClient] = {}
        self._rssi_cache: dict[str, int] = {}
        self._reconnect_tasks: dict[str, asyncio.Task] = {}
        self._connected: dict[str, bool] = {}
        self._shutting_down: bool = False

    # ---- Public API ----

    async def scan_and_connect_all(self, scan_timeout: float = 5.0) -> int:
        """Scan for configured devices by BLE address, connect, and enable notifications.

        Devices with empty addresses are skipped.

        Args:
            scan_timeout: BLE scan duration in seconds.

        Returns:
            Number of devices successfully connected.
        """
        logger.info("Starting BLE scan (timeout=%.1fs)...", scan_timeout)

        # Discover devices
        discovered = await BleakScanner.discover(timeout=scan_timeout)
        discovered_map: dict[str, str] = {}  # normalized_address -> name
        for d in discovered:
            addr = d.address.upper()
            discovered_map[addr] = d.name or "unknown"
            logger.debug("  Found: %s [%s]", addr, d.name)

        # Connect to configured devices found in scan
        connected_count = 0
        for device_id, cfg in self._device_cfgs.items():
            address = cfg.get("address", "").upper().strip()
            if not address:
                logger.warning("[%s] No BLE address configured, skipping.", device_id)
                continue

            if address in discovered_map:
                logger.info(
                    "[%s] Found device at %s [%s], connecting...",
                    device_id,
                    address,
                    discovered_map[address],
                )
                success = await self.connect_device(device_id)
                if success:
                    connected_count += 1
            else:
                logger.warning("[%s] Configured address %s not found in scan.", device_id, address)

        logger.info("BLE scan complete: %d/%d devices connected.", connected_count, len(self._device_cfgs))
        return connected_count

    async def connect_device(self, device_id: str) -> bool:
        """Connect to a specific device by its configured address.

        Args:
            device_id: Logical device ID.

        Returns:
            True if connected and notifications enabled.
        """
        cfg = self._device_cfgs.get(device_id)
        if cfg is None:
            logger.error("[%s] Unknown device_id.", device_id)
            return False

        address = cfg.get("address", "").upper().strip()
        if not address:
            logger.error("[%s] No address configured.", device_id)
            return False

        try:
            client = BleakClient(address, timeout=10.0)
            await client.connect()
            logger.info("[%s] Connected to %s.", device_id, address)

            # Wait for services to be discovered
            await asyncio.sleep(0.5)

            # Start notifications on the UART RX characteristic
            await client.start_notify(UART_RX_CHAR_UUID, self._make_notify_handler(device_id))
            logger.info("[%s] Notifications enabled on RX char.", device_id)

            self._clients[device_id] = client
            self._connected[device_id] = True

            # Start auto-reconnect background task
            if device_id in self._reconnect_tasks:
                self._reconnect_tasks[device_id].cancel()
            self._reconnect_tasks[device_id] = asyncio.create_task(
                self._auto_reconnect_loop(device_id)
            )

            return True

        except Exception as e:
            logger.error("[%s] Connection failed: %s", device_id, e)
            self._connected[device_id] = False
            return False

    async def send_command(self, device_id: str, command: str) -> bool:
        """Send a text command to a specific device via UART TX.

        Args:
            device_id: Logical device ID.
            command: Command string, e.g., "SYNC,5" or "START".

        Returns:
            True if sent successfully.
        """
        client = self._clients.get(device_id)
        if client is None or not client.is_connected:
            logger.warning("[%s] Cannot send command: not connected.", device_id)
            return False

        try:
            payload = (command + "\r\n").encode("utf-8")
            await client.write_gatt_char(UART_TX_CHAR_UUID, payload, response=True)
            logger.debug("[%s] Sent command: %s", device_id, command)
            return True
        except Exception as e:
            logger.warning("[%s] Send command '%s' failed: %s", device_id, command, e)
            return False

    async def send_command_all(self, command: str) -> dict[str, bool]:
        """Send a command to all connected devices.

        Args:
            command: Command string.

        Returns:
            Dict mapping device_id -> success flag.
        """
        results = {}
        for device_id in self._device_cfgs:
            results[device_id] = await self.send_command(device_id, command)
        return results

    async def disconnect_all(self) -> None:
        """Disable notifications and disconnect all devices gracefully."""
        self._shutting_down = True

        # Cancel all reconnect tasks
        for device_id, task in list(self._reconnect_tasks.items()):
            if not task.done():
                task.cancel()
        self._reconnect_tasks.clear()

        # Disconnect each device
        for device_id, client in list(self._clients.items()):
            try:
                if client.is_connected:
                    await client.stop_notify(UART_RX_CHAR_UUID)
            except Exception:
                pass
            try:
                if client.is_connected:
                    await client.disconnect()
            except Exception as e:
                logger.debug("[%s] Disconnect error (ignored): %s", device_id, e)
            self._connected[device_id] = False
            logger.info("[%s] Disconnected.", device_id)

        self._clients.clear()

    def get_rssi(self, device_id: str) -> int | None:
        """Return the most recently cached RSSI for a device.

        Note: Bleak gives RSSI per-advertisement, not per-connection.
        For connection RSSI, BlueZ's Device API would be needed.
        We return what we have; callers should treat absent RSSI gracefully.
        """
        return self._rssi_cache.get(device_id)

    def is_connected(self, device_id: str) -> bool:
        """Check if a device is currently connected."""
        return self._connected.get(device_id, False)

    def get_connected_ids(self) -> list[str]:
        """Return list of currently connected device_ids."""
        return [did for did, conn in self._connected.items() if conn]

    def get_device_config(self, device_id: str) -> dict | None:
        """Return the configuration dict for a device."""
        return self._device_cfgs.get(device_id)

    # ---- Internal ----

    def _make_notify_handler(self, device_id: str):
        """Create a Bleak notification callback closure for a specific device.

        The callback receives (sender_handle, data) from Bleak. We record
        the Pi receive timestamp and route by content type:

        - Text notifications starting with b"SYNC_ACK" → on_text callback
          (used for clock synchronization responses).
        - Everything else → on_packet callback (binary sensor data).

        SYNC_ACK format: "SYNC_ACK,<sync_id>,<device_timestamp_ms>\\r\\n"
        """

        def handler(_sender: int, data: bytearray) -> None:
            pi_receive_ns = time.monotonic_ns()
            try:
                # Detect text SYNC_ACK responses (clock sync protocol).
                # Binary sensor packets start with version=1 (0x01), never 'S'.
                if data.startswith(b"SYNC_ACK") and self._on_text is not None:
                    text = data.decode("utf-8", errors="replace").strip()
                    self._on_text(device_id, text, pi_receive_ns)
                else:
                    self._on_packet(device_id, data, pi_receive_ns)
            except Exception as e:
                logger.error("[%s] notification handler error: %s", device_id, e, exc_info=True)

        return handler

    async def _auto_reconnect_loop(self, device_id: str) -> None:
        """Background task: monitor connection and reconnect with exponential backoff.

        Args:
            device_id: Logical device ID to monitor.
        """
        backoff = 1.0  # seconds
        max_backoff = 30.0

        while not self._shutting_down:
            await asyncio.sleep(2.0)  # Check interval

            client = self._clients.get(device_id)
            if client is None or not client.is_connected:
                if self._shutting_down:
                    break

                logger.warning("[%s] Disconnected. Reconnecting in %.1fs...", device_id, backoff)
                await asyncio.sleep(backoff)

                if self._shutting_down:
                    break

                success = await self.connect_device(device_id)
                if success:
                    backoff = 1.0  # Reset backoff on success
                    logger.info("[%s] Reconnected successfully.", device_id)
                else:
                    backoff = min(backoff * 2, max_backoff)
                    logger.warning("[%s] Reconnect failed, next attempt in %.1fs.", device_id, backoff)

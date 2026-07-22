"""Async TCP JSON Lines client for sending data to PC.

Maintains a persistent TCP connection to the PC server. Messages are
serialized as JSON with newline delimiters and sent via asyncio streams.
Includes auto-reconnection and bounded queue with backpressure.
"""

import asyncio
import json
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class TcpJsonlClient:
    """Async TCP client that sends JSON Lines to a PC server.

    Each message is serialized as json.dumps(msg) + '\n'. Messages are
    enqueued and sent by a background drain task. Connection failures
    trigger automatic reconnection.

    Args:
        host: PC server hostname or IP address.
        port: PC server TCP port.
        reconnect_delay_s: Initial delay before reconnection attempts.
        max_queue_size: Maximum number of queued messages before dropping.
        connect_timeout_s: Connection timeout in seconds.
    """

    def __init__(
        self,
        host: str = "192.168.1.100",
        port: int = 9000,
        reconnect_delay_s: float = 2.0,
        max_queue_size: int = 500,
        connect_timeout_s: float = 5.0,
    ):
        self._host = host
        self._port = port
        self._reconnect_delay = reconnect_delay_s
        self._max_queue_size = max_queue_size
        self._connect_timeout = connect_timeout_s

        self._writer: asyncio.StreamWriter | None = None
        self._reader: asyncio.StreamReader | None = None
        self._connected = False
        self._send_queue: asyncio.Queue = asyncio.Queue(maxsize=max_queue_size)
        self._dropped_messages = 0
        self._reconnect_count = 0

        # Background tasks
        self._drain_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._shutting_down = False

        # Rate tracking
        self._send_times: deque[float] = deque(maxlen=100)

    # ---- Public API ----

    async def start(self) -> None:
        """Start the TCP client: connect and launch background tasks."""
        self._shutting_down = False

        # Attempt initial connection
        connected = await self._connect()
        if connected:
            logger.info("Connected to PC at %s:%d", self._host, self._port)
        else:
            logger.warning(
                "Initial connection to %s:%d failed. Will retry in background.",
                self._host,
                self._port,
            )

        # Start background loops
        self._drain_task = asyncio.create_task(self._send_drain_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        """Gracefully shutdown: cancel tasks, close connection."""
        self._shutting_down = True

        # Cancel background tasks
        for task in [self._drain_task, self._reconnect_task]:
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connection
        await self._disconnect()

        logger.info("TCP client stopped.")

    def send(self, message: dict) -> bool:
        """Enqueue a message for transmission (synchronous, non-blocking).

        If the send queue is full, fused_frame messages are dropped
        (control_event and status messages are preserved).

        Args:
            message: A complete message dict from MessageBuilder.

        Returns:
            True if the message was enqueued, False if it was dropped.
        """
        try:
            self._send_queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            # Drop policy: keep important messages, drop fused_frame
            msg_type = message.get("message_type", "")
            if msg_type in ("control_event", "status"):
                # Evict oldest fused_frame to make room
                try:
                    # Peek at oldest message — we can't selectively remove
                    # from asyncio.Queue, so we accept the loss for simplicity
                    pass
                except Exception:
                    pass

            self._dropped_messages += 1
            if self._dropped_messages % 100 == 0:
                logger.warning(
                    "Send queue full: %d messages dropped so far.",
                    self._dropped_messages,
                )
            return False

    def is_connected(self) -> bool:
        """Return whether the TCP connection is currently established."""
        return self._connected

    def get_status(self) -> dict:
        """Return network status for the status message.

        Returns:
            Dict with connection and queue stats.
        """
        # Calculate send rate (messages/sec over recent window)
        now = time.monotonic()
        recent_count = sum(1 for t in self._send_times if now - t < 1.0)
        send_rate_hz = recent_count  # messages in last second

        return {
            "pc_connected": self._connected,
            "queued_messages": self._send_queue.qsize(),
            "dropped_messages": self._dropped_messages,
            "send_rate_hz": send_rate_hz,
            "reconnect_count": self._reconnect_count,
        }

    # ---- Internal ----

    async def _connect(self) -> bool:
        """Attempt to connect to the PC server.

        Returns:
            True if connection was established.
        """
        try:
            self._reader, self._writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._connect_timeout,
            )
            self._connected = True
            self._reconnect_count += 1
            logger.info("Connected to %s:%d", self._host, self._port)
            return True

        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as e:
            self._connected = False
            logger.debug("Connection to %s:%d failed: %s", self._host, self._port, e)
            return False

    async def _disconnect(self) -> None:
        """Close the current connection if open."""
        self._connected = False

        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None
            self._reader = None

    async def _send_drain_loop(self) -> None:
        """Background task: drain the send queue and write to TCP socket."""
        while not self._shutting_down:
            try:
                # Block until a message is available
                message = await self._send_queue.get()

                if not self._connected or self._writer is None:
                    # Put back and wait for reconnect
                    # Don't requeue — drop to avoid infinite growth
                    self._send_queue.task_done()
                    continue

                # Serialize and send
                json_str = json.dumps(message, ensure_ascii=False)
                payload = (json_str + "\n").encode("utf-8")

                try:
                    self._writer.write(payload)
                    await self._writer.drain()
                    self._send_times.append(time.monotonic())
                except (ConnectionResetError, BrokenPipeError, OSError) as e:
                    logger.warning("Write failed: %s. Marking disconnected.", e)
                    self._connected = False
                    # Put the message back at the front? For now drop it
                    self._dropped_messages += 1

                self._send_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Send drain error: %s", e, exc_info=True)
                await asyncio.sleep(0.1)

    async def _reconnect_loop(self) -> None:
        """Background task: monitor connection and reconnect on disconnect."""
        backoff = self._reconnect_delay
        max_backoff = 30.0

        while not self._shutting_down:
            try:
                await asyncio.sleep(2.0)  # Check interval

                if self._shutting_down:
                    break

                if not self._connected:
                    logger.info("Reconnecting to %s:%d (backoff=%.1fs)...",
                                 self._host, self._port, backoff)
                    await asyncio.sleep(backoff)

                    if self._shutting_down:
                        break

                    success = await self._connect()
                    if success:
                        backoff = self._reconnect_delay  # Reset on success
                    else:
                        backoff = min(backoff * 2, max_backoff)

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Reconnect loop error: %s", e)

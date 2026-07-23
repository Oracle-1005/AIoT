"""Async TCP JSON Lines client for sending fused data to the PC backend.

Each message is serialized as json.dumps(msg, ensure_ascii=False) + '\\n'.
Messages are enqueued and drained by a background asyncio task.
Connection failures trigger automatic reconnection with exponential backoff.

Output message types (per the technical document):
  - fused_frame
  - microbit_control_event
  - status
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from collections import deque

logger = logging.getLogger(__name__)


class TcpJsonlClient:
    """Async TCP client that sends JSON Lines messages to a PC server.

    Args:
        host: PC server IP address.
        port: PC server TCP port.
        reconnect_delay_s: Initial delay before reconnection attempts.
        max_queue_size: Max queued messages before dropping.
        connect_timeout_s: Connection timeout in seconds.
    """

    def __init__(
        self,
        *,
        host: str = "192.168.1.100",
        port: int = 9000,
        reconnect_delay_s: float = 2.0,
        max_queue_size: int = 500,
        connect_timeout_s: float = 5.0,
    ) -> None:
        self._host = host
        self._port = port
        self._reconnect_delay = reconnect_delay_s
        self._connect_timeout = connect_timeout_s

        self._writer: asyncio.StreamWriter | None = None
        self._connected = False
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue_size)

        # Stats
        self._dropped_messages = 0
        self._reconnect_count = 0
        self._send_times: deque[float] = deque(maxlen=100)

        # Tasks
        self._drain_task: asyncio.Task | None = None
        self._reconnect_task: asyncio.Task | None = None
        self._shutting_down = False

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Connect and launch background drain + reconnect tasks."""
        self._shutting_down = False

        connected = await self._connect()
        if connected:
            logger.info("TCP connected to %s:%d", self._host, self._port)
        else:
            logger.warning(
                "Initial TCP connection to %s:%d failed — will retry.",
                self._host,
                self._port,
            )

        self._drain_task = asyncio.create_task(self._drain_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        """Gracefully shutdown: cancel tasks, close connection."""
        self._shutting_down = True

        for task in (self._drain_task, self._reconnect_task):
            if task and not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        await self._disconnect()
        logger.info("TCP client stopped.")

    # ── Public API ─────────────────────────────────────────────────────────

    def send(self, message: dict) -> bool:
        """Enqueue a message for transmission (non-blocking).

        If the queue is full, the message is dropped.

        Returns:
            True if enqueued, False if dropped.
        """
        try:
            self._send_queue.put_nowait(message)
            return True
        except asyncio.QueueFull:
            self._dropped_messages += 1
            if self._dropped_messages % 100 == 0:
                logger.warning(
                    "Send queue full: %d messages dropped so far.",
                    self._dropped_messages,
                )
            return False

    @property
    def is_connected(self) -> bool:
        return self._connected

    def get_status(self) -> dict:
        """Return network metrics for the status message."""
        now = time.monotonic()
        recent = sum(1 for t in self._send_times if now - t < 1.0)
        return {
            "pc_connected": self._connected,
            "queued_messages": self._send_queue.qsize(),
            "dropped_messages": self._dropped_messages,
            "send_rate_hz": recent,
            "reconnect_count": self._reconnect_count,
        }

    # ── Internal ───────────────────────────────────────────────────────────

    async def _connect(self) -> bool:
        """Attempt TCP connection to the PC server."""
        try:
            _reader, writer = await asyncio.wait_for(
                asyncio.open_connection(self._host, self._port),
                timeout=self._connect_timeout,
            )
            self._writer = writer
            self._connected = True
            self._reconnect_count += 1
            logger.info("Connected to %s:%d", self._host, self._port)
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
            logger.debug("Connection to %s:%d failed: %s", self._host, self._port, exc)
            self._connected = False
            return False

    async def _disconnect(self) -> None:
        """Close the current TCP connection."""
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await self._writer.wait_closed()
            except Exception:
                pass
            self._writer = None

    async def _drain_loop(self) -> None:
        """Background task: drain the send queue to the TCP socket."""
        while not self._shutting_down:
            try:
                message = await self._send_queue.get()

                if not self._connected or self._writer is None:
                    self._send_queue.task_done()
                    continue

                payload = (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
                self._writer.write(payload)
                await self._writer.drain()
                self._send_times.append(time.monotonic())
                self._send_queue.task_done()

            except asyncio.CancelledError:
                break
            except (ConnectionResetError, BrokenPipeError, OSError) as exc:
                logger.warning("TCP write failed: %s — marking disconnected.", exc)
                self._connected = False
                self._dropped_messages += 1
                self._send_queue.task_done()
            except Exception:
                logger.exception("TCP drain error")
                await asyncio.sleep(0.1)

    async def _reconnect_loop(self) -> None:
        """Background task: reconnect on disconnect with exponential backoff."""
        backoff = self._reconnect_delay
        max_backoff = 30.0

        while not self._shutting_down:
            try:
                await asyncio.sleep(2.0)  # Check every 2 s
                if self._shutting_down:
                    break

                if not self._connected:
                    logger.info(
                        "Reconnecting to %s:%d (backoff %.1f s)...",
                        self._host,
                        self._port,
                        backoff,
                    )
                    await asyncio.sleep(backoff)
                    if self._shutting_down:
                        break

                    if await self._connect():
                        backoff = self._reconnect_delay
                    else:
                        backoff = min(backoff * 2, max_backoff)

            except asyncio.CancelledError:
                break
            except Exception:
                logger.exception("Reconnect loop error")

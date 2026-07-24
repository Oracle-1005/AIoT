"""Async TCP JSON Lines client for sending fused data to the PC backend.

Each message is serialized as json.dumps(msg, ensure_ascii=False) + '\\n'.
Messages are enqueued and drained by a background asyncio task.
Connection failures trigger automatic reconnection with exponential backoff.

The connection is bidirectional: a background read loop receives downlink
JSONL messages from the backend (led_command etc., see INTERFACE_CONTRACT
§8.1) and dispatches them to the handler registered via
set_downlink_handler().

Output message types (per the technical document):
  - fused_frame
  - control_event
  - status
"""

from __future__ import annotations

import asyncio
import json
import logging
import socket
import time
from collections import deque
from collections.abc import Callable

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
        self._reader: asyncio.StreamReader | None = None
        self._connected = False
        self._send_queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=max_queue_size)
        self._downlink_handler: Callable[[dict], None] | None = None

        # Stats
        self._dropped_messages = 0
        self._reconnect_count = 0
        self._send_times: deque[float] = deque(maxlen=100)
        self._downlink_received = 0

        # Tasks
        self._drain_task: asyncio.Task | None = None
        self._read_task: asyncio.Task | None = None
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
        self._read_task = asyncio.create_task(self._read_loop())
        self._reconnect_task = asyncio.create_task(self._reconnect_loop())

    async def stop(self) -> None:
        """Gracefully shutdown: cancel tasks, close connection."""
        self._shutting_down = True

        for task in (self._drain_task, self._read_task, self._reconnect_task):
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

    def set_downlink_handler(self, handler: Callable[[dict], None] | None) -> None:
        """Register a callback for downlink JSONL messages from the backend.

        The handler is invoked from the read loop (same event loop) with the
        parsed message dict. Exceptions inside the handler are logged and
        swallowed so a bad consumer cannot kill the connection.
        """
        self._downlink_handler = handler

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
            "downlink_received": self._downlink_received,
        }

    # ── Internal ───────────────────────────────────────────────────────────

    async def _connect(self) -> bool:
        """Attempt TCP connection to the PC server."""
        # Close the previous transport before replacing it: this feeds EOF to
        # the old reader so a read loop awaiting it wakes up and picks up the
        # new connection (and the broken transport doesn't leak).
        old_writer = self._writer
        if old_writer is not None:
            self._writer = None
            self._reader = None
            try:
                old_writer.close()  # fire-and-forget; broken transports may hang wait_closed()
            except Exception:
                pass
        try:
            reader, writer = await asyncio.wait_for(
                asyncio.open_connection(
                    self._host,
                    self._port,
                    # Match pi_gateway's 1 MiB line cap (PI_GATEWAY_MAX_LINE_BYTES);
                    # the 64 KiB default would churn the connection on a large
                    # downlink message (e.g. a future led_config table).
                    limit=2**20,
                ),
                timeout=self._connect_timeout,
            )
            self._enable_keepalive(writer)
            self._reader = reader
            self._writer = writer
            self._connected = True
            self._reconnect_count += 1
            logger.info("Connected to %s:%d", self._host, self._port)
            return True
        except (asyncio.TimeoutError, ConnectionRefusedError, OSError) as exc:
            logger.debug("Connection to %s:%d failed: %s", self._host, self._port, exc)
            self._connected = False
            return False

    def _enable_keepalive(self, writer: asyncio.StreamWriter) -> None:
        """Enable TCP keepalive so a silently-dead peer (backend power loss,
        cable pull) is detected in ~25 s instead of the kernel's 15-30 min
        retransmission timeout. Without this the read loop pends forever and
        the pipeline reports pc_connected=true while uplinks vanish.

        Note: keepalive does not detect a wedged-but-ACKing backend process
        (kernel still answers) — that would need an app-level heartbeat,
        which the contract does not define yet.
        """
        sock = writer.get_extra_info("socket")
        if sock is None:
            return
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for opt_name, value in (("TCP_KEEPIDLE", 10), ("TCP_KEEPINTVL", 5), ("TCP_KEEPCNT", 3)):
                opt = getattr(socket, opt_name, None)
                if opt is not None:  # Linux + recent Windows; skip where absent
                    sock.setsockopt(socket.IPPROTO_TCP, opt, value)
        except OSError:
            logger.debug("TCP keepalive setup failed", exc_info=True)

    async def _disconnect(self) -> None:
        """Close the current TCP connection.

        wait_closed() is bounded: with an unflushed send buffer against a
        half-open peer it would block until the kernel TCP timeout (~15-30
        min on Linux), hanging graceful shutdown and skipping LED cleanup.
        """
        self._connected = False
        if self._writer:
            try:
                self._writer.close()
                await asyncio.wait_for(self._writer.wait_closed(), timeout=2.0)
            except Exception:
                try:
                    self._writer.transport.abort()
                except Exception:
                    pass
            self._writer = None
            self._reader = None

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

    async def _read_loop(self) -> None:
        """Background task: read downlink JSONL messages from the backend.

        The reader reference is re-fetched every iteration so the loop picks
        up the new connection after a reconnect. EOF or a read error marks
        the connection down; the reconnect loop re-establishes it.
        """
        while not self._shutting_down:
            try:
                reader = self._reader
                if not self._connected or reader is None:
                    await asyncio.sleep(0.5)
                    continue

                line = await reader.readline()
                if not line:
                    if self._connected:
                        logger.warning("TCP downlink EOF — server closed connection.")
                        self._connected = False
                    continue

                try:
                    message = json.loads(line.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                    logger.warning("Invalid downlink JSONL ignored: %s", exc)
                    continue
                if not isinstance(message, dict):
                    logger.warning("Downlink message is not an object — ignored.")
                    continue

                self._downlink_received += 1
                handler = self._downlink_handler
                if handler is not None:
                    try:
                        handler(message)
                    except Exception:
                        logger.exception("Downlink handler failed")

            except asyncio.CancelledError:
                break
            except (ConnectionResetError, BrokenPipeError, OSError, ValueError) as exc:
                # ValueError covers StreamReader limit overruns on readline().
                logger.warning("TCP read failed: %s — marking disconnected.", exc)
                self._connected = False
                await asyncio.sleep(0.1)
            except Exception:
                logger.exception("TCP read loop error")
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

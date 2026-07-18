"""TCP + JSON Lines gateway between the PC backend and Raspberry Pi.

The PC is the TCP server and the Pi is the client.  Uplink messages are one
JSON object per line.  The same connection is reused for downlink LED/system
commands.
"""

from __future__ import annotations

import json
import os
import socket
import threading
import time
from collections.abc import Callable
from typing import Any

PI_GATEWAY_ENABLED = os.getenv("AIOT_PI_GATEWAY_ENABLED", "1").lower() in {
    "1", "true", "yes", "on"
}
PI_GATEWAY_HOST = os.getenv("AIOT_PI_GATEWAY_HOST", "0.0.0.0")
PI_GATEWAY_PORT = int(os.getenv("AIOT_PI_GATEWAY_PORT", "9000"))
PI_GATEWAY_MAX_LINE_BYTES = int(os.getenv("AIOT_PI_GATEWAY_MAX_LINE_BYTES", "1048576"))

MessageHandler = Callable[[dict[str, Any], tuple[str, int]], None]


class PiGateway:
    """Single-Pi TCP server with reconnect support and newline framing."""

    def __init__(self) -> None:
        self._handler: MessageHandler | None = None
        self._server_socket: socket.socket | None = None
        self._client_socket: socket.socket | None = None
        self._client_address: tuple[str, int] | None = None
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._lock = threading.RLock()
        self._send_lock = threading.Lock()
        self._last_error: str | None = None
        self._connected_at: float | None = None
        self._last_received_at: float | None = None
        self._received_messages = 0
        self._sent_messages = 0

    def set_handler(self, handler: MessageHandler) -> None:
        self._handler = handler

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    @property
    def connected(self) -> bool:
        with self._lock:
            return self._client_socket is not None

    def start(self) -> bool:
        if not PI_GATEWAY_ENABLED or self.running:
            return False
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._serve, name="pi-gateway", daemon=True)
        self._thread.start()
        return True

    def stop(self) -> None:
        self._stop_event.set()
        self._close_client()
        with self._lock:
            server = self._server_socket
            self._server_socket = None
        if server is not None:
            try:
                server.close()
            except OSError:
                pass
        thread = self._thread
        if thread and thread.is_alive() and thread is not threading.current_thread():
            thread.join(timeout=2)

    def send(self, message: dict[str, Any]) -> bool:
        """Send one JSONL downlink message to the currently connected Pi."""
        if not isinstance(message, dict):
            raise TypeError("message must be a dict")
        encoded = (json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")
        with self._send_lock:
            with self._lock:
                client = self._client_socket
            if client is None:
                return False
            try:
                client.sendall(encoded)
                with self._lock:
                    self._sent_messages += 1
                return True
            except OSError as exc:
                self._set_error(f"send failed: {exc}")
                self._close_client()
                return False

    def status(self) -> dict[str, Any]:
        with self._lock:
            return {
                "enabled": PI_GATEWAY_ENABLED,
                "running": self.running,
                "connected": self._client_socket is not None,
                "listen_host": PI_GATEWAY_HOST,
                "listen_port": PI_GATEWAY_PORT,
                "client_address": list(self._client_address) if self._client_address else None,
                "connected_at": self._connected_at,
                "last_received_at": self._last_received_at,
                "received_messages": self._received_messages,
                "sent_messages": self._sent_messages,
                "last_error": self._last_error,
            }

    def _serve(self) -> None:
        try:
            server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((PI_GATEWAY_HOST, PI_GATEWAY_PORT))
            server.listen(1)
            server.settimeout(1.0)
            with self._lock:
                self._server_socket = server
                self._last_error = None
            print(f"[PiGateway] Listening on {PI_GATEWAY_HOST}:{PI_GATEWAY_PORT}")
        except OSError as exc:
            self._set_error(f"startup failed: {exc}")
            print(f"[PiGateway] Startup failed: {exc}")
            return

        while not self._stop_event.is_set():
            try:
                client, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            # Only one Pi is expected. A new connection replaces a stale one.
            self._close_client()
            client.settimeout(1.0)
            with self._lock:
                self._client_socket = client
                self._client_address = address
                self._connected_at = time.time()
                self._last_error = None
            print(f"[PiGateway] Pi connected from {address[0]}:{address[1]}")
            self._read_client(client, address)

        try:
            server.close()
        except OSError:
            pass

    def _read_client(self, client: socket.socket, address: tuple[str, int]) -> None:
        buffer = bytearray()
        while not self._stop_event.is_set():
            try:
                chunk = client.recv(65536)
            except socket.timeout:
                continue
            except OSError as exc:
                self._set_error(f"receive failed: {exc}")
                break
            if not chunk:
                break
            buffer.extend(chunk)
            if len(buffer) > PI_GATEWAY_MAX_LINE_BYTES and b"\n" not in buffer:
                self._set_error("incoming JSONL line exceeds maximum size")
                break

            while b"\n" in buffer:
                raw_line, _, remainder = buffer.partition(b"\n")
                buffer = bytearray(remainder)
                raw_line = raw_line.strip()
                if not raw_line:
                    continue
                if len(raw_line) > PI_GATEWAY_MAX_LINE_BYTES:
                    self._set_error("incoming JSONL line exceeds maximum size")
                    continue
                self._handle_line(raw_line, address)

        self._close_client(client)
        print(f"[PiGateway] Pi disconnected from {address[0]}:{address[1]}")

    def _handle_line(self, raw_line: bytes, address: tuple[str, int]) -> None:
        try:
            message = json.loads(raw_line.decode("utf-8"))
            if not isinstance(message, dict):
                raise ValueError("top-level JSON value must be an object")
            with self._lock:
                self._last_received_at = time.time()
                self._received_messages += 1
            if self._handler is not None:
                self._handler(message, address)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
            self._set_error(f"invalid uplink message: {exc}")
            print(f"[PiGateway] Ignored invalid JSONL message: {exc}")
        except Exception as exc:  # keep gateway alive if a downstream handler fails
            self._set_error(f"message handler failed: {exc}")
            print(f"[PiGateway] Message handler failed: {exc}")

    def _close_client(self, expected: socket.socket | None = None) -> None:
        with self._lock:
            client = self._client_socket
            if expected is not None and client is not expected:
                return
            self._client_socket = None
            self._client_address = None
            self._connected_at = None
        if client is not None:
            try:
                client.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            try:
                client.close()
            except OSError:
                pass

    def _set_error(self, message: str) -> None:
        with self._lock:
            self._last_error = message


pi_gateway = PiGateway()

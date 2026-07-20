#!/usr/bin/env python3
"""Mock PC Server — TCP JSON Lines receiver for testing.

Listens on 127.0.0.1:9000 and prints incoming messages with statistics.
Use this instead of a real PC server to verify the data pipeline.

Usage:
    # Terminal 1: Run the mock server
    python tests/mock_pc_server.py [--port 9000]

    # Terminal 2: Run the pipeline (or integration test)
    python tests/test_pipeline_mock.py
"""

import asyncio
import json
import argparse
import time
from collections import defaultdict
from datetime import datetime


class MockPcServer:
    """A simple TCP JSON Lines server for testing the RPi-to-PC pipeline.

    Tracks message counts by type, shows the last message of each type,
    and displays real-time statistics.
    """

    def __init__(self, host: str = "127.0.0.1", port: int = 9000):
        self.host = host
        self.port = port
        self._counts: dict[str, int] = defaultdict(int)
        self._last_messages: dict[str, dict] = {}
        self._start_time: float = 0.0
        self._total_bytes = 0

    async def start(self) -> None:
        """Start listening for connections."""
        self._start_time = time.time()
        server = await asyncio.start_server(
            self._handle_client, self.host, self.port
        )

        addr = server.sockets[0].getsockname()
        print(f"Mock PC Server listening on {addr[0]}:{addr[1]}")
        print("Waiting for Raspberry Pi connection...\n")
        print("─" * 60)

        async with server:
            await server.serve_forever()

    async def _handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Handle an incoming TCP connection."""
        addr = writer.get_extra_info("peername")
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Client connected: {addr}\n")

        buffer = b""
        try:
            while True:
                data = await reader.read(4096)
                if not data:
                    break

                self._total_bytes += len(data)
                buffer += data

                # Process complete JSON lines
                while b"\n" in buffer:
                    line, buffer = buffer.split(b"\n", 1)
                    if line.strip():
                        self._process_line(line.strip())

        except (ConnectionResetError, asyncio.CancelledError):
            pass
        finally:
            writer.close()
            await writer.wait_closed()
            print(f"\n[{datetime.now().strftime('%H:%M:%S')}] Client disconnected: {addr}")
            self._print_final_stats()

    def _process_line(self, line: bytes) -> None:
        """Parse and display a single JSON line message."""
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            print(f"  [PARSE ERROR] {line[:80]}...")
            return

        msg_type = msg.get("message_type", "unknown")
        self._counts[msg_type] += 1
        self._last_messages[msg_type] = msg

        # ── Display based on message type ──────────────────────────
        total = sum(self._counts.values())

        if msg_type == "fused_frame":
            # Print every 25th fused_frame to avoid flooding
            if self._counts["fused_frame"] % 25 == 0:
                ts = msg.get("timestamps", {})
                fusion = msg.get("fusion", {})
                cam = msg.get("camera", {})
                mbs = msg.get("microbits", [])

                fusion_time_ms = ts.get("fusion_target_timestamp_ns", 0) / 1_000_000
                hands = cam.get("hands", [])
                hand_info = ", ".join(
                    f"{h.get('handedness','?')}(conf={h.get('confidence',0):.2f})"
                    for h in hands
                ) if hands else "none"

                mb_info = ", ".join(
                    f"{m.get('device_id','?')}=({'✓' if m.get('valid') else '✗'})"
                    for m in mbs
                )

                print(f"  [fused_frame #{self._counts['fused_frame']:5d}] "
                      f"t={fusion_time_ms:8.1f}ms  hands=[{hand_info}]  "
                      f"MB=[{mb_info}]  fusion_valid={fusion.get('valid')}")

        elif msg_type == "control_event":
            ev = msg.get("event", {})
            mc = msg.get("music_control", {})
            print(f"\n  *** control_event: {ev.get('type')} "
                  f"hand={ev.get('hand')}  confidence={ev.get('confidence',0):.2f}  "
                  f"strength={ev.get('strength',0):.2f}")
            print(f"      bpm={mc.get('estimated_bpm',0):.1f}  "
                  f"volume={mc.get('volume',0):.2f}  "
                  f"intensity={mc.get('intensity',0):.2f}")

        elif msg_type == "status":
            # Print every status message
            ts = msg.get("timestamps", {})
            unix_s = ts.get("pi_unix_time_ns", 0) / 1_000_000_000
            time_str = datetime.fromtimestamp(unix_s).strftime('%H:%M:%S') if unix_s > 0 else "?"
            cam_s = msg.get("camera", {})
            net = msg.get("network", {})
            mbs = msg.get("microbits", {})

            print(f"  [status @{time_str}] "
                  f"cam={'✓' if cam_s.get('connected') else '✗'} "
                  f"left={'✓' if mbs.get('left',{}).get('connected') else '✗'} "
                  f"right={'✓' if mbs.get('right',{}).get('connected') else '✗'} "
                  f"pc={'✓' if net.get('pc_connected') else '✗'} "
                  f"dropped={net.get('dropped_messages',0)}  "
                  f"send_rate={net.get('send_rate_hz',0):.1f}Hz")

        # Periodic summary
        if total % 100 == 0 and total > 0:
            elapsed = time.time() - self._start_time
            rate = total / elapsed if elapsed > 0 else 0
            print(f"\n── Stats: {total} msgs in {elapsed:.1f}s ({rate:.1f} msg/s) "
                  f"| {dict(self._counts)} ──\n")

    def _print_final_stats(self) -> None:
        """Print final statistics on disconnect."""
        elapsed = time.time() - self._start_time
        total = sum(self._counts.values())
        rate = total / elapsed if elapsed > 0 else 0

        print("\n" + "=" * 60)
        print(f"  FINAL STATISTICS ({elapsed:.1f} seconds)")
        print("=" * 60)
        for msg_type, count in sorted(self._counts.items()):
            pct = count / max(total, 1) * 100
            print(f"  {msg_type:25s}: {count:6d} ({pct:5.1f}%)")
        print(f"  {'TOTAL':25s}: {total:6d}")
        print(f"  {'Data received':25s}: {self._total_bytes/1024:.1f} KB")
        print(f"  {'Avg rate':25s}: {rate:.1f} msg/s")
        print("=" * 60)


# ── Entry Point ────────────────────────────────────────────────────────────

def parse_args():
    parser = argparse.ArgumentParser(
        description="Mock PC Server — receives TCP JSON Lines from Raspberry Pi"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Listen address (default: 127.0.0.1)")
    parser.add_argument("--port", "-p", type=int, default=9000, help="Listen port (default: 9000)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    server = MockPcServer(host=args.host, port=args.port)
    try:
        asyncio.run(server.start())
    except KeyboardInterrupt:
        print("\nServer stopped.")

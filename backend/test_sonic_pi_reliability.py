"""Deterministic tests for Sonic Pi OSC retry, ACK and idempotency state."""

from __future__ import annotations

import time

import sonic_pi


class FakeOscClient:
    def __init__(self) -> None:
        self.messages: list[tuple[str, list]] = []

    def send_message(self, path: str, args: list) -> None:
        self.messages.append((path, list(args)))


def main() -> None:
    adapter = sonic_pi.SonicPiOscAdapter()
    adapter.enabled = True
    adapter._client = FakeOscClient()
    client = adapter._client

    assert adapter.send_style("next", command_id="reliable-style-1")
    assert client.messages == [
        ("/conductor/style", ["reliable-style-1", "next"]),
    ]
    pending = adapter.command_status("reliable-style-1")
    assert pending["status"] == "pending"
    assert pending["attempts"] == 1

    adapter._retry_pending(pending["sent_at"] + 0.13)
    assert len(client.messages) == 2
    assert client.messages[-1] == client.messages[0]

    adapter._handle_ack(
        "/music/ack",
        "reliable-style-1",
        "style:tropical_house",
    )
    delivery = adapter.command_status("reliable-style-1")
    assert delivery["status"] == "acked"
    assert delivery["attempts"] == 2
    assert delivery["result"] == "style:tropical_house"
    assert adapter.status()["pending_commands"] == 0
    acked_commands = adapter.status()["acked_commands"]
    adapter._handle_ack(
        "/music/ack",
        "reliable-style-1",
        "style:tropical_house",
    )
    assert adapter.status()["acked_commands"] == acked_commands

    # Repeating the same HTTP/client command id must not emit another datagram.
    assert adapter.send_style("next", command_id="reliable-style-1")
    assert len(client.messages) == 2

    # Realtime scalar updates are last-value-wins while awaiting ACK.
    assert adapter.send_bpm(100, command_id="bpm-old")
    assert adapter.send_bpm(104, command_id="bpm-new")
    assert adapter.command_status("bpm-old")["status"] == "superseded"
    assert adapter.command_status("bpm-new")["status"] == "pending"
    messages_before_stale_retry = len(client.messages)
    old_bpm = adapter.command_status("bpm-old")
    adapter._pending_commands["bpm-new"]["next_retry_at"] = (
        old_bpm["sent_at"] + 1.0
    )
    adapter._retry_pending(old_bpm["sent_at"] + 0.13)
    assert len(client.messages) == messages_before_stale_retry

    new_bpm = adapter.command_status("bpm-new")
    adapter._retry_pending(new_bpm["sent_at"] + sonic_pi.SONIC_PI_ACK_TIMEOUT + 0.01)
    assert adapter.command_status("bpm-new")["status"] == "timed_out"
    assert adapter.status()["timed_out_commands"] == 1

    # Heartbeat distinguishes feedback-only health from command input health.
    adapter._last_ping_id = "ping-test"
    adapter._last_ping_at = time.time() - 0.01
    adapter._handle_pong("/music/pong", "ping-test", "epoch")
    assert adapter.status()["command_channel_ready"] is True
    assert adapter.status()["last_ping_latency_ms"] is not None
    adapter._handle_output("/music/output", "internal")
    assert adapter.status()["audio_output_mode"] == "internal"

    collision = adapter.send_style(
        "previous",
        command_id="reliable-style-1",
    )
    assert collision is False
    assert "command_id collision" in str(adapter.status()["last_error"])

    print("Sonic Pi reliability tests passed.")


if __name__ == "__main__":
    main()

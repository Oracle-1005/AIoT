#!/usr/bin/env python3
"""Transport-level tests for the micro:bit Radio USB gateway."""

from __future__ import annotations

import struct
import sys
import unittest
from pathlib import Path

_HARDWARE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_HARDWARE))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "esp32_ble_gateway_to_Pi"))
sys.path.insert(0, str(_HARDWARE / "raspberry_pi" / "microbit_to_Pi"))

from fusion_pipeline.radio_serial_adapter import RadioSerialAdapter


class RadioSerialAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.raw: list[dict] = []
        self.samples = []
        self.events: list[dict] = []
        self.adapter = RadioSerialAdapter(
            device="/dev/test-radio-gateway",
            on_raw_sensor_state=self.raw.append,
            on_sensor_state=self.samples.append,
            on_control_event=self.events.append,
        )

    def test_sensor_uses_existing_processing_path(self) -> None:
        payload = struct.pack(
            "<BHIhhhhh",
            0x01,
            42,
            123_456,
            100,
            -200,
            980,
            12,
            -8,
        )
        self.adapter._handle_serial_line(
            f"GW1,5000,-55,1234,{payload.hex()}".encode()
        )

        self.assertEqual(len(self.raw), 1)
        self.assertEqual(self.raw[0]["transport"], "microbit_radio_usb")
        self.assertEqual(self.raw[0]["gateway"]["sender_serial"], 1234)
        self.assertEqual(len(self.samples), 1)
        self.assertEqual(self.samples[0].source, "left")
        self.assertEqual(self.samples[0].sample_sequence, 42)
        self.assertEqual(self.samples[0].ble_rssi, -55)

    def test_repeated_control_event_is_deduplicated(self) -> None:
        for repeat_index in (0, 1, 2):
            payload = struct.pack(
                "<BHIBBBB",
                0x06,
                7,
                456_000,
                0x03,
                100,
                repeat_index,
                7,
            )
            self.adapter._handle_serial_line(
                f"GW1,6000,-60,4321,{payload.hex()}".encode()
            )

        self.assertEqual(len(self.events), 1)
        self.assertEqual(
            self.events[0]["payload"]["event"]["type"],
            "stop",
        )
        self.assertEqual(
            self.events[0]["payload"]["gateway"]["transport"],
            "microbit_radio_usb",
        )

    def test_bad_line_is_counted_and_dropped(self) -> None:
        self.adapter._handle_serial_line(b"GW1,not-a-time,-50,1,00")
        status = self.adapter.get_status()
        self.assertEqual(status["serial_parse_errors"], 1)
        self.assertEqual(status["serial_received_lines"], 0)


if __name__ == "__main__":
    unittest.main()

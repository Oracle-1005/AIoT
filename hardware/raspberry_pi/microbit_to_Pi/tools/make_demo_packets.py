"""无需 BLE 硬件即可查看两个合法示例包的解析结果。"""

from __future__ import annotations

import json
import time

from microbit_receiver.protocol import (
    CONTROL_EVENT_STRUCT,
    SENSOR_STATE_STRUCT,
    Hand,
    parse_packet,
)


def main() -> None:
    packets = [
        (Hand.LEFT, SENSOR_STATE_STRUCT.pack(0x01, 1821, 73452, 112, -934, 287, -18, 42)),
        (Hand.RIGHT, CONTROL_EVENT_STRUCT.pack(0x06, 215, 82411, 0x03, 100, 0, 3)),
    ]
    for hand, payload in packets:
        parsed = parse_packet(
            payload,
            expected_hand=hand,
            pi_rx_monotonic_ns=time.monotonic_ns(),
        )
        print(json.dumps(parsed.to_dict(), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

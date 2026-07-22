"""Quick BLE scan to find Micro:bit devices."""
import asyncio
from bleak import BleakScanner

async def main():
    print("Scanning for BLE devices (10s)...")
    devices = await BleakScanner.discover(timeout=10, return_adv=True)
    print(f"\nFound {len(devices)} device(s):\n")
    for address, (d, adv) in devices.items():
        name = d.name or getattr(adv, 'local_name', '') or "(no name)"
        rssi = getattr(adv, 'rssi', -999)
        is_mb = "micro:bit" in name.lower() or "bbc" in name.lower()
        marker = " <-- MICRO:BIT" if is_mb else ""
        print(f"  RSSI={rssi:4d}  {name:35s}  [{address}]{marker}")
        if is_mb:
            uuids = getattr(adv, 'service_uuids', [])
            print(f"           Service UUIDs: {uuids}")
    if not devices:
        print("  No devices found! Make sure Micro:bit is powered on and in pairing mode.")
        print("  (Press reset button 3x quickly on Micro:bit to enter BLE pairing mode)")

asyncio.run(main())

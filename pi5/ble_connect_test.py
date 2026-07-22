"""Quick BLE connect test to Micro:bit — read NUS UART data."""
import asyncio
from bleak import BleakClient, BleakScanner

NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"  # notify
NUS_RX = "6E400003-B5A3-F393-E0A9-E50E24DCCA9E"  # write
TARGET_NAME = "BBC micro:bit"

def notify_handler(sender, data):
    text = data.decode("utf-8", errors="replace").strip()
    print(f"  >>> {text}")

async def main():
    print("Scanning for Micro:bit...")
    device = await BleakScanner.find_device_by_name(TARGET_NAME, timeout=10)
    if not device:
        # Try partial match
        devices = await BleakScanner.discover(timeout=10, return_adv=True)
        for addr, (d, adv) in devices.items():
            name = d.name or ""
            if "micro:bit" in name.lower():
                device = d
                break
    if not device:
        print("No Micro:bit found!")
        return

    print(f"Found: {device.name} [{device.address}]")
    print(f"Connecting...")

    async with BleakClient(device.address, timeout=15) as client:
        print(f"Connected: {client.is_connected}")
        services = client.services
        for svc in services:
            print(f"  Service: {svc.uuid}")
            for char in svc.characteristics:
                props = char.properties
                print(f"    Char: {char.uuid} props={props}")

        # Try to subscribe to NUS TX
        try:
            await client.start_notify(NUS_TX, notify_handler)
            print("Subscribed to NUS TX! Waiting for data (15s)...")
            await asyncio.sleep(15)
            await client.stop_notify(NUS_TX)
        except Exception as e:
            print(f"NUS TX subscribe failed: {e}")

asyncio.run(main())

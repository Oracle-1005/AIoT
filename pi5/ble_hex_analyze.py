"""Analyze raw BLE UART data from Micro:bit — show hex and try to decode."""
import asyncio
from bleak import BleakClient, BleakScanner

NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
TARGET_NAME = "BBC micro:bit"

count = [0]

def notify_handler(sender, data):
    count[0] += 1
    hex_str = data.hex(' ')
    # Try to decode as UTF-8
    try:
        text = data.decode('utf-8')
    except:
        text = "(not UTF-8)"
    # Try to decode as ASCII
    try:
        ascii_text = data.decode('ascii')
    except:
        ascii_text = "(not ASCII)"
    print(f"#{count[0]:04d}  len={len(data):3d}  hex=[{hex_str[:60]}]  text=[{text[:80]}]")
    if count[0] >= 20:
        raise KeyboardInterrupt()  # stop after 20 samples

async def main():
    print("Scanning for Micro:bit...")
    device = await BleakScanner.find_device_by_name(TARGET_NAME, timeout=10)
    if not device:
        print("Not found!")
        return
    print(f"Found: {device.name} [{device.address}]")
    async with BleakClient(device.address, timeout=15) as client:
        print(f"Connected: {client.is_connected}")
        await client.start_notify(NUS_TX, notify_handler)
        print("Subscribed! Waiting for 20 packets...\n")
        try:
            await asyncio.sleep(30)
        except KeyboardInterrupt:
            pass
        await client.stop_notify(NUS_TX)
        print(f"\nTotal packets: {count[0]}")

asyncio.run(main())

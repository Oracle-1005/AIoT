"""Connect to ONE Micro:bit and verify text data format."""
import asyncio
from bleak import BleakClient, BleakScanner

NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

async def main():
    # Scan
    print("Scanning...")
    devices = await BleakScanner.discover(timeout=8, return_adv=True)
    mbs = []
    for addr, (d, adv) in devices.items():
        name = d.name or getattr(adv, 'local_name', '') or ''
        if 'micro:bit' in name.lower():
            rssi = getattr(adv, 'rssi', -999)
            mbs.append((rssi, addr, name))
    mbs.sort(reverse=True)
    if not mbs:
        print("No Micro:bit found!")
        return

    # Connect to strongest
    rssi, addr, name = mbs[0]
    print(f"Connecting to: {name} [{addr}] RSSI={rssi}\n")

    count = [0]
    def handler(sender, data):
        count[0] += 1
        try:
            text = data.decode('utf-8').strip()
            print(f"#{count[0]:3d}  {text}")
        except:
            hex_str = data[:24].hex(' ')
            print(f"#{count[0]:3d}  BINARY(len={len(data)}) [{hex_str}]")
        if count[0] >= 15:
            raise KeyboardInterrupt()

    try:
        async with BleakClient(addr, timeout=15) as c:
            print(f"Connected: {c.is_connected}")
            await c.start_notify(NUS_TX, handler)
            print("Subscribed! Reading data...\n")
            await asyncio.sleep(10)
            await c.stop_notify(NUS_TX)
            print(f"\nTotal: {count[0]} packets")
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())

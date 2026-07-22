import asyncio
from bleak import BleakClient, BleakScanner

NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

async def main():
    print("Fast scan 5s...")
    devices = await BleakScanner.discover(timeout=5, return_adv=True)
    mbs = []
    for addr, (d, adv) in devices.items():
        name = d.name or ''
        if 'micro:bit' in name.lower():
            rssi = getattr(adv, 'rssi', -999)
            mbs.append((rssi, addr, name))
    mbs.sort(reverse=True)
    print(f"Found {len(mbs)} Micro:bit(s)")
    for r, a, n in mbs:
        print(f"  {n} [{a}] RSSI={r}")

    if not mbs:
        print("No Micro:bit! Triple-click reset to re-enter BLE mode.")
        return

    rssi, addr, name = mbs[0]
    print(f"\nConnecting to [{addr}]...")
    try:
        async with BleakClient(addr, timeout=20) as c:
            print(f"Connected: {c.is_connected}")
            count = [0]
            def handler(s, data):
                count[0] += 1
                try:
                    text = data.decode().strip()
                    print(f"  #{count[0]} [{text}]")
                except:
                    print(f"  #{count[0]} BIN len={len(data)}: {data[:30].hex(' ')}")
                if count[0] >= 8:
                    raise KeyboardInterrupt()
            await c.start_notify(NUS_TX, handler)
            print("Reading data...\n")
            await asyncio.sleep(10)
    except KeyboardInterrupt:
        pass
    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())

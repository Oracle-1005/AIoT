"""Connect to 2 strongest Micro:bits and verify data format."""
import asyncio
from bleak import BleakClient, BleakScanner

NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"

def make_handler(name):
    count = [0]
    def handler(sender, data):
        count[0] += 1
        try:
            text = data.decode('utf-8').strip()
            print(f"  [{name}] #{count[0]:3d}  {text[:80]}")
        except:
            print(f"  [{name}] #{count[0]:3d}  BINARY len={len(data)} hex={data[:20].hex(' ')}")
        if count[0] >= 10:
            raise KeyboardInterrupt()
    return handler

async def connect_one(addr, name):
    try:
        async with BleakClient(addr, timeout=15) as c:
            print(f"  {name} [{addr}] connected: {c.is_connected}")
            await c.start_notify(NUS_TX, make_handler(name))
            await asyncio.sleep(20)
    except Exception as e:
        print(f"  {name} ERROR: {e}")

async def main():
    # Quick scan for top 2 by RSSI
    print("Scanning...")
    devices = await BleakScanner.discover(timeout=8, return_adv=True)
    mbs = []
    for addr, (d, adv) in devices.items():
        name = d.name or getattr(adv, 'local_name', '') or ''
        if 'micro:bit' in name.lower():
            rssi = getattr(adv, 'rssi', -999)
            mbs.append((rssi, addr, name))
    mbs.sort(reverse=True)
    top2 = mbs[:2]
    print(f"Top 2: {[(a, r) for r, a, _ in top2]}")

    # Connect to both
    tasks = [connect_one(addr, f'MB{i+1}') for i, (_, addr, _) in enumerate(top2)]
    await asyncio.gather(*tasks)

asyncio.run(main())

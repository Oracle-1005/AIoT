import asyncio
from bleak import BleakScanner
async def main():
    print("Scanning 10s...")
    devices = await BleakScanner.discover(timeout=10, return_adv=True)
    found = []
    for addr, (d, adv) in devices.items():
        name = d.name or getattr(adv, 'local_name', '') or ''
        if 'micro:bit' in name.lower() or 'bbc' in name.lower():
            rssi = getattr(adv, 'rssi', -999)
            uuids = [str(u) for u in getattr(adv, 'service_uuids', [])]
            nus = any('6e400001' in u for u in uuids)
            found.append((name, addr, rssi, nus, uuids))
    print(f'Found {len(found)} Micro:bit(s):')
    for name, addr, rssi, nus, uuids in found:
        print(f'  {name}  [{addr}]  RSSI={rssi}  NUS={nus}')
asyncio.run(main())

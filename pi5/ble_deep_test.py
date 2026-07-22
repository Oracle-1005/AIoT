"""Deep test: scan, connect, list ALL GATT services and subscribe to data."""
import asyncio, sys
from bleak import BleakClient, BleakScanner

async def main():
    print("=== Step 1: Scan ===")
    devices = await BleakScanner.discover(timeout=6, return_adv=True)
    mbs = []
    for addr, (d, adv) in devices.items():
        if d.name and 'micro:bit' in d.name.lower():
            rssi = getattr(adv, 'rssi', -999)
            uuids = [str(u) for u in getattr(adv, 'service_uuids', [])]
            mbs.append((rssi, addr, d.name, uuids))

    mbs.sort(reverse=True)
    print(f"Found {len(mbs)} Micro:bit(s):")
    for r, a, n, uuids in mbs:
        print(f"  {n} [{a}] RSSI={r} UUIDs={uuids[:3]}")

    if not mbs:
        print("NO Micro:bit found! Triple-click reset to re-enter BLE mode.")
        return

    target_rssi, target_addr, target_name, _ = mbs[0]
    print(f"\n=== Step 2: Connect to {target_name} [{target_addr}] ===")

    try:
        async with BleakClient(target_addr, timeout=20) as c:
            print(f"Connected: {c.is_connected}")
            print(f"MTU: {c.mtu_size}")

            print(f"\n=== Step 3: Service Discovery ===")
            svcs = c.services
            if svcs:
                print(f"Services: {len(svcs)}")
                for s in svcs:
                    print(f"\n  Service: {s.uuid}")
                    if s.description:
                        print(f"    Description: {s.description}")
                    for ch in s.characteristics:
                        print(f"    Char: {ch.uuid} props={ch.properties}")
                        for desc in ch.descriptors:
                            print(f"      Desc: {desc.uuid}")
            else:
                print("WARNING: No services! Trying manual discovery via get_services()...")
                svcs = await c.get_services()
                if svcs:
                    print("Services discovered via get_services():")
                    for s in svcs:
                        print(f"  {s.uuid}")
                        for ch in s.characteristics:
                            print(f"    {ch.uuid} props={ch.properties}")
                else:
                    print("Still no services. This firmware may not have BLE UART.")

            # Step 4: If NUS found, subscribe
            NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
            count = [0]
            def handler(s, data):
                count[0] += 1
                try:
                    text = data.decode('utf-8').strip()
                    print(f"  DATA #{count[0]} TEXT: [{text}]")
                except:
                    hx = data.hex(' ')
                    print(f"  DATA #{count[0]} BIN len={len(data)}: {hx}")
                if count[0] >= 10:
                    raise KeyboardInterrupt()

            try:
                await c.start_notify(NUS_TX, handler)
                print(f"\n=== Step 4: Subscribed to NUS TX ===")
                print("Waiting for data...\n")
                await asyncio.sleep(12)
            except KeyboardInterrupt:
                pass
            except Exception as e:
                print(f"Subscribe failed: {e}")
                print("Trying known characteristics...")
                # Try any notify-capable characteristic
                for s in (svcs or []):
                    for ch in s.characteristics:
                        if 'notify' in ch.properties or 'indicate' in ch.properties:
                            print(f"  Trying notify on {ch.uuid}...")
                            try:
                                await c.start_notify(ch.uuid, handler)
                                print(f"  Subscribed! Waiting...")
                                await asyncio.sleep(8)
                            except Exception as e2:
                                print(f"  Failed: {e2}")

    except Exception as e:
        print(f"Error: {e}")

asyncio.run(main())

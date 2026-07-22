"""Connect to Micro:bit and subscribe to the built-in Accelerometer Service.
This bypasses the UART service entirely — uses standard micro:bit GATT.
"""
import asyncio
from bleak import BleakClient, BleakScanner
import struct

# Micro:bit standard Accelerometer Service (part of the BLE profile, NOT UART)
ACCEL_SVC_UUID = "E95D93AF-251D-470A-A062-FA1922DFA9A8"
ACCEL_DATA_CHAR = "E95DB84C-251D-470A-A062-FA1922DFA9A8"  # read + notify
ACCEL_PERIOD_CHAR = "E95D5404-251D-470A-A062-FA1922DFA9A8"  # write

async def main():
    print("=== Scan 6s ===")
    devices = await BleakScanner.discover(timeout=6, return_adv=True)
    mbs = []
    for addr, (d, adv) in devices.items():
        if d.name and 'micro:bit' in d.name.lower():
            rssi = getattr(adv, 'rssi', -999)
            mbs.append((rssi, addr, d.name))
    mbs.sort(reverse=True)

    if not mbs:
        print("NO Micro:bit found. Triple-click reset!")
        return

    print(f"Found {len(mbs)}:")
    for r, a, n in mbs:
        print(f"  {n} [{a}] RSSI={r}")

    target_rssi, target_addr, target_name = mbs[0]
    print(f"\n=== Connecting to {target_name} [{target_addr}] ===")

    try:
        async with BleakClient(target_addr, timeout=20) as c:
            print(f"Connected: {c.is_connected}")

            # List all services
            print(f"\n=== Services ===")
            has_accel = False
            has_nus = False
            notify_chars = []

            for s in c.services:
                print(f"  {s.uuid}")
                for ch in s.characteristics:
                    print(f"    {ch.uuid} props={ch.properties}")
                    if 'notify' in ch.properties or 'indicate' in ch.properties:
                        notify_chars.append(ch.uuid)
                    if ch.uuid == ACCEL_DATA_CHAR:
                        has_accel = True
                    if '6E400002' in ch.uuid:
                        has_nus = True

            print(f"\nHas Accelerometer Service: {has_accel}")
            print(f"Has NUS TX: {has_nus}")
            print(f"All notify chars: {len(notify_chars)}")

            # Try subscribing to accelerometer data
            if has_accel:
                print(f"\n=== Subscribing to Accelerometer Data ===")
                # First set period to 20ms (50Hz)
                try:
                    period_bytes = struct.pack('<H', 20)  # milliseconds
                    await c.write_gatt_char(ACCEL_PERIOD_CHAR, period_bytes, response=False)
                    print("Set period to 20ms")
                except Exception as e:
                    print(f"Set period: {e}")

                count = [0]
                def accel_handler(s, data):
                    count[0] += 1
                    # Micro:bit accelerometer data: 3 signed 16-bit little-endian (x, y, z)
                    # Values in mg (milli-g)
                    if len(data) >= 6:
                        try:
                            x, y, z = struct.unpack('<hhh', data[:6])
                            print(f"  ACCEL #{count[0]}: x={x:6d} y={y:6d} z={z:6d} mg")
                        except:
                            print(f"  ACCEL #{count[0]} BIN len={len(data)}: {data[:20].hex(' ')}")
                    else:
                        print(f"  ACCEL #{count[0]} BIN len={len(data)}: {data.hex(' ')}")
                    if count[0] >= 15:
                        raise KeyboardInterrupt()

                try:
                    await c.start_notify(ACCEL_DATA_CHAR, accel_handler)
                    print("Subscribed! Reading data...\n")
                    await asyncio.sleep(15)
                except KeyboardInterrupt:
                    pass

            elif has_nus:
                print(f"\n=== NUS found but Accel Service missing ===")
                print("Subscribing to NUS TX instead...")
                NUS_TX = "6E400002-B5A3-F393-E0A9-E50E24DCCA9E"
                count = [0]
                def handler(s, data):
                    count[0] += 1
                    try:
                        text = data.decode().strip()
                        print(f"  #{count[0]}: [{text}]")
                    except:
                        print(f"  #{count[0]} BIN len={len(data)}: {data.hex(' ')}")
                    if count[0] >= 15:
                        raise KeyboardInterrupt()
                await c.start_notify(NUS_TX, handler)
                print("Reading...\n")
                await asyncio.sleep(15)
            else:
                print("\nNEITHER Accel Service NOR NUS found!")
                print("This firmware doesn't have the Bluetooth extension.")
                print("Trying any notify-capable characteristic...")

                count = [0]
                def any_handler(s, data):
                    count[0] += 1
                    print(f"  #{count[0]} char={s.uuid} len={len(data)}: {data[:30].hex(' ')}")
                    if count[0] >= 10:
                        raise KeyboardInterrupt()

                for ch_uuid in notify_chars[:3]:
                    try:
                        print(f"  Trying {ch_uuid}...")
                        await c.start_notify(ch_uuid, any_handler)
                        await asyncio.sleep(5)
                    except Exception as e:
                        print(f"  Failed: {e}")

    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")

asyncio.run(main())

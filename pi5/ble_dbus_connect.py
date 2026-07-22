"""Direct BlueZ D-Bus connect + GATT discovery for Micro:bit.
Uses pydbus to bypass bleak's abstraction layer."""
import sys
sys.path.insert(0, '/usr/lib/python3/dist-packages')
from pydbus import SystemBus
from gi.repository import GLib
import time

bus = SystemBus()
adapter = bus.get("org.bluez", "/org/bluez/hci0")

# Scan to find device
print("Starting discovery...")
adapter.SetDiscoveryFilter({"Transport": GLib.Variant("s", "le")})
adapter.StartDiscovery()
time.sleep(6)
adapter.StopDiscovery()
print("Discovery stopped")

# Find Micro:bit
mgr = adapter.GetManagedObjects()
target_path = None
target_addr = None

for path, ifaces in mgr.items():
    dev = ifaces.get("org.bluez.Device1")
    if dev:
        name = dev.get("Name", "")
        if "micro:bit" in name.lower():
            addr = dev.get("Address", "")
            rssi = dev.get("RSSI", -999)
            connected = dev.get("Connected", False)
            print(f"  {name} [{addr}] RSSI={rssi} Connected={connected}")
            if not target_path and "petup" in name.lower():
                target_path = path
                target_addr = addr

if not target_path:
    # Pick the first one
    for path, ifaces in mgr.items():
        dev = ifaces.get("org.bluez.Device1")
        if dev and "micro:bit" in dev.get("Name", "").lower():
            target_path = path
            target_addr = dev.get("Address", "")
            break

if not target_path:
    print("No Micro:bit found!")
    sys.exit(1)

print(f"\nTarget: {target_addr} ({target_path})")

# Connect
device = bus.get("org.bluez", target_path)
print("Calling Connect()...")
try:
    device.Connect()
    print("Connect() returned OK")
except Exception as e:
    print(f"Connect() exception: {e}")

# Wait for services
print("Waiting for ServicesResolved...")
for i in range(10):
    time.sleep(1)
    try:
        props = device.GetAll("org.bluez.Device1")
        connected = props.get("Connected", False)
        svc_resolved = props.get("ServicesResolved", False)
        uuids = props.get("UUIDs", [])
        print(f"  t={i+1}s Connected={connected} ServicesResolved={svc_resolved} UUIDs={uuids[:3]}")
        if not connected:
            print("  DISCONNECTED!")
            break
        if svc_resolved:
            break
    except Exception as e:
        print(f"  t={i+1}s Error: {e}")

# List GATT
print(f"\n=== GATT Services ===")
mgr = adapter.GetManagedObjects()

# Collect services and characteristics
services = {}
for path, ifaces in sorted(mgr.items()):
    if not path.startswith(target_path + "/service"):
        continue

    svc = ifaces.get("org.bluez.GattService1")
    char = ifaces.get("org.bluez.GattCharacteristic1")

    if svc:
        svc_uuid = svc.get("UUID", "")
        services[path] = {"uuid": svc_uuid, "chars": []}
        print(f"\nSVC: {svc_uuid}")

    if char:
        char_uuid = char.get("UUID", "")
        flags = char.get("Flags", [])
        print(f"  CHAR: {char_uuid} flags={flags}")

        # Subscribe to NUS TX
        if "6e400002" in char_uuid and ("notify" in flags or "indicate" in flags):
            print(f"    >>> Subscribing to NUS TX! <<<")
            char_proxy = bus.get("org.bluez", path)
            count = [0]

            def on_prop_changed(iface, changed, invalidated):
                if iface != "org.bluez.GattCharacteristic1":
                    return
                val = changed.get("Value")
                if val:
                    count[0] += 1
                    data = bytes(val)
                    try:
                        text = data.decode('utf-8').strip()
                        print(f"    DATA #{count[0]}: [{text}]")
                    except:
                        hx = data.hex(' ')
                        print(f"    DATA #{count[0]} BIN len={len(data)}: {hx}")
                    if count[0] >= 12:
                        loop.quit()

            char_proxy.PropertiesChanged.connect(on_prop_changed)
            try:
                char_proxy.StartNotify()
                print("    StartNotify OK, waiting for data...")
            except Exception as e:
                print(f"    StartNotify error: {e}")

        # Also subscribe to Accelerometer Data
        if "e95db84c" in char_uuid and ("notify" in flags or "indicate" in flags):
            print(f"    >>> Subscribing to Accelerometer! <<<")
            char_proxy = bus.get("org.bluez", path)
            accel_count = [0]

            def on_accel(iface, changed, invalidated):
                if iface != "org.bluez.GattCharacteristic1":
                    return
                val = changed.get("Value")
                if val:
                    accel_count[0] += 1
                    data = bytes(val)
                    import struct
                    if len(data) >= 6:
                        x, y, z = struct.unpack('<hhh', data[:6])
                        print(f"    ACCEL #{accel_count[0]}: x={x:6d} y={y:6d} z={z:6d}")

            char_proxy.PropertiesChanged.connect(on_accel)
            try:
                char_proxy.StartNotify()
                print("    Accel StartNotify OK")
            except Exception as e:
                print(f"    Accel StartNotify error: {e}")

print(f"\n=== Waiting for notifications (15s) ===")
loop = GLib.MainLoop()
GLib.timeout_add(15_000, loop.quit)
try:
    loop.run()
except KeyboardInterrupt:
    pass

print("Done.")

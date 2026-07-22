"""Use pydbus to directly control BlueZ for BLE connection to Micro:bit."""
import sys
from pydbus import SystemBus
from gi.repository import GLib

DEVICE_NAME = "petup"  # partial match
TIMEOUT = 20

bus = SystemBus()
adapter = bus.get("org.bluez", "/org/bluez/hci0")
mgr = adapter.GetManagedObjects()

print("=== Finding Micro:bit in BlueZ managed objects ===")
target_path = None
target_addr = None
for path, ifaces in mgr.items():
    dev = ifaces.get("org.bluez.Device1")
    if dev:
        name = dev.get("Name", "")
        addr = dev.get("Address", "")
        rssi = dev.get("RSSI", -999)
        if "micro:bit" in name.lower():
            print(f"  {name} [{addr}] RSSI={rssi} Path={path}")
            if DEVICE_NAME in name.lower() and not target_path:
                target_path = path
                target_addr = addr

if not target_path:
    print(f"No Micro:bit matching '{DEVICE_NAME}' found in cached devices.")
    print("Starting discovery...")
    adapter.StartDiscovery()
    import time
    time.sleep(5)
    adapter.StopDiscovery()
    mgr = adapter.GetManagedObjects()
    for path, ifaces in mgr.items():
        dev = ifaces.get("org.bluez.Device1")
        if dev:
            name = dev.get("Name", "")
            if "micro:bit" in name.lower():
                addr = dev.get("Address", "")
                rssi = dev.get("RSSI", -999)
                print(f"  {name} [{addr}] RSSI={rssi} Path={path}")
                if DEVICE_NAME in name.lower() and not target_path:
                    target_path = path
                    target_addr = addr

if not target_path:
    print("Still not found. Exiting.")
    sys.exit(1)

print(f"\n=== Connecting to {target_addr} ===")
device = bus.get("org.bluez", target_path)

# Check if already connected
if device.Connected:
    print("Already connected!")
else:
    try:
        device.Connect()
        print("Connect() returned, waiting...")
    except Exception as e:
        print(f"Connect error: {e}")
        sys.exit(1)

# Wait for connection to stabilize
import time
for i in range(5):
    time.sleep(1)
    try:
        connected = device.Connected
        services = device.ServicesResolved
        print(f"  t={i+1}s Connected={connected} ServicesResolved={services}")
        if connected and services:
            break
    except Exception as e:
        print(f"  t={i+1}s Error checking state: {e}")

print(f"\n=== Device Properties ===")
props = device.GetAll("org.bluez.Device1")
for key in ['Connected', 'ServicesResolved', 'Paired', 'Trusted', 'UUIDs']:
    print(f"  {key}: {props.get(key, 'N/A')}")

if props.get('ServicesResolved'):
    print(f"\n=== GATT Services ===")
    mgr2 = adapter.GetManagedObjects()
    for path, ifaces in sorted(mgr2.items()):
        if not path.startswith(target_path + "/service"):
            continue
        svc = ifaces.get("org.bluez.GattService1")
        char = ifaces.get("org.bluez.GattCharacteristic1")
        if svc:
            print(f"  SVC [{path.split('/')[-1]}]: {svc.get('UUID', '?')}")
        if char:
            flags = char.get('Flags', [])
            uuid = char.get('UUID', '?')
            print(f"    CHAR [{path.split('/')[-1]}]: {uuid} flags={flags}")
            # If this looks like NUS TX, subscribe
            if "6E400002" in uuid:
                print(f"      *** This is NUS TX! Subscribing... ***")
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
                            print(f"      DATA #{count[0]}: [{text}]")
                        except:
                            print(f"      DATA #{count[0]} BIN len={len(data)}: {data[:30].hex(' ')}")
                        if count[0] >= 10:
                            loop.quit()

                try:
                    char_proxy = bus.get("org.bluez", path)
                    char_proxy.PropertiesChanged.connect(on_prop_changed)
                    char_proxy.StartNotify()
                    print("      Notify started! Waiting for data...")
                except Exception as e:
                    print(f"      StartNotify error: {e}")

if not props.get('ServicesResolved'):
    print("Services not resolved. Trying to resolve manually...")
    try:
        device.ConnectProfile("00001801-0000-1000-8000-00805f9b34fb")  # GAP
    except:
        pass

print("\n=== Waiting for events (main loop) ===")
loop = GLib.MainLoop()
GLib.timeout_add(TIMEOUT * 1000, loop.quit)
try:
    loop.run()
except KeyboardInterrupt:
    pass

print("Done.")

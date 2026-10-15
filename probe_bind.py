"""Secure BluFi session + the bind handshake (type 0 -> type 6), then listen for status."""
import asyncio, base64, json, sys, uuid
from bleak import BleakClient, BleakScanner
from dbus_next import BusType
from dbus_next.aio import MessageBus
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from bluestar.blufi import BluFi, WRITE_UUID

NAME_PREFIX = "BLUAC_"

async def bluez_mtu(address: str) -> int:
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        intro = await bus.introspect("org.bluez", "/")
        om = bus.get_proxy_object("org.bluez", "/", intro).get_interface("org.freedesktop.DBus.ObjectManager")
        dev = "dev_" + address.replace(":", "_")
        for path, ifaces in (await om.call_get_managed_objects()).items():
            ch = ifaces.get("org.bluez.GattCharacteristic1")
            if ch and dev in path and ch["UUID"].value == WRITE_UUID and "MTU" in ch:
                return ch["MTU"].value
    finally:
        bus.disconnect()
    return 23

def decrypt_status(b64: str, uat: str) -> str:
    raw = base64.b64decode(b64)
    c = Cipher(algorithms.AES(uat[:16].encode()), modes.CBC(raw[:16])).decryptor()
    return (c.update(raw[16:]) + c.finalize()).decode("ascii", "replace")

async def main() -> int:
    uat = sys.argv[1] if len(sys.argv) > 1 else str(uuid.uuid4())
    print("uat =", uat)
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or ad.local_name or "").startswith(NAME_PREFIX), timeout=15)
    if dev is None:
        print("AC not found"); return 1
    async with BleakClient(dev, timeout=20) as client:
        mtu = await bluez_mtu(dev.address)
        print("connected, bluez MTU", mtu)
        bf = BluFi(client, mtu=mtu)
        await bf.start()
        await bf.negotiate()
        print("negotiated, key =", bf.key.hex())

        async def send(obj):
            raw = json.dumps(obj, separators=(",", ":")).encode()
            print(">>", raw.decode())
            await bf.send_custom(raw)

        async def drain(t=4.0):
            try:
                while True:
                    f = await bf.recv(timeout=t)
                    if f.is_custom:
                        txt = f.data.decode("utf-8", "replace")
                        print("<< CUSTOM", txt)
                        try:
                            o = json.loads(txt)
                            if o.get("type") == 5 and "state" in o:
                                dev_id, _, enc = o["state"].strip("()").partition("|")
                                print("   state from", dev_id, "=>", decrypt_status(enc, uat))
                        except Exception as e:
                            print("   (decode failed:", e, ")")
                    else:
                        print("<<", f)
            except asyncio.TimeoutError:
                pass

        await send({"type": 0, "uat": uat}); await drain()
        await send({"type": 6, "uat": uat}); await drain()
        print("-- listening 10s for unsolicited status --"); await drain(10)
        await bf.stop()
    return 0

if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

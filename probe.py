"""Read-only probe: connect to the AC over BLE and ask BluFi for version + Wi-Fi status."""
import asyncio
import sys

from bleak import BleakClient, BleakScanner

from coolbar.blufi import (BluFi, CTRL_GET_VERSION, CTRL_GET_WIFI_STATUS, DATA_VERSION,
                            DATA_WIFI_STATUS, describe_wifi_status)

NAME_PREFIX = "BLUAC_"


async def main() -> int:
    print("scanning for", NAME_PREFIX, "...")
    dev = await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or ad.local_name or "").startswith(NAME_PREFIX), timeout=15)
    if dev is None:
        print("AC not found")
        return 1
    print("found", dev.name, dev.address)
    async with BleakClient(dev, timeout=20) as client:
        print("connected, mtu", client.mtu_size)
        bf = BluFi(client)
        await bf.start()

        f = await bf.query(CTRL_GET_VERSION)
        print("version reply:", f)
        if f.subtype == DATA_VERSION and len(f.data) >= 2:
            print(f"  BluFi version {f.data[0]}.{f.data[1]}")

        f = await bf.query(CTRL_GET_WIFI_STATUS)
        print("wifi status reply:", f)
        if f.subtype == DATA_WIFI_STATUS:
            print("  ", describe_wifi_status(f.data))

        # listen a little for any unsolicited frames (vendor firmware often pushes custom data)
        try:
            while True:
                f = await bf.recv(timeout=3)
                print("unsolicited:", f)
        except asyncio.TimeoutError:
            pass
        await bf.stop()
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))

"""End-to-end verification against the real AC: pair if needed, then for each control send a change and
check the AC's own status push reflects it, then restore the original value.

    .venv/bin/python verify.py            # run all round-trips
    .venv/bin/python verify.py --pair     # force a fresh pairing first (AC must be blinking)
Quit the tray app first; the AC accepts one BLE client at a time.
"""
import asyncio
import json
import logging
import sys

from bleak import BleakClient

from coolbar import config
from coolbar.ble import ACSession, bluez_mtu, find_ac
from coolbar.commands import FAN_IDS, MODE_IDS


async def main(argv: list[str]) -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    cfg = config.load()
    dev = await find_ac()
    if dev is None:
        print("FAIL: AC not found over Bluetooth")
        return 1
    async with BleakClient(dev, timeout=20) as client:
        s = ACSession(client, cfg, await bluez_mtu(dev.address))
        await s.start()
        print("connected + encrypted session up")

        if "--pair" in argv or not cfg.paired:
            print("pairing… (AC must be in pairing mode: remote button 5x within 7 s, display blinking)")
            cfg = await s.pair()
            print("PAIRED pid =", cfg.pid, "info =", json.dumps(cfg.info))

        print("requesting current status…")
        st = await s.request_status()
        if st is None:
            print("FAIL: AC did not push its status (wrong token? not paired?)")
            return 1
        print("STATUS:", json.dumps(st))
        base = s.ac
        print("parsed:", base)

        results = []

        async def roundtrip(label: str, desired: dict):
            ok, status = await s.send_desired(desired, confirm_timeout=8.0)
            results.append((label, ok))
            print(f"{'PASS' if ok else 'FAIL'}: {label} -> {desired} ; AC says {json.dumps(status) if status else 'nothing'}")
            await asyncio.sleep(1.0)

        t0 = base.temp
        t1 = t0 + 1 if t0 < 30 else t0 - 1
        await roundtrip("set temperature", {"stemp": f"{t1:.1f}"})
        await roundtrip("restore temperature", {"stemp": f"{t0:.1f}"})

        m0 = MODE_IDS[base.mode]
        m1 = MODE_IDS["dry"] if base.mode != "dry" else MODE_IDS["cool"]
        f0 = FAN_IDS[base.fan]
        mode_obj = lambda m: {"mode": {"value": m, "stemp": f"{t0:.1f}", "fspd": f0}}   # the form the AC applies
        await roundtrip("set mode", mode_obj(m1))
        await roundtrip("restore mode", mode_obj(m0))
        await roundtrip("re-assert temperature after mode", {"stemp": f"{t0:.1f}"})

        f1 = FAN_IDS["low"] if base.fan != "low" else FAN_IDS["medium"]
        await roundtrip("set fan", {"fspd": f1})
        await roundtrip("restore fan", {"fspd": f0})

        # remote-only extras (object form for eco/5-in-1, plain ints for the rest)
        if base.mode == "cool":
            await roundtrip("5-in-1 level 2", {"eco": {"value": 2}})
            await roundtrip("5-in-1 default", {"eco": {"value": 0}})
        else:
            print("SKIP: 5-in-1 (Cool mode only)")
        for key in ("esave", "sleep"):
            cur = int(float(st.get(key, 0)))
            await roundtrip(f"{key} on", {key: 1 - cur})
            await roundtrip(f"{key} restore", {key: cur})
        cur = int(float(st.get("display", 1)))
        await roundtrip("light toggle", {"display": 1 - cur})
        await roundtrip("light restore", {"display": cur})
        for key in ("vswing", "hswing"):
            cur = int(float(st.get(key, 6)))
            await roundtrip(f"{key} position 3", {key: 3})
            await roundtrip(f"{key} restore", {key: cur})
        if base.mode == "cool":
            await roundtrip("turbo on", {"turbo": 1})
            await roundtrip("turbo off", {"turbo": 0})
            await roundtrip("re-assert temperature after turbo", {"stemp": f"{t0:.1f}"})
            await roundtrip("re-assert fan after turbo", {"fspd": f0})
        else:
            print("SKIP: turbo (AC not in Cool mode)")

        p0 = 1 if base.power else 0
        await roundtrip("toggle power", {"pow": 1 - p0})
        await roundtrip("restore power", {"pow": p0})

        await s.stop()
    failed = [l for l, ok in results if not ok]
    print("\nSUMMARY:", f"{len(results) - len(failed)}/{len(results)} passed", ("FAILED: " + ", ".join(failed)) if failed else "")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))

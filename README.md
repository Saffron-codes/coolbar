# CoolBar – menubar controller for Blue Star ACs

> **Unofficial.** This is an independent, community project. It is not affiliated with, endorsed by,
> or supported by Blue Star Limited. "Blue Star" is a trademark of Blue Star Limited and is used here
> only to describe which air conditioners the software works with. Use at your own risk.

A tray ("menubar") app for GNOME that talks to the Blue Star BI-IC318VNUS split AC
**directly over Bluetooth LE**. No Wi-Fi onboarding, no Blue Star cloud account.

Click the snowflake icon in the top bar → a small dark panel drops down under the bar
with power, temperature, mode and fan controls. Click anywhere else (or press Esc) to dismiss.
There are no normal windows.

## Status

| Layer | State |
|---|---|
| BLE link (`BLUAC_…`, Espressif module) | **working** – auto-scans, connects, drops stale links, reconnects |
| BluFi transport incl. DH/AES security negotiation | **working** – verified: encrypted replies decode (BluFi v1.2) |
| Tray icon + drop-down panel | **working** |
| Blue Star command protocol (JSON over BluFi custom data) | **documented below** (reverse-engineered for interoperability) |
| Pairing (one-time bind, type 0/6) | **done** on 2026-10-15, token in `~/.config/coolbar/device.json` |
| Control + read-back confirmation (type 1 → type 5) | **verified on the unit** for every remote function (see table) |

## Protocol

All app↔AC traffic is BluFi *custom data* (subtype 19) carrying UTF-8 JSON, sent only after the
BluFi DH negotiation (plain-text custom data is silently ignored). `"type"` selects the message:

| type | direction | payload | purpose |
|---|---|---|---|
| 0 | app→AC | `{"type":0,"uat":U}` | start bind; U = random UUID chosen by the app |
| 6 | app→AC | `{"type":6,"uat":U}` | finish bind |
| 6 | AC→app | `pid, rmtType, iduType, iduMainFv, iduEEFv, oduMainFv, oduEEFv, bootFv, boardId` | bind result (only while the AC is in pairing mode) |
| 1 | app→AC | `{"type":1,"uat":U,"state":{"desired":{...,"src":"anble"}}}` | control |
| 5 | AC→app | `{"type":5,"state":"(<pid>\|<b64>)"}` | status push; b64 = 16-byte IV + AES-128-CBC(JSON), key = U[:16] |
| 7 | app→AC | `{"type":7,"uat":U}` | **session hello** – sent right after every connection; without it the AC ignores type 1. AC then pushes type 5 every ~3 s |
| 2/3/4 | app→AC | wifi config / wifi scan / wifi result | not used here |

Desired-state rules found by testing on the unit (every object also carries `"src":"anble"` and
`"ts": <epoch ms>`, otherwise it is silently dropped):

| Remote button | key | encoding | verified |
|---|---|---|---|
| ON/OFF | `pow` | 0/1 | yes |
| + / − | `stemp` | "24.0" (string, one decimal) | yes |
| MODE | `mode` | `{"value": id, "stemp": "24.0", "fspd": n}` — 0 fan, 1 heat, 2 cool, 3 dry, 4 auto; a bare int is ignored; fan mode forces stemp 24.0 | yes |
| FAN | `fspd` | 2 low, 3 medium, 4 high, 5 high-high, 6 turbo, 7 auto | yes |
| 5-in-1 CONV | `eco` | `{"value": level}` — 0 default, 1, 2, 3, 4, 6 accepted (5 refused); turbo clears it | yes (percent labels of the levels unknown) |
| 5-in-1 TURBO | `turbo` | 0/1, Cool mode only; on → fspd 4 + stemp 16 | yes |
| swing ↕ / ↔ | `vswing` / `hswing` | 0 off, 1–5 fixed positions, 6 swing | 0/3/6 round-trip; louver positions by eye |
| ENERGY SAVE | `esave` | 0/1 | yes |
| SLEEP | `sleep` | 0/1 | yes |
| LIGHT | `display` | 0/1 | yes |
| TIMER | `offtimer` / `ontimer` | hours (value 1 did not fire within 100 s; the remote counts hours) | accepted, unit inferred |
| CLOCK | — | remote only | — |

Status JSON (type 5, decrypted) is flat: `pow, stemp, ctemp (room temp), mode, fspd, eco, turbo, esave,
sleep, display, vswing, hswing, ontimer, offtimer, climate, err, i_runhour, fv, mCoreVer, udid, …`.

## Panel design

Follows the macOS popover the reference clip shows, with only the controls that exist on the remote:
room temperature · light · power / animated indoor unit (airflow speed from fan, colour from mode,
louver sweep from the swing setting) / big set-point that counts to new values · Turbo / Energy save /
Sleep chips / slider with − + / tiles Mode · Fan · 5-in-1 · Timer / Swing ↕ · Swing ↔ /
"Connected" or "Syncing…" footer. The set-point is also shown next to the tray icon.

## Pairing (one time)

1. On the remote: mode COOL, temperature 16 °C, fan AUTO.
2. Press one of the remote's special buttons (heart / bubbles / bulb / "88" display) **5 times within
   7 seconds**. The AC display starts blinking = pairing mode.
3. Click **Pair with AC** in the panel (or run `.venv/bin/python verify.py --pair` with the app quit).
   The token is saved to `~/.config/coolbar/device.json`.

## Verifying round-trips

```sh
.venv/bin/python verify.py      # quit the tray app first (one BLE client at a time)
```
For temperature, mode, fan and power it sends the change, waits for the AC's own status push, checks
the value came back, then restores the original.

## Install (Linux, one time)

```sh
curl -fsSL https://github.com/Saffron-codes/coolbar/releases/latest/download/install.sh | bash
```

That downloads the self-contained bundle to `~/.local/opt/coolbar`, adds CoolBar to your app launcher,
makes it start at login, and starts it now. No Python or other dependencies are needed. GNOME users
need the *AppIndicator and KStatusNotifierItem Support* extension for the tray icon. Remove with `install.sh --uninstall`.

Windows: download `CoolBar-<version>-windows-x64.zip` from the latest release, unzip anywhere, run
`coolbar.exe`. Android: install `CoolBar-<version>.apk` from the same release.

## Run from source

```sh
python3 -m venv --system-site-packages .venv && .venv/bin/pip install bleak dbus_next cryptography
.venv/bin/python -m coolbar        # add -v for debug logging
```

Requirements: GNOME/KDE with a StatusNotifier tray, `python3-gobject` + GTK3, BlueZ, XWayland.

## Releases

Push a tag `vX.Y.Z`; the Release workflow builds the Android APK, the Windows zip and the Linux
tarball + installer and attaches them to a GitHub Release. Android release signing is used when the
`ANDROID_KEYSTORE_BASE64`, `ANDROID_KEYSTORE_PASSWORD`, `ANDROID_KEY_ALIAS` and `ANDROID_KEY_PASSWORD`
secrets exist, otherwise the APK is debug-signed.

## Layout

```
coolbar/
  blufi.py     Espressif BluFi framing: build/parse frames, CRC16, query helpers
  ble.py       background asyncio worker: scan → connect → BluFi handshake → keep-alive/reconnect
  tray.py      StatusNotifierItem over D-Bus (dbus_next); no menu, so left-click → Activate → panel
  panel.py     GTK3 popup panel, placed under the top bar at the right edge, dark macOS-like styling
  commands.py  ACState model + desired-state encode / status decode
  config.py    pairing token storage (~/.config/coolbar/device.json)
  app.py       wires GTK main thread + worker thread
probe.py       read-only CLI probe (version + Wi-Fi status)
probe_bind.py  low-level pairing probe
verify.py      pair (if needed) + round-trip verification of every control
```

## Legal

- The Bluetooth protocol described here was reverse-engineered by observing how the air conditioner
  and its official app communicate, solely to achieve interoperability with hardware the author
  owns. No code, assets or other material from Blue Star's software is included in this repository.
- The transport is Espressif's open [BluFi](https://docs.espressif.com/projects/esp-idf/en/latest/esp32/api-guides/ble/blufi.html)
  protocol. The Diffie-Hellman group parameters and framing follow Espressif's reference client
  (Apache License 2.0).
- Panel design inspired by a status-bar AC app shown by [@icanberk](https://x.com/icanberk).
- This software can switch a mains-powered appliance on and off. The authors accept no liability for
  any damage, malfunction or warranty consequences; see the MIT [LICENSE](LICENSE).

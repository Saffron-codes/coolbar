# CoolBar – Android app and Windows menubar app (Flutter)

Same controller as the Linux menubar app (`../`), same design. Builds the Android app and, with
`lib/desktop/tray_shell.dart`, the Windows menubar app: a tray icon whose click pops the panel up next to
the taskbar; clicking elsewhere hides it. (A Linux desktop build exists for development only: the tray
plugin on Linux offers a menu, not clicks, so the Python app remains the Linux menubar app.) Talks to the
BI-IC318VNUS directly over Bluetooth LE; no Blue Star account, no Wi-Fi, no cloud.

## Layout

```
lib/
  protocol/blufi.dart      BluFi framing, CRC16, fragmentation, DH + AES-CFB negotiation  (port of ../coolbar/blufi.py)
  protocol/commands.dart   ACState, desired-state encode, status decode, confirmation matcher (port of ../coolbar/commands.py)
  protocol/session.dart    pairing (type 0/6), hello (type 7), control (type 1), status decrypt (type 5)
  ble/ac_connection.dart   scan BLUAC_*, connect (MTU 512), reconnect loop, ChangeNotifier for the UI
  ui/home_page.dart        the screen: room temp · light · power / animated unit / set-point + chips / slider / tiles / footer
  ui/ac_illustration.dart  CustomPainter airflow animation (speed = fan, colour = mode, sweep = swing)
  ui/widgets.dart          BigTemp (counting + bounce), RoundButton, Chip2, Tile, bottom-sheet picker
  ui/theme.dart            palette shared with the desktop panel
  desktop/tray_shell.dart  Windows/Linux tray icon + frameless popover window (tray_manager, window_manager)
```

The protocol rules (every desired object needs `ts` in epoch ms and `src`, mode and 5-in-1 go as
objects, hello after every connection, …) are documented in `../README.md`. Keep `commands.dart`
and `../coolbar/commands.py` in sync.

## Build / run

```sh
cd app
flutter pub get
flutter run -d linux            # runs on the laptop against the real AC (flutter_blue_plus has a BlueZ backend)
flutter build apk --release     # build/app/outputs/flutter-apk/app-release.apk
flutter run -d <phone>          # with a phone in developer mode plugged in
```

Android: min SDK 23, BLUETOOTH_SCAN/CONNECT permissions declared (the plugin requests them at
runtime). iOS: `NSBluetoothAlwaysUsageDescription` set; needs a Mac + Xcode to build.

## Pairing

The pairing token is per app install and stored with `shared_preferences`. The AC remembers one
token, so pairing the phone replaces the laptop's pairing (and vice versa). To use both, tap
"Already paired elsewhere?" in the app and paste `uat` and `pid` from the laptop's
`~/.config/coolbar/device.json` (or the other way round: the token the phone creates is shown in
the app's footer after pairing).

## Verified

2026-10-15, running on the laptop against the real unit (`flutter run -d linux`): scan, connect,
DH/AES negotiation (BluFi v1.2), hello, status decrypt, set-point 23→24→23 with the AC confirming
each step. Run the same check yourself with
`flutter run -d linux --dart-define=BLUESTAR_SELFTEST=true` (quit the menubar app first).

Linux-only quirks handled in `ac_connection.dart`: the BlueZ backend only reports newly discovered
devices as scan results (so the system device list is checked first), replays a stale "disconnected"
state right after connecting, and does not negotiate MTU (frames fall back to 23-byte fragments).

/// Finds the AC (BLE name BLUAC_*), keeps a connected + negotiated session, reconnects, and
/// exposes everything the UI needs as a ChangeNotifier.
library;

import 'dart:async';
import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_blue_plus/flutter_blue_plus.dart';
import 'package:shared_preferences/shared_preferences.dart';

import '../protocol/blufi.dart';
import '../protocol/commands.dart';
import '../protocol/session.dart';

enum Phase { scanning, connecting, connected, error }

class ACConnection extends ChangeNotifier {
  Phase phase = Phase.scanning;
  String message = 'Looking for the AC…';
  bool busy = false;
  bool acKnown = false;
  ACState ac = const ACState();
  DeviceConfig cfg = const DeviceConfig();
  String version = '';
  String address = '';

  BluetoothDevice? _device;
  ACSession? _session;
  BluFi? _bf;
  StreamSubscription? _notifySub, _connSub, _statusSub;
  bool _stopping = false;
  bool _running = false;

  bool get paired => cfg.paired;
  bool get connected => phase == Phase.connected;

  Future<void> start() async {
    if (_running) return;
    _running = true;
    FlutterBluePlus.setLogLevel(LogLevel.info, color: false);
    final prefs = await SharedPreferences.getInstance();
    final raw = prefs.getString('device');
    if (raw != null) cfg = DeviceConfig.fromJson(jsonDecode(raw));
    _loop();
  }

  Future<void> stop() async {
    _stopping = true;
    await _teardown();
  }

  void _set({Phase? p, String? msg, bool? b}) {
    if (p != null) phase = p;
    if (msg != null) message = msg;
    if (b != null) busy = b;
    notifyListeners();
  }

  Future<void> _loop() async {
    while (!_stopping) {
      try {
        await _sessionOnce();
      } catch (e) {
        debugPrint('session ended: $e');
        _set(p: Phase.error, msg: _friendly(e));
      }
      await _teardown();
      if (!_stopping) await Future.delayed(const Duration(seconds: 3));
    }
  }

  String _friendly(Object e) {
    final s = e.toString();
    if (s.contains('Bluetooth') && s.contains('off')) return 'Bluetooth is off';
    return s.length > 90 ? '${s.substring(0, 90)}…' : s;
  }

  Future<BluetoothDevice?> _find() async {
    // A phone can keep a GATT link cached; prefer a device that is already connected.
    for (final d in FlutterBluePlus.connectedDevices) {
      if (d.platformName.startsWith('BLUAC_')) return d;
    }
    // Linux (BlueZ) only reports *newly* discovered devices as scan results; a device BlueZ already
    // knows never re-appears. The system device list covers that case (on Android/iOS it just lists
    // devices connected via other apps, which is harmless).
    try {
      for (final d in await FlutterBluePlus.systemDevices([])) {
        if (d.platformName.startsWith('BLUAC_')) {
          debugPrint('found cached device ${d.remoteId.str} ${d.platformName}');
          return d;
        }
      }
    } catch (e) {
      debugPrint('systemDevices: $e');
    }
    final completer = Completer<BluetoothDevice?>();
    final seen = <String>{};
    final sub = FlutterBluePlus.onScanResults.listen((results) {
      for (final r in results) {
        final name = r.advertisementData.advName.isNotEmpty ? r.advertisementData.advName : r.device.platformName;
        if (seen.add(r.device.remoteId.str)) debugPrint('scan: ${r.device.remoteId.str} name="$name" adv="${r.advertisementData.advName}" plat="${r.device.platformName}" rssi=${r.rssi}');
        if (name.startsWith('BLUAC_') && !completer.isCompleted) completer.complete(r.device);
      }
    });
    try {
      await FlutterBluePlus.startScan(timeout: const Duration(seconds: 12), continuousUpdates: true);
      return await completer.future.timeout(const Duration(seconds: 13), onTimeout: () => null);
    } finally {
      await FlutterBluePlus.stopScan();
      await sub.cancel();
    }
  }

  Future<void> _sessionOnce() async {
    _set(p: Phase.scanning, msg: 'Looking for the AC…');
    await FlutterBluePlus.adapterState.where((s) => s == BluetoothAdapterState.on).first
        .timeout(const Duration(seconds: 15), onTimeout: () => throw StateError('Bluetooth is off'));
    final dev = await _find();
    if (dev == null) {
      _set(p: Phase.error, msg: 'AC not found over Bluetooth');
      return;
    }
    _device = dev;
    address = dev.remoteId.str;
    _set(p: Phase.connecting, msg: 'Connecting…');
    final dropped = Completer<void>();
    debugPrint('connecting to ${dev.remoteId.str} …');
    await dev.connect(license: License.nonprofit, timeout: const Duration(seconds: 20), mtu: 512);
    // Subscribe only now: the stream replays its last value, and before connect() that is a stale
    // "disconnected" which would end the session immediately. Count a drop only after "connected".
    var sawConnected = false;
    _connSub = dev.connectionState.listen((s) {
      if (s == BluetoothConnectionState.connected) sawConnected = true;
      if (s == BluetoothConnectionState.disconnected && sawConnected && !dropped.isCompleted) dropped.complete();
    });
    debugPrint('connected, discovering services …');
    final services = await dev.discoverServices();
    debugPrint('services: ${services.map((s) => s.uuid.str).toList()}');
    BluetoothCharacteristic? wr, nt;
    for (final s in services) {
      if (!s.uuid.str.toLowerCase().endsWith(serviceUuid)) continue;
      for (final c in s.characteristics) {
        final u = c.uuid.str.toLowerCase();
        if (u.endsWith(writeUuid)) wr = c;
        if (u.endsWith(notifyUuid)) nt = c;
      }
    }
    if (wr == null || nt == null) throw StateError('BluFi service not found on device');
    final mtu = dev.mtuNow;
    final bf = BluFi(mtu: mtu > 0 ? mtu : 23, writer: (bytes) => wr!.write(bytes, withoutResponse: false), log: debugPrint);
    _bf = bf;
    _notifySub = nt.onValueReceived.listen(bf.onNotify);
    debugPrint('mtu=$mtu, enabling notifications …');
    await nt.setNotifyValue(true);
    debugPrint('negotiating …');
    final session = ACSession(bf, cfg, log: debugPrint);
    _session = session;
    _statusSub = session.statusStream.listen((_) {
      if (session.ac != null) {
        ac = session.ac!;
        acKnown = true;
        if (!busy) message = 'Connected';
        notifyListeners();
      }
    });
    await session.start();
    version = session.version;
    debugPrint('session up, blufi v$version, paired=${cfg.paired}');
    _set(p: Phase.connected, msg: cfg.paired ? 'Connected' : 'Connected – not paired yet');
    if (const bool.fromEnvironment('BLUESTAR_SELFTEST')) unawaited(_selfTest(session));
    await dropped.future;
    _set(p: Phase.scanning, msg: 'Disconnected');
  }

  /// Desktop-only check (flutter run --dart-define=BLUESTAR_SELFTEST=true): bump the set-point by one
  /// degree, wait for the AC to confirm, restore it. Proves hello/status/control on the Dart port.
  Future<void> _selfTest(ACSession s) async {
    try {
      final st = s.lastStatus.isNotEmpty ? s.lastStatus : (await s.hello() ?? {});
      debugPrint('SELFTEST status: ${jsonEncode(st)}');
      final t0 = double.parse('${st['stemp']}').round();
      final t1 = t0 < 30 ? t0 + 1 : t0 - 1;
      for (final (label, t) in [('set', t1), ('restore', t0)]) {
        final (ok, status) = await s.sendDesired({'stemp': t.toStringAsFixed(1)});
        debugPrint('SELFTEST $label stemp=$t -> ${ok ? "CONFIRMED" : "NOT CONFIRMED"} (AC says stemp=${status?['stemp']})');
      }
    } catch (e) {
      debugPrint('SELFTEST failed: $e');
    }
  }

  Future<void> _teardown() async {
    await _statusSub?.cancel();
    await _notifySub?.cancel();
    await _connSub?.cancel();
    await _session?.stop();
    _bf?.dispose();
    try {
      await _device?.disconnect();
    } catch (_) {}
    _session = null;
    _bf = null;
    _device = null;
  }

  // ---------------------------------------------------------------- commands
  Future<void> pair() async {
    final s = _session;
    if (s == null || !connected) {
      _set(msg: 'Not connected');
      return;
    }
    _set(b: true, msg: 'Pairing… (AC must be blinking)');
    try {
      cfg = await s.pair();
      cfg = DeviceConfig(uat: cfg.uat, pid: cfg.pid, address: address, info: cfg.info);
      s.cfg = cfg;
      final prefs = await SharedPreferences.getInstance();
      await prefs.setString('device', jsonEncode(cfg.toJson()));
      _set(b: false, msg: 'Paired with ${cfg.pid}');
      await s.hello();
    } catch (e) {
      _set(b: false, msg: e.toString());
    }
  }

  Future<void> apply(ACState next) async {
    final s = _session;
    final prev = acKnown ? ac : null;
    ac = next;
    notifyListeners();
    if (s == null || !connected) {
      _set(msg: 'Not connected');
      return;
    }
    if (!cfg.paired) {
      _set(msg: 'Not paired – pair while the AC is blinking');
      return;
    }
    final desired = encode(next, prev);
    if (desired.isEmpty) return;
    _set(b: true, msg: 'Syncing…');
    try {
      final (ok, status) = await s.sendDesired(desired);
      final what = desired.entries.map((e) => '${e.key}=${e.value is Map ? (e.value as Map)['value'] : e.value}').join(', ');
      if (ok) {
        _set(b: false, msg: 'AC confirmed $what');
      } else if (status == null) {
        _set(b: false, msg: 'Sent $what – no reply from AC');
      } else {
        _set(b: false, msg: 'Sent $what – AC reported something else');
      }
    } catch (e) {
      _set(b: false, msg: 'Send failed: ${_friendly(e)}');
    }
  }

  /// Use a token obtained elsewhere (e.g. the laptop's ~/.config/bluestar-ac/device.json), so both
  /// apps share the AC's single pairing instead of replacing each other's.
  Future<void> importToken(String uat, String pid) async {
    cfg = DeviceConfig(uat: uat.trim(), pid: pid.trim(), address: address);
    if (!cfg.paired) {
      _set(msg: 'Token must be at least 16 characters');
      return;
    }
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('device', jsonEncode(cfg.toJson()));
    _session?.cfg = cfg;
    _set(msg: 'Token imported');
    if (_session != null && connected) await _session!.hello();
  }

  Future<void> forget() async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('device');
    cfg = const DeviceConfig();
    _session?.cfg = cfg;
    acKnown = false;
    _set(msg: 'Pairing forgotten');
  }
}

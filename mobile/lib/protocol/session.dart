/// One connected, negotiated BluFi link to the AC plus the Blue Star custom-data protocol:
///   0/6 pairing (AC must be in pairing mode), 7 hello with the token on every connection,
///   1 control {"state":{"desired":{...,"src":"anble","ts":ms}}}, 5 status push (AES-CBC, key = uat[:16]).
library;

import 'dart:async';
import 'dart:convert';
import 'dart:math';
import 'dart:typed_data';

import 'package:pointycastle/export.dart';

import 'blufi.dart';
import 'commands.dart';

class DeviceConfig {
  final String uat, pid, address;
  final Map<String, dynamic> info;
  const DeviceConfig({this.uat = '', this.pid = '', this.address = '', this.info = const {}});
  bool get paired => uat.length >= 16;
  Map<String, dynamic> toJson() => {'uat': uat, 'pid': pid, 'address': address, 'info': info};
  factory DeviceConfig.fromJson(Map<String, dynamic> j) => DeviceConfig(
      uat: j['uat'] ?? '', pid: j['pid'] ?? '', address: j['address'] ?? '',
      info: (j['info'] as Map?)?.cast<String, dynamic>() ?? const {});
}

class PairingTimeout implements Exception {
  @override
  String toString() => 'AC did not answer the pairing request. Put it in pairing mode first '
      '(remote button 5x within 7 s, display blinking) and retry.';
}

Map<String, dynamic> decryptStatus(String b64, String uat) {
  final raw = base64.decode(b64);
  final cbc = CBCBlockCipher(AESEngine())
    ..init(false, ParametersWithIV(KeyParameter(Uint8List.fromList(utf8.encode(uat.substring(0, 16)))), raw.sublist(0, 16)));
  final body = raw.sublist(16);
  final out = Uint8List(body.length);
  for (var off = 0; off + 16 <= body.length; off += 16) {
    cbc.processBlock(body, off, out, off);
  }
  var txt = ascii.decode(out, allowInvalid: true);
  final end = txt.lastIndexOf('}');
  if (end >= 0) txt = txt.substring(0, end + 1);
  return jsonDecode(txt) as Map<String, dynamic>;
}

class ACSession {
  ACSession(this.bf, this.cfg, {this.log});

  final BluFi bf;
  DeviceConfig cfg;
  final void Function(String)? log;

  ACState? ac;
  Map<String, dynamic> lastStatus = {};
  String version = '';
  final _status = StreamController<Map<String, dynamic>>.broadcast();
  final _custom = StreamController<Map<String, dynamic>>.broadcast();
  StreamSubscription? _sub;

  Stream<Map<String, dynamic>> get statusStream => _status.stream;

  Future<void> start() async {
    _sub = bf.frames.listen(_onFrame);
    await bf.negotiate();
    final v = await bf.query(ctrlGetVersion);
    version = v.data.length >= 2 ? '${v.data[0]}.${v.data[1]}' : '';
    if (cfg.paired) await hello();
  }

  Future<void> stop() async {
    await _sub?.cancel();
  }

  void _onFrame(Frame f) {
    if (!f.isCustom) return;
    Map<String, dynamic> obj;
    try {
      obj = jsonDecode(utf8.decode(f.data)) as Map<String, dynamic>;
    } catch (_) {
      log?.call('rx custom (not json)');
      return;
    }
    if (obj['type'] == 5) {
      if (!cfg.paired) return;
      try {
        final state = (obj['state'] as String).replaceAll(RegExp(r'^\(|\)$'), '');
        final bar = state.indexOf('|');
        final status = decryptStatus(state.substring(bar + 1), cfg.uat);
        lastStatus = status;
        ac = decode(status, ac) ?? ac;
        _status.add(status);
      } catch (e) {
        log?.call('status decrypt failed: $e');
      }
    } else {
      _custom.add(obj);
    }
  }

  Future<void> _send(Map<String, dynamic> obj) => bf.sendCustom(utf8.encode(jsonEncode(obj)));

  Future<Map<String, dynamic>?> hello({Duration timeout = const Duration(seconds: 5)}) async {
    final first = _status.stream.first.timeout(timeout);
    await _send({'type': 7, 'uat': cfg.uat});
    try {
      return await first;
    } on TimeoutException {
      log?.call('no status after hello');
      return null;
    }
  }

  Future<DeviceConfig> pair({Duration timeout = const Duration(seconds: 20)}) async {
    final uat = _uuid();
    final reply = _custom.stream.firstWhere((o) => o['type'] == 6).timeout(timeout);
    await _send({'type': 0, 'uat': uat});
    await Future.delayed(const Duration(milliseconds: 300));
    await _send({'type': 6, 'uat': uat});
    Map<String, dynamic> r;
    try {
      r = await reply;
    } on TimeoutException {
      throw PairingTimeout();
    }
    cfg = DeviceConfig(
        uat: uat,
        pid: '${r['pid'] ?? ''}',
        address: cfg.address,
        info: {for (final e in r.entries) if (e.key != 'type' && e.key != 'pid') e.key: e.value});
    return cfg;
  }

  /// Send a desired-state change; returns (confirmed, status) once the AC pushes a status that
  /// reflects every requested field, or the last status seen before the timeout.
  Future<(bool, Map<String, dynamic>?)> sendDesired(Map<String, dynamic> desired,
      {Duration confirmTimeout = const Duration(seconds: 6)}) async {
    if (!cfg.paired) throw StateError('not paired');
    final payload = {...desired, 'src': 'anble', 'ts': DateTime.now().millisecondsSinceEpoch};
    final deadline = DateTime.now().add(confirmTimeout);
    Map<String, dynamic>? last;
    final done = Completer<(bool, Map<String, dynamic>?)>();
    final sub = _status.stream.listen((st) {
      last = st;
      if (matches(desired, st) && !done.isCompleted) done.complete((true, st));
    });
    try {
      await _send({'type': 1, 'uat': cfg.uat, 'state': {'desired': payload}});
      final remaining = deadline.difference(DateTime.now());
      return await done.future.timeout(remaining.isNegative ? Duration.zero : remaining, onTimeout: () => (false, last));
    } finally {
      await sub.cancel();
    }
  }

  static String _uuid() {
    final r = Random.secure();
    final b = List<int>.generate(16, (_) => r.nextInt(256));
    b[6] = (b[6] & 0x0f) | 0x40;
    b[8] = (b[8] & 0x3f) | 0x80;
    final h = b.map((x) => x.toRadixString(16).padLeft(2, '0')).join();
    return '${h.substring(0, 8)}-${h.substring(8, 12)}-${h.substring(12, 16)}-${h.substring(16, 20)}-${h.substring(20)}';
  }
}

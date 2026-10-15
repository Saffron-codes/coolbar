/// Espressif BluFi transport with the security negotiation the Blue Star app performs.
/// Direct port of the verified Python implementation (coolbar/blufi.py in the desktop app).
///
/// Frame: [type][frame_ctrl][seq][len][data...][crc_lo][crc_hi]
///   type       = (subtype << 2) | pktType   (0 = CTRL, 1 = DATA)
///   frame_ctrl = bit0 ENC, bit1 CHECKSUM, bit2 DIR, bit3 REQ_ACK, bit4 FRAG
///   crc        = crc16 over seq|len|PLAINTEXT data
///   enc        = AES-128-CFB128 over data, IV = [seq, 0*15], key = MD5(DH shared secret)
///   frag       = data = [remaining_total lo, hi] + chunk
library;

import 'dart:async';
import 'dart:math';
import 'dart:typed_data';

import 'package:pointycastle/export.dart';

const serviceUuid = 'ffff';
const writeUuid = 'ff01'; // app -> device
const notifyUuid = 'ff02'; // device -> app

const pktCtrl = 0, pktData = 1;
const ctrlSetSecMode = 1, ctrlGetWifiStatus = 5, ctrlGetVersion = 7;
const dataNeg = 0, dataWifiStatus = 15, dataVersion = 16, dataError = 18, dataCustom = 19;
const fcEnc = 0x01, fcCheck = 0x02, fcFrag = 0x10;

final BigInt dhP = BigInt.parse(
    'cf5cf5c38419a724957ff5dd323b9c45c3cdd261eb740f69aa94b8bb1a5c96409153bd76b24222d03274e4725a5406092e9e82e9'
    '135c643cae98132b0d95f7d65347c68afc1e677da90e51bbab5f5cf429c291b4ba39c6b2dc5e8c7231e46aa7728e87664532cdf5'
    '47be20c9a3fa8342be6e34371a27c06f7dc0edddd2f86373',
    radix: 16);
final BigInt dhG = BigInt.two;
const secModeDataEncCheck = 0x03;

int crc16be(List<int> data, [int crc = 0]) {
  crc = (~crc) & 0xFFFF;
  for (final b in data) {
    crc ^= b << 8;
    for (var i = 0; i < 8; i++) {
      crc = (crc & 0x8000) != 0 ? ((crc << 1) ^ 0x1021) & 0xFFFF : (crc << 1) & 0xFFFF;
    }
  }
  return (~crc) & 0xFFFF;
}

Uint8List _bigToBytes(BigInt v, int len) {
  final out = Uint8List(len);
  var x = v;
  for (var i = len - 1; i >= 0; i--) {
    out[i] = (x & BigInt.from(0xff)).toInt();
    x = x >> 8;
  }
  return out;
}

BigInt _bytesToBig(List<int> b) {
  var r = BigInt.zero;
  for (final x in b) {
    r = (r << 8) | BigInt.from(x);
  }
  return r;
}

/// AES-128 CFB128 (what Java's "AES/CFB/NoPadding" means), implemented on the raw block cipher
/// so arbitrary lengths work.
Uint8List aesCfb(Uint8List key, int seq, List<int> data, {required bool encrypt}) {
  final aes = AESEngine()..init(true, KeyParameter(key));
  var iv = Uint8List(16)..[0] = seq;
  final out = Uint8List(data.length);
  for (var off = 0; off < data.length; off += 16) {
    final ks = Uint8List(16);
    aes.processBlock(iv, 0, ks, 0);
    final n = min(16, data.length - off);
    final next = Uint8List(16);
    for (var i = 0; i < n; i++) {
      out[off + i] = data[off + i] ^ ks[i];
      next[i] = encrypt ? out[off + i] : data[off + i];
    }
    iv = next;
  }
  return out;
}

class Frame {
  final int pktType, subtype, fc, seq;
  final Uint8List data;
  Frame(this.pktType, this.subtype, this.fc, this.seq, this.data);
  bool get isCtrl => pktType == pktCtrl;
  bool get isCustom => pktType == pktData && subtype == dataCustom;
  @override
  String toString() => '<${isCtrl ? "CTRL" : "DATA"} sub=$subtype seq=$seq len=${data.length}>';
}

/// Transport-agnostic BluFi session: feed notifications in with [onNotify], send with [writer].
class BluFi {
  BluFi({required this.writer, this.mtu = 23, this.log});

  final Future<void> Function(Uint8List bytes) writer;
  int mtu;
  final void Function(String)? log;

  int _seq = -1;
  Uint8List? key;
  final _rx = StreamController<Frame>.broadcast();
  final Map<int, List<int>> _frag = {};
  final Map<int, int> _fragTotal = {};

  Stream<Frame> get frames => _rx.stream;
  bool get secure => key != null;

  void reset() {
    _seq = -1;
    key = null;
    _frag.clear();
  }

  void onNotify(List<int> raw) {
    if (raw.length < 4) return;
    final t = raw[0], fc = raw[1], seq = raw[2], ln = raw[3];
    var data = Uint8List.fromList(raw.sublist(4, min(raw.length, 4 + ln)));
    if ((fc & fcEnc) != 0) {
      if (key == null) {
        log?.call('rx encrypted frame before key negotiation');
        return;
      }
      data = aesCfb(key!, seq, data, encrypt: false);
    }
    if ((fc & fcCheck) != 0 && raw.length >= 6 + ln) {
      final want = raw[4 + ln] | (raw[5 + ln] << 8);
      final got = crc16be([seq, ln, ...data]);
      if (want != got) {
        log?.call('rx bad crc');
        return;
      }
    }
    final pktType = t & 0x03, subtype = t >> 2;
    if ((fc & fcFrag) != 0) {
      if (!_frag.containsKey(t)) _fragTotal[t] = data[0] | (data[1] << 8);
      (_frag[t] ??= []).addAll(data.sublist(2));
      return;
    }
    if (_frag.containsKey(t)) {
      final all = [..._frag.remove(t)!, ...data];
      final total = _fragTotal.remove(t);
      if (total != null && total != all.length) {
        log?.call('rx dropped reassembled frame ${all.length} != $total');
        return;
      }
      data = Uint8List.fromList(all);
    }
    _rx.add(Frame(pktType, subtype, fc, seq, data));
  }

  int _nextSeq() => _seq = (_seq + 1) & 0xFF;

  Uint8List _frame(int pktType, int subtype, List<int> data, {required bool enc, required bool check, required bool frag}) {
    final seq = _nextSeq();
    final fc = (enc ? fcEnc : 0) | (check ? fcCheck : 0) | (frag ? fcFrag : 0);
    final out = BytesBuilder()..add([(subtype << 2) | pktType, fc, seq, data.length]);
    final crc = check ? crc16be([seq, data.length, ...data]) : null;
    var payload = Uint8List.fromList(data);
    if (enc && data.isNotEmpty) payload = aesCfb(key!, seq, data, encrypt: true);
    out.add(payload);
    if (crc != null) out.add([crc & 0xff, (crc >> 8) & 0xff]);
    return out.toBytes();
  }

  /// Send one logical message, fragmenting exactly like EspBlufi.
  Future<void> send(int pktType, int subtype, List<int> data, {bool? enc, bool check = true}) async {
    enc ??= key != null && pktType == pktData;
    final limit = max(mtu - 4, 20) - (check ? 8 : 6);
    if (data.length <= limit) {
      await writer(_frame(pktType, subtype, data, enc: enc, check: check, frag: false));
      return;
    }
    var pos = 0;
    while (pos < data.length) {
      var chunk = data.sublist(pos, min(pos + limit, data.length));
      pos += chunk.length;
      if (data.length - pos > 0 && data.length - pos <= 2) {
        chunk = [...chunk, ...data.sublist(pos)];
        pos = data.length;
      }
      final last = pos >= data.length;
      final remaining = data.length - (pos - chunk.length);
      final payload = last ? chunk : [remaining & 0xff, (remaining >> 8) & 0xff, ...chunk];
      await writer(_frame(pktType, subtype, payload, enc: enc, check: check, frag: !last));
    }
  }

  Future<void> sendCustom(List<int> payload) => send(pktData, dataCustom, payload);

  Future<Frame> _waitFor(bool Function(Frame) pred, Duration timeout) {
    // `ignore()`: if the write that follows throws, nobody awaits this future; without it the
    // stream closing later surfaces as an unhandled "No element" error.
    final f = frames.firstWhere(pred).timeout(timeout);
    f.ignore();
    return f;
  }

  /// DH key exchange + SET_SEC_MODE, after which data frames are encrypted + checksummed.
  Future<void> negotiate({Duration timeout = const Duration(seconds: 8)}) async {
    final rnd = Random.secure();
    var priv = BigInt.zero;
    for (var i = 0; i < 128; i++) {
      priv = (priv << 8) | BigInt.from(rnd.nextInt(256));
    }
    priv = (priv >> 1) | BigInt.one; // 1023 bits, odd
    final pub = dhG.modPow(priv, dhP);
    final pB = _bigToBytes(dhP, 128), gB = [2], pubB = _bigToBytes(pub, 128);
    final body = [1, 0, pB.length, ...pB, 0, gB.length, ...gB, 0, pubB.length, ...pubB];
    final total = pB.length + gB.length + pubB.length + 6;
    final reply = _waitFor((f) => !f.isCtrl && (f.subtype == dataNeg || f.subtype == dataError), timeout);
    await send(pktData, dataNeg, [0, (total >> 8) & 0xff, total & 0xff], enc: false, check: false);
    await Future.delayed(const Duration(milliseconds: 10));
    await send(pktData, dataNeg, body, enc: false, check: false);
    final f = await reply;
    if (f.subtype == dataError) throw StateError('negotiation refused (${f.data})');
    final devPub = _bytesToBig(f.data);
    if (devPub == BigInt.zero) throw StateError('device sent empty public key');
    final secret = _bigToBytes(devPub.modPow(priv, dhP), 128);
    key = MD5Digest().process(secret);
    await send(pktCtrl, ctrlSetSecMode, [secModeDataEncCheck], enc: false, check: true);
  }

  Future<Frame> query(int ctrlSubtype, {Duration timeout = const Duration(seconds: 3)}) async {
    final reply = _waitFor((f) => !f.isCtrl && f.subtype != dataCustom, timeout);
    await send(pktCtrl, ctrlSubtype, const [], enc: false);
    return reply;
  }

  void dispose() => _rx.close();
}

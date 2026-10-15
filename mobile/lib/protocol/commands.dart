/// AC state model and the Blue Star JSON encoding, verified against the BI-IC318VNUS.
/// Mirrors bluestar/commands.py in the desktop app; keep the two in sync.
library;

const modes = ['cool', 'dry', 'fan', 'auto'];
const fans = ['auto', 'low', 'medium', 'high'];
const tempMin = 16, tempMax = 30;

const modeIds = {'heat': 1, 'cool': 2, 'dry': 3, 'auto': 4, 'fan': 0};
const fanIds = {'low': 2, 'medium': 3, 'high': 4, 'highhigh': 5, 'turbo': 6, 'auto': 7};
final idModes = {for (final e in modeIds.entries) e.value: e.key};
final idFans = {for (final e in fanIds.entries) e.value: e.key};
const convLevels = [0, 1, 2, 3, 4, 6]; // 5-in-1 ids the unit accepts, 0 = default
const swingAuto = 6; // 1..5 fixed louver positions, 6 = continuous swing
const timerPresets = [0, 1, 2, 4, 8]; // hours

class ACState {
  final bool power;
  final int temp;
  final String mode;
  final String fan;
  final double? ambient;
  final int conv;
  final bool turbo, esave, sleep, display;
  final int vswing, hswing, offtimer, ontimer;

  const ACState({
    this.power = false,
    this.temp = 24,
    this.mode = 'cool',
    this.fan = 'auto',
    this.ambient,
    this.conv = 0,
    this.turbo = false,
    this.esave = false,
    this.sleep = false,
    this.display = true,
    this.vswing = swingAuto,
    this.hswing = swingAuto,
    this.offtimer = 0,
    this.ontimer = 0,
  });

  ACState copyWith({
    bool? power, int? temp, String? mode, String? fan, double? ambient, int? conv, bool? turbo, bool? esave,
    bool? sleep, bool? display, int? vswing, int? hswing, int? offtimer, int? ontimer,
  }) =>
      ACState(
        power: power ?? this.power,
        temp: (temp ?? this.temp).clamp(tempMin, tempMax),
        mode: mode ?? this.mode,
        fan: fan ?? this.fan,
        ambient: ambient ?? this.ambient,
        conv: conv ?? this.conv,
        turbo: turbo ?? this.turbo,
        esave: esave ?? this.esave,
        sleep: sleep ?? this.sleep,
        display: display ?? this.display,
        vswing: vswing ?? this.vswing,
        hswing: hswing ?? this.hswing,
        offtimer: offtimer ?? this.offtimer,
        ontimer: ontimer ?? this.ontimer,
      );

  @override
  String toString() => 'ACState(pow=$power temp=$temp $mode fan=$fan conv=$conv turbo=$turbo esave=$esave '
      'sleep=$sleep display=$display vswing=$vswing hswing=$hswing off=$offtimer on=$ontimer room=$ambient)';
}

/// Desired-state object for a type-1 message: only fields that differ from [prev].
Map<String, dynamic> encode(ACState s, ACState? prev) {
  bool changed<T>(T a, T? b) => prev == null || a != b;
  final d = <String, dynamic>{};
  if (changed(s.power, prev?.power)) d['pow'] = s.power ? 1 : 0;
  if (changed(s.mode, prev?.mode)) {
    d['mode'] = {'value': modeIds[s.mode], 'stemp': s.temp.toStringAsFixed(1), 'fspd': fanIds[s.fan]};
  } else {
    if (changed(s.temp, prev?.temp)) d['stemp'] = s.temp.toStringAsFixed(1);
    if (changed(s.fan, prev?.fan)) d['fspd'] = fanIds[s.fan];
  }
  if (prev != null) {
    if (s.conv != prev.conv) d['eco'] = {'value': s.conv};
    if (s.turbo != prev.turbo) d['turbo'] = s.turbo ? 1 : 0;
    if (s.esave != prev.esave) d['esave'] = s.esave ? 1 : 0;
    if (s.sleep != prev.sleep) d['sleep'] = s.sleep ? 1 : 0;
    if (s.display != prev.display) d['display'] = s.display ? 1 : 0;
    if (s.vswing != prev.vswing) d['vswing'] = s.vswing;
    if (s.hswing != prev.hswing) d['hswing'] = s.hswing;
    if (s.offtimer != prev.offtimer) d['offtimer'] = s.offtimer;
    if (s.ontimer != prev.ontimer) d['ontimer'] = s.ontimer;
  }
  return d;
}

int _int(dynamic v, int def) => v == null ? def : (double.tryParse(v.toString())?.toInt() ?? def);

bool plausible(Map<String, dynamic> s) {
  final pow = _int(s['pow'], 0);
  if (s.containsKey('pow') && pow != 0 && pow != 1) return false;
  final st = double.tryParse('${s['stemp']}');
  if (s.containsKey('stemp') && (st == null || st < 10 || st > 35)) return false;
  final ct = double.tryParse('${s['ctemp']}');
  if (s.containsKey('ctemp') && (ct == null || ct < -10 || ct > 60)) return false;
  return true;
}

/// Merge a decrypted status push into an ACState.
ACState? decode(Map<String, dynamic> s, ACState? base) {
  if (!(s.containsKey('pow') || s.containsKey('stemp')) || !plausible(s)) return null;
  final cur = base ?? const ACState();
  String fanName(int id) {
    final n = idFans[id] ?? cur.fan;
    return (n == 'highhigh' || n == 'turbo') ? 'high' : n;
  }
  return cur.copyWith(
    power: s.containsKey('pow') ? _int(s['pow'], 0) == 1 : null,
    temp: s.containsKey('stemp') ? double.parse('${s['stemp']}').round() : null,
    mode: s.containsKey('mode') ? (idModes[_int(s['mode'], -1)] ?? cur.mode) : null,
    fan: s.containsKey('fspd') ? fanName(_int(s['fspd'], -1)) : null,
    ambient: s.containsKey('ctemp') ? double.tryParse('${s['ctemp']}') : null,
    conv: s.containsKey('eco') ? _int(s['eco'], cur.conv) : null,
    turbo: s.containsKey('turbo') ? _int(s['turbo'], 0) == 1 : null,
    esave: s.containsKey('esave') ? _int(s['esave'], 0) == 1 : null,
    sleep: s.containsKey('sleep') ? _int(s['sleep'], 0) == 1 : null,
    display: s.containsKey('display') ? _int(s['display'], 1) == 1 : null,
    vswing: s.containsKey('vswing') ? _int(s['vswing'], cur.vswing) : null,
    hswing: s.containsKey('hswing') ? _int(s['hswing'], cur.hswing) : null,
    offtimer: s.containsKey('offtimer') ? _int(s['offtimer'], 0) : null,
    ontimer: s.containsKey('ontimer') ? _int(s['ontimer'], 0) : null,
  );
}

/// True when every requested field is reflected in the status the AC pushed back.
bool matches(Map<String, dynamic> desired, Map<String, dynamic> status) {
  if (!plausible(status)) return false;
  for (final e in desired.entries) {
    if (e.key == 'src' || e.key == 'ts') continue;
    if (e.value is Map) {
      if (!matches({e.key: (e.value as Map)['value']}, status)) return false;
      continue;
    }
    if (!status.containsKey(e.key)) return false;
    final a = double.tryParse('${status[e.key]}'), b = double.tryParse('${e.value}');
    if (a != null && b != null) {
      if ((a - b).abs() > 0.01) return false;
    } else if ('${status[e.key]}' != '${e.value}') {
      return false;
    }
  }
  return true;
}

String convLabel(int v) => v == 0 ? 'Default' : (convLevels.contains(v) ? 'Level ${convLevels.indexOf(v)}' : '$v');
String swingLabel(int v) => v == swingAuto ? 'Swing' : (v == 0 ? 'Off' : 'Pos $v');
String timerLabel(int h) => h <= 0 ? 'Off' : '$h h';

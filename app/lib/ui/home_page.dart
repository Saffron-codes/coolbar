import 'package:flutter/material.dart';

import '../ble/ac_connection.dart';
import '../protocol/commands.dart';
import 'ac_illustration.dart';
import 'theme.dart';
import 'widgets.dart';

const _modeIcon = {
  'cool': Icons.ac_unit_rounded,
  'dry': Icons.water_drop_outlined,
  'fan': Icons.air_rounded,
  'auto': Icons.auto_mode_rounded,
};

class HomePage extends StatefulWidget {
  const HomePage({super.key, required this.conn});
  final ACConnection conn;

  @override
  State<HomePage> createState() => _HomePageState();
}

class _HomePageState extends State<HomePage> {
  ACConnection get c => widget.conn;
  ACState _local = const ACState();
  DateTime _holdUntil = DateTime.fromMillisecondsSinceEpoch(0);
  bool _reflected = false;
  double? _dragTemp;

  @override
  void initState() {
    super.initState();
    c.addListener(_onConn);
  }

  @override
  void dispose() {
    c.removeListener(_onConn);
    super.dispose();
  }

  void _onConn() {
    final first = !_reflected;
    if (c.acKnown && (first || (DateTime.now().isAfter(_holdUntil) && !c.busy))) {
      _local = c.ac;
      _reflected = true;
    }
    setState(() {});
  }

  void _set(ACState next) {
    _local = next;
    _holdUntil = DateTime.now().add(const Duration(seconds: 3));
    setState(() {});
    c.apply(next);
  }

  Future<void> _pickMode() async {
    final v = await pick<String>(context, title: 'Mode', current: _local.mode, options: [for (final m in modes) PickOption(m, _cap(m), icon: _modeIcon[m])]);
    if (v != null && v != _local.mode) _set(_local.copyWith(mode: v));
  }

  Future<void> _pickFan() async {
    final v = await pick<String>(context, title: 'Fan speed', current: _local.fan, options: [for (final f in fans) PickOption(f, _cap(f))]);
    if (v != null && v != _local.fan) _set(_local.copyWith(fan: v));
  }

  Future<void> _pickConv() async {
    final v = await pick<int>(context, title: '5-in-1 Convertible', current: _local.conv, options: [for (final l in convLevels) PickOption(l, convLabel(l))]);
    if (v != null && v != _local.conv) _set(_local.copyWith(conv: v));
  }

  Future<void> _pickTimer() async {
    final on = _local.power;
    final cur = on ? _local.offtimer : _local.ontimer;
    final v = await pick<int>(context, title: on ? 'Switch off in' : 'Switch on in', current: cur, options: [for (final h in timerPresets) PickOption(h, h == 0 ? 'Off' : '$h h')]);
    if (v == null || v == cur) return;
    _set(on ? _local.copyWith(offtimer: v) : _local.copyWith(ontimer: v));
  }

  Future<void> _pickSwing(bool vertical) async {
    final cur = vertical ? _local.vswing : _local.hswing;
    const vals = [0, 1, 2, 3, 4, 5, swingAuto];
    final v = await pick<int>(context, title: vertical ? 'Vertical swing' : 'Horizontal swing', current: cur, options: [for (final s in vals) PickOption(s, swingLabel(s))]);
    if (v == null || v == cur) return;
    _set(vertical ? _local.copyWith(vswing: v) : _local.copyWith(hswing: v));
  }

  static String _cap(String s) => s[0].toUpperCase() + s.substring(1);

  @override
  Widget build(BuildContext context) {
    final ac = _local;
    final cool = ac.mode == 'cool' && ac.power;
    final timer = ac.power ? ac.offtimer : ac.ontimer;
    final sliderVal = _dragTemp ?? ac.temp.toDouble();

    return Scaffold(
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.fromLTRB(20, 8, 20, 24),
          physics: const BouncingScrollPhysics(),
          children: [
            // header: room · light · power
            Row(children: [
              const Icon(Icons.thermostat_rounded, size: 18, color: C.dim),
              const SizedBox(width: 6),
              const Text('Room', style: TextStyle(fontSize: 14, color: C.dim)),
              const SizedBox(width: 6),
              Text(ac.ambient == null ? '—' : '${_fmt(ac.ambient!)} °C', style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
              const Spacer(),
              RoundButton(icon: Icons.lightbulb_outline_rounded, on: ac.display && ac.power, onColor: C.yellow, size: 42, onTap: () => _set(ac.copyWith(display: !ac.display))),
              const SizedBox(width: 10),
              RoundButton(icon: Icons.power_settings_new_rounded, on: ac.power, onColor: C.green, size: 42, onTap: () => _set(ac.copyWith(power: !ac.power))),
            ]),
            const SizedBox(height: 6),
            ACIllustration(ac: ac),
            const SizedBox(height: 4),

            // set-point + chips
            BigTemp(value: ac.temp),
            const SizedBox(height: 14),
            Wrap(spacing: 8, runSpacing: 8, children: [
              Chip2(label: 'Turbo', icon: Icons.bolt_rounded, on: ac.turbo, color: C.red, enabled: cool, onTap: () => _set(ac.copyWith(turbo: !ac.turbo))),
              Chip2(label: 'Energy save', icon: Icons.eco_rounded, on: ac.esave, color: C.green, onTap: () => _set(ac.copyWith(esave: !ac.esave))),
              Chip2(label: 'Sleep', icon: Icons.bedtime_rounded, on: ac.sleep, color: C.purple, onTap: () => _set(ac.copyWith(sleep: !ac.sleep))),
            ]),
            const SizedBox(height: 18),

            // slider
            Row(children: [
              RoundButton(icon: Icons.remove_rounded, size: 44, onTap: () => _set(ac.copyWith(temp: ac.temp - 1))),
              Expanded(
                child: Slider(
                  min: tempMin.toDouble(),
                  max: tempMax.toDouble(),
                  divisions: tempMax - tempMin,
                  value: sliderVal.clamp(tempMin.toDouble(), tempMax.toDouble()),
                  onChanged: (v) => setState(() => _dragTemp = v),
                  onChangeEnd: (v) {
                    _dragTemp = null;
                    final t = v.round();
                    if (t != ac.temp) _set(ac.copyWith(temp: t));
                  },
                ),
              ),
              RoundButton(icon: Icons.add_rounded, size: 44, onTap: () => _set(ac.copyWith(temp: ac.temp + 1))),
            ]),
            const Padding(
              padding: EdgeInsets.symmetric(horizontal: 58),
              child: Row(mainAxisAlignment: MainAxisAlignment.spaceBetween, children: [
                Text('$tempMin°', style: TextStyle(fontSize: 11, color: C.dim2)),
                Text('$tempMax°', style: TextStyle(fontSize: 11, color: C.dim2)),
              ]),
            ),
            const SizedBox(height: 14),

            // tiles
            GridView.count(
              crossAxisCount: 2,
              shrinkWrap: true,
              physics: const NeverScrollableScrollPhysics(),
              mainAxisSpacing: 10,
              crossAxisSpacing: 10,
              childAspectRatio: 1.55,
              children: [
                Tile(caption: 'Mode', value: _cap(ac.mode), icon: _modeIcon[ac.mode]!, active: ac.power, onTap: _pickMode),
                Tile(caption: 'Fan speed', value: ac.turbo ? 'Turbo' : _cap(ac.fan), icon: Icons.air_rounded, active: ac.power, onTap: _pickFan),
                Tile(caption: '5-in-1', value: convLabel(ac.conv), icon: Icons.tune_rounded, active: ac.conv != 0, enabled: cool, onTap: _pickConv),
                Tile(caption: 'Timer', value: timer > 0 ? '${ac.power ? "Off" : "On"} in $timer h' : 'Off', icon: Icons.timer_outlined, active: timer > 0, onTap: _pickTimer),
                Tile(caption: 'Swing ↕', value: swingLabel(ac.vswing), icon: Icons.swap_vert_rounded, active: ac.vswing == swingAuto, onTap: () => _pickSwing(true)),
                Tile(caption: 'Swing ↔', value: swingLabel(ac.hswing), icon: Icons.swap_horiz_rounded, active: ac.hswing == swingAuto, onTap: () => _pickSwing(false)),
              ],
            ),
            const SizedBox(height: 16),
            if (!c.paired) _PairCard(conn: c),
            const SizedBox(height: 8),
            _Footer(conn: c),
          ],
        ),
      ),
    );
  }

  static String _fmt(double v) => v == v.roundToDouble() ? '${v.round()}' : v.toStringAsFixed(1);
}

class _Footer extends StatelessWidget {
  const _Footer({required this.conn});
  final ACConnection conn;

  @override
  Widget build(BuildContext context) {
    final connected = conn.connected;
    final Color color = conn.busy ? C.orange : (connected && conn.paired ? C.green : (conn.phase == Phase.error ? C.red : C.orange));
    final text = conn.busy ? 'Syncing…' : conn.message;
    return Row(children: [
      if (conn.busy)
        const SizedBox(width: 14, height: 14, child: CircularProgressIndicator(strokeWidth: 2, color: C.orange))
      else
        Icon(connected ? Icons.bluetooth_connected_rounded : Icons.bluetooth_disabled_rounded, size: 16, color: color),
      const SizedBox(width: 8),
      Expanded(
        child: AnimatedSwitcher(
          duration: const Duration(milliseconds: 200),
          child: Text(text, key: ValueKey(text), style: TextStyle(fontSize: 12, color: color), maxLines: 2, overflow: TextOverflow.ellipsis),
        ),
      ),
      if (conn.paired)
        TextButton(
          onPressed: () => showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: C.card2,
              title: const Text('Forget pairing?'),
              content: const Text('You will need to put the AC in pairing mode again.'),
              actions: [
                TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Cancel')),
                TextButton(onPressed: () { conn.forget(); Navigator.pop(ctx); }, child: const Text('Forget')),
              ],
            ),
          ),
          child: const Text('Forget', style: TextStyle(fontSize: 12, color: C.dim)),
        ),
      if (conn.paired)
        TextButton(
          onPressed: () => showDialog(
            context: context,
            builder: (ctx) => AlertDialog(
              backgroundColor: C.card2,
              title: const Text('Pairing token'),
              content: SelectableText('uat: ${conn.cfg.uat}\npid: ${conn.cfg.pid}', style: const TextStyle(fontSize: 13)),
              actions: [TextButton(onPressed: () => Navigator.pop(ctx), child: const Text('Close'))],
            ),
          ),
          child: const Text('Token', style: TextStyle(fontSize: 12, color: C.dim)),
        ),
    ]);
  }
}

class _PairCard extends StatelessWidget {
  const _PairCard({required this.conn});
  final ACConnection conn;

  Future<void> _importDialog(BuildContext context) async {
    final uat = TextEditingController(), pid = TextEditingController();
    final ok = await showDialog<bool>(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: C.card2,
        title: const Text('Import pairing token'),
        content: Column(mainAxisSize: MainAxisSize.min, children: [
          const Text('The AC keeps one token. Copy "uat" and "pid" from the laptop\'s ~/.config/coolbar/device.json so both apps share it.',
              style: TextStyle(fontSize: 12, color: C.dim)),
          const SizedBox(height: 12),
          TextField(controller: uat, decoration: const InputDecoration(labelText: 'uat'), autocorrect: false),
          TextField(controller: pid, decoration: const InputDecoration(labelText: 'pid'), autocorrect: false),
        ]),
        actions: [
          TextButton(onPressed: () => Navigator.pop(ctx, false), child: const Text('Cancel')),
          FilledButton(onPressed: () => Navigator.pop(ctx, true), child: const Text('Import')),
        ],
      ),
    );
    if (ok == true) await conn.importToken(uat.text, pid.text);
  }

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(color: C.blue.withValues(alpha: 0.12), borderRadius: BorderRadius.circular(16)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        const Text('First-time pairing', style: TextStyle(fontWeight: FontWeight.w700)),
        const SizedBox(height: 8),
        const Text(
          '1. On the remote set mode COOL, temperature 16 °C, fan AUTO.\n'
          '2. Press one special remote button (heart, bubbles, bulb or the 88 display button) 5 times within 7 seconds until the AC display blinks.\n'
          '3. Tap Pair while it is blinking.',
          style: TextStyle(fontSize: 13, color: C.dim, height: 1.4),
        ),
        const SizedBox(height: 12),
        Row(children: [
          FilledButton.icon(
            onPressed: conn.connected && !conn.busy ? conn.pair : null,
            icon: const Icon(Icons.link_rounded),
            label: const Text('Pair with AC'),
          ),
          const SizedBox(width: 8),
          TextButton(onPressed: () => _importDialog(context), child: const Text('Already paired elsewhere?')),
        ]),
      ]),
    );
  }
}

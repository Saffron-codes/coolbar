import 'dart:math';

import 'package:flutter/material.dart';

import '../protocol/commands.dart';
import 'theme.dart';

/// The indoor unit with airflow underneath: speed from fan, colour from mode, sweep from swing.
/// Airflow eases in/out with power; the louver tilt follows the swing setting.
class ACIllustration extends StatefulWidget {
  const ACIllustration({super.key, required this.ac, this.height = 190});
  final ACState ac;
  final double height;

  @override
  State<ACIllustration> createState() => _ACIllustrationState();
}

class _ACIllustrationState extends State<ACIllustration> with SingleTickerProviderStateMixin {
  late final AnimationController _ctl = AnimationController(vsync: this, duration: const Duration(days: 1))..forward();
  double _flow = 0, _phase = 0, _sweep = 0;
  Duration _last = Duration.zero;

  @override
  void initState() {
    super.initState();
    _ctl.addListener(_tick);
  }

  void _tick() {
    final now = _ctl.lastElapsedDuration ?? Duration.zero;
    final dt = min(0.05, (now - _last).inMicroseconds / 1e6);
    _last = now;
    final target = widget.ac.power ? 1.0 : 0.0;
    _flow += (target - _flow) * min(1.0, dt * 6);
    if ((_flow - target).abs() < 0.002) _flow = target;
    if (_flow > 0.001) {
      final inten = widget.ac.turbo ? 1.0 : _intensity(widget.ac.fan);
      _phase += dt * (0.8 + 1.8 * inten);
      if (widget.ac.vswing == swingAuto || widget.ac.hswing == swingAuto) _sweep += dt * 1.1;
    }
    setState(() {});
  }

  @override
  void dispose() {
    _ctl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      height: widget.height,
      width: double.infinity,
      child: CustomPaint(painter: _Painter(widget.ac, _flow, _phase, _sweep)),
    );
  }
}

double _intensity(String fan) => const {'low': 0.45, 'medium': 0.7, 'high': 1.0, 'auto': 0.6}[fan] ?? 0.6;

class _Painter extends CustomPainter {
  _Painter(this.ac, this.flow, this.phase, this.sweep);
  final ACState ac;
  final double flow, phase, sweep;

  @override
  void paint(Canvas canvas, Size size) {
    final cx = size.width / 2;
    const uw = 220.0, uh = 62.0, top = 18.0;
    final ux = cx - uw / 2;
    final dim = 0.55 + 0.45 * flow;
    final body = RRect.fromRectAndRadius(Rect.fromLTWH(ux, top, uw, uh), const Radius.circular(14));

    // shadow + body
    canvas.drawRRect(body.shift(const Offset(0, 8)), Paint()..color = Colors.black.withValues(alpha: 0.35)..maskFilter = const MaskFilter.blur(BlurStyle.normal, 14));
    canvas.drawRRect(
      body,
      Paint()
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [Color.lerp(const Color(0xFF8C8C90), const Color(0xFFFCFCFD), dim)!, Color.lerp(const Color(0xFF66666A), const Color(0xFFCDCDD1), dim)!],
        ).createShader(body.outerRect),
    );
    // louver slot
    canvas.drawRRect(
      RRect.fromRectAndRadius(Rect.fromLTWH(ux + 18, top + uh - 16, uw - 36, 6), const Radius.circular(3)),
      Paint()..color = const Color(0xE61E1E23),
    );
    // display LED
    if (ac.power && ac.display) {
      canvas.drawCircle(Offset(ux + uw - 22, top + 16), 3, Paint()..color = C.green.withValues(alpha: 0.95));
    }

    if (flow <= 0.001) return;
    var color = C.modeColor[ac.mode] ?? C.modeColor['cool']!;
    if (ac.turbo) color = const Color(0xFF9AD8FF);
    final inten = ac.turbo ? 1.0 : _intensity(ac.fan);
    final tilt = ac.vswing == swingAuto ? sin(sweep) * 0.55 : (ac.vswing == 0 ? 0.0 : (ac.vswing - 3) * 0.22);
    final shift = ac.hswing == swingAuto ? sin(sweep * 0.8) * 26 : (ac.hswing == 0 ? 0.0 : (ac.hswing - 3) * 13);
    const n = 9;
    final y0 = top + uh - 6;
    final length = 72 + 34 * inten;
    for (var i = 0; i < n; i++) {
      final fx = ux + 30 + i * (uw - 60) / (n - 1) + shift;
      final offset = (phase * 40 + i * 13) % 40;
      final path = Path();
      const steps = 16;
      for (var k = 0; k <= steps; k++) {
        final t = k / steps;
        final y = y0 + offset * 0.35 + t * length;
        final x = fx + t * length * tilt + sin(t * 3.0 + phase * 2.2 + i * 0.7) * (5 + 6 * inten) * t;
        k == 0 ? path.moveTo(x, y) : path.lineTo(x, y);
      }
      final base = 0.85 * flow * (0.45 + 0.55 * inten);
      final paint = Paint()
        ..style = PaintingStyle.stroke
        ..strokeWidth = 2.4
        ..strokeCap = StrokeCap.round
        ..shader = LinearGradient(
          begin: Alignment.topCenter,
          end: Alignment.bottomCenter,
          colors: [color.withValues(alpha: base), color.withValues(alpha: base * 0.45), color.withValues(alpha: 0)],
          stops: const [0, 0.6, 1],
        ).createShader(Rect.fromLTWH(0, y0, size.width, length + 16));
      canvas.drawPath(path, paint);
    }
  }

  @override
  bool shouldRepaint(_Painter old) => true;
}

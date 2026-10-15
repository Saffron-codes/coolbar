import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'theme.dart';

/// Set-point readout that counts smoothly to new values and bounces on change.
class BigTemp extends StatefulWidget {
  const BigTemp({super.key, required this.value});
  final int value;

  @override
  State<BigTemp> createState() => _BigTempState();
}

class _BigTempState extends State<BigTemp> with SingleTickerProviderStateMixin {
  late final AnimationController _bounce = AnimationController(vsync: this, duration: const Duration(milliseconds: 380));

  @override
  void didUpdateWidget(BigTemp old) {
    super.didUpdateWidget(old);
    if (old.value != widget.value) _bounce.forward(from: 0);
  }

  @override
  void dispose() {
    _bounce.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _bounce,
      builder: (_, child) {
        final s = 1 + 0.06 * Curves.easeOut.transform(1 - (_bounce.value - 0.5).abs() * 2).clamp(0, 1);
        return Transform.scale(scale: s, alignment: Alignment.centerLeft, child: child);
      },
      child: TweenAnimationBuilder<double>(
        tween: Tween(end: widget.value.toDouble()),
        duration: const Duration(milliseconds: 350),
        curve: Curves.easeOutCubic,
        builder: (_, v, child) => Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          mainAxisSize: MainAxisSize.min,
          children: [
            Text('${v.round()}', style: const TextStyle(fontSize: 72, fontWeight: FontWeight.w300, height: 1, letterSpacing: -2)),
            const Padding(
              padding: EdgeInsets.only(top: 8, left: 4),
              child: Text('°C', style: TextStyle(fontSize: 22, color: C.dim)),
            ),
          ],
        ),
      ),
    );
  }
}

/// Round icon button (power, light, − / +).
class RoundButton extends StatelessWidget {
  const RoundButton({super.key, required this.icon, required this.onTap, this.on = false, this.onColor = C.green, this.size = 46});
  final IconData icon;
  final VoidCallback onTap;
  final bool on;
  final Color onColor;
  final double size;

  @override
  Widget build(BuildContext context) {
    return AnimatedContainer(
      duration: const Duration(milliseconds: 180),
      width: size,
      height: size,
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: on ? onColor.withValues(alpha: 0.18) : Colors.white.withValues(alpha: 0.07),
        border: Border.all(color: on ? onColor.withValues(alpha: 0.6) : C.stroke),
        boxShadow: on ? [BoxShadow(color: onColor.withValues(alpha: 0.35), blurRadius: 18, spreadRadius: 1)] : null,
      ),
      child: Material(
        color: Colors.transparent,
        shape: const CircleBorder(),
        clipBehavior: Clip.antiAlias,
        child: InkWell(
          onTap: () {
            HapticFeedback.lightImpact();
            onTap();
          },
          child: Icon(icon, size: size * 0.46, color: on ? onColor : C.text),
        ),
      ),
    );
  }
}

/// Toggle pill (Turbo / Energy save / Sleep).
class Chip2 extends StatelessWidget {
  const Chip2({super.key, required this.label, required this.icon, required this.on, required this.color, required this.onTap, this.enabled = true});
  final String label;
  final IconData icon;
  final bool on, enabled;
  final Color color;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final fg = on ? color : (enabled ? C.text : C.dim2);
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        decoration: BoxDecoration(
          color: on ? color.withValues(alpha: 0.16) : Colors.white.withValues(alpha: 0.07),
          borderRadius: BorderRadius.circular(22),
          border: Border.all(color: on ? color.withValues(alpha: 0.6) : C.stroke),
        ),
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(22),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: enabled
                ? () {
                    HapticFeedback.selectionClick();
                    onTap();
                  }
                : null,
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(icon, size: 16, color: fg),
                const SizedBox(width: 6),
                Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: fg)),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

/// Card tile: icon · chevron / caption / value. Tapping opens a picker.
class Tile extends StatelessWidget {
  const Tile({super.key, required this.caption, required this.value, required this.icon, required this.onTap, this.active = false, this.enabled = true});
  final String caption, value;
  final IconData icon;
  final bool active, enabled;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return Opacity(
      opacity: enabled ? 1 : 0.45,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 180),
        decoration: BoxDecoration(
          color: active ? C.blue.withValues(alpha: 0.13) : Colors.white.withValues(alpha: 0.07),
          borderRadius: BorderRadius.circular(16),
          border: Border.all(color: active ? C.blue.withValues(alpha: 0.5) : C.stroke),
        ),
        child: Material(
          color: Colors.transparent,
          borderRadius: BorderRadius.circular(16),
          clipBehavior: Clip.antiAlias,
          child: InkWell(
            onTap: enabled
                ? () {
                    HapticFeedback.selectionClick();
                    onTap();
                  }
                : null,
            child: Padding(
              padding: const EdgeInsets.fromLTRB(12, 10, 10, 10),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [Icon(icon, size: 18, color: C.text), const Spacer(), const Icon(Icons.expand_more_rounded, size: 18, color: C.dim)]),
                const SizedBox(height: 8),
                Text(caption, style: const TextStyle(fontSize: 11, color: C.dim)),
                const SizedBox(height: 2),
                AnimatedSwitcher(
                  duration: const Duration(milliseconds: 220),
                  transitionBuilder: (c, a) => FadeTransition(opacity: a, child: SlideTransition(position: Tween(begin: const Offset(0, 0.4), end: Offset.zero).animate(a), child: c)),
                  child: Text(value, key: ValueKey(value), style: const TextStyle(fontSize: 14, fontWeight: FontWeight.w700)),
                ),
              ]),
            ),
          ),
        ),
      ),
    );
  }
}

class PickOption<T> {
  const PickOption(this.value, this.label, {this.icon});
  final T value;
  final String label;
  final IconData? icon;
}

/// Bottom-sheet picker: every option listed, the current one marked. Returns the choice or null.
Future<T?> pick<T>(BuildContext context, {required String title, required List<PickOption<T>> options, required T current}) {
  return showModalBottomSheet<T>(
    context: context,
    backgroundColor: C.card2,
    barrierColor: Colors.black54,
    shape: const RoundedRectangleBorder(borderRadius: BorderRadius.vertical(top: Radius.circular(24))),
    builder: (ctx) => SafeArea(
      child: Padding(
        padding: const EdgeInsets.fromLTRB(12, 8, 12, 12),
        child: Column(mainAxisSize: MainAxisSize.min, children: [
          Container(width: 36, height: 4, margin: const EdgeInsets.only(bottom: 10), decoration: BoxDecoration(color: C.dim2, borderRadius: BorderRadius.circular(2))),
          Padding(padding: const EdgeInsets.only(bottom: 6), child: Text(title, style: const TextStyle(fontSize: 13, color: C.dim, fontWeight: FontWeight.w600))),
          for (final o in options)
            ListTile(
              dense: true,
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
              leading: o.icon != null ? Icon(o.icon, size: 20, color: o.value == current ? C.blueText : C.text) : null,
              title: Text(o.label, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: o.value == current ? C.blueText : C.text)),
              trailing: o.value == current ? const Icon(Icons.check_rounded, color: C.blueText) : null,
              onTap: () {
                HapticFeedback.selectionClick();
                Navigator.pop(ctx, o.value);
              },
            ),
        ]),
      ),
    ),
  );
}

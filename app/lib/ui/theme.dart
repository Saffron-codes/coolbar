import 'package:flutter/material.dart';

/// The palette of the desktop panel: near-black cards, white type, iOS-style accents.
class C {
  static const bg = Color(0xFF0E0E11);
  static const card = Color(0xFF17171B);
  static const card2 = Color(0xFF202026);
  static const stroke = Color(0x17FFFFFF);
  static const text = Color(0xFFF2F2F2);
  static const dim = Color(0x8CFFFFFF);
  static const dim2 = Color(0x59FFFFFF);
  static const blue = Color(0xFF0A84FF);
  static const blueText = Color(0xFF7CC4FF);
  static const green = Color(0xFF34C759);
  static const orange = Color(0xFFFF9F0A);
  static const red = Color(0xFFFF453A);
  static const yellow = Color(0xFFFFD60A);
  static const purple = Color(0xFFBF5AF2);

  static const modeColor = {
    'cool': Color(0xFF7CC4FF),
    'dry': Color(0xFF5EE0C8),
    'fan': Color(0xFFD1D1D6),
    'auto': Color(0xFFB58CFF),
    'heat': Color(0xFFFF9E6B),
  };
}

ThemeData buildTheme() {
  final base = ThemeData(brightness: Brightness.dark, useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: C.bg,
    colorScheme: base.colorScheme.copyWith(primary: C.blue, surface: C.card, onSurface: C.text),
    textTheme: base.textTheme.apply(bodyColor: C.text, displayColor: C.text),
    sliderTheme: const SliderThemeData(
      trackHeight: 34,
      activeTrackColor: Color(0x2EFFFFFF),
      inactiveTrackColor: Color(0x14FFFFFF),
      thumbColor: Color(0xFFECECEC),
      overlayColor: Color(0x1AFFFFFF),
      thumbShape: RoundSliderThumbShape(enabledThumbRadius: 13, elevation: 4),
      trackShape: RoundedRectSliderTrackShape(),
    ),
    splashFactory: InkSparkle.splashFactory,
  );
}

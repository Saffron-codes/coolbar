import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'ble/ac_connection.dart';
import 'ui/home_page.dart';
import 'ui/theme.dart';

final conn = ACConnection();

void main() {
  WidgetsFlutterBinding.ensureInitialized();
  SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
    statusBarColor: Colors.transparent,
    statusBarIconBrightness: Brightness.light,
    systemNavigationBarColor: Color(0xFF0E0E11),
  ));
  conn.start();
  runApp(const BlueStarApp());
}

class BlueStarApp extends StatelessWidget {
  const BlueStarApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Blue Star AC',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: HomePage(conn: conn),
    );
  }
}

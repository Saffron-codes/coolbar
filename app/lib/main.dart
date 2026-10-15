import 'dart:io';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import 'ble/ac_connection.dart';
import 'desktop/tray_shell.dart';
import 'ui/home_page.dart';
import 'ui/theme.dart';

final conn = ACConnection();
TrayShell? tray;

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  if (isDesktopShell) {
    tray = TrayShell(onQuit: () async {
      await conn.stop();
      exit(0);
    });
    await tray!.init();
  } else {
    SystemChrome.setSystemUIOverlayStyle(const SystemUiOverlayStyle(
      statusBarColor: Colors.transparent,
      statusBarIconBrightness: Brightness.light,
      systemNavigationBarColor: Color(0xFF0E0E11),
    ));
  }
  conn.start();
  runApp(const CoolBarApp());
}

class CoolBarApp extends StatelessWidget {
  const CoolBarApp({super.key});

  @override
  Widget build(BuildContext context) {
    final home = HomePage(conn: conn, onQuit: tray?.onQuit);
    return MaterialApp(
      title: 'CoolBar',
      debugShowCheckedModeBanner: false,
      theme: buildTheme(),
      home: isDesktopShell
          ? Container(
              decoration: BoxDecoration(
                color: C.bg,
                borderRadius: BorderRadius.circular(18),
                border: Border.all(color: C.stroke),
              ),
              clipBehavior: Clip.antiAlias,
              child: home,
            )
          : home,
    );
  }
}

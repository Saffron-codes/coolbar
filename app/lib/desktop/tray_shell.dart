/// Desktop "menubar" mode (Windows): a tray icon whose left click pops the control panel up next
/// to the taskbar as a frameless always-on-top window; clicking elsewhere hides it again.
/// Linux desktop builds get the same shell, but there the tray plugin only offers a menu, so the
/// panel is opened from the menu's "Open" item.
library;

import 'dart:io';

import 'package:flutter/material.dart';
import 'package:screen_retriever/screen_retriever.dart';
import 'package:tray_manager/tray_manager.dart';
import 'package:window_manager/window_manager.dart';

const panelSize = Size(420, 760);

bool get isDesktopShell => Platform.isWindows || Platform.isLinux || Platform.isMacOS;

class TrayShell with TrayListener, WindowListener {
  TrayShell({required this.onQuit});
  final VoidCallback onQuit;
  bool _visible = false;
  bool _ignoreBlur = false;

  Future<void> init() async {
    await windowManager.ensureInitialized();
    await windowManager.waitUntilReadyToShow(
      const WindowOptions(
        size: panelSize,
        minimumSize: panelSize,
        maximumSize: panelSize,
        titleBarStyle: TitleBarStyle.hidden,
        skipTaskbar: true,
        alwaysOnTop: true,
        backgroundColor: Colors.transparent,
        title: 'CoolBar',
      ),
      () async {
        await windowManager.setAsFrameless();
        await windowManager.hide();
      },
    );
    windowManager.addListener(this);

    await trayManager.setIcon(Platform.isWindows ? 'assets/tray.ico' : 'assets/tray.png');
    try {
      await trayManager.setToolTip('CoolBar');   // not implemented by the Linux backend
    } catch (_) {}
    await trayManager.setContextMenu(Menu(items: [
      MenuItem(key: 'open', label: 'Open CoolBar'),
      MenuItem.separator(),
      MenuItem(key: 'quit', label: 'Quit'),
    ]));
    trayManager.addListener(this);
  }

  Future<void> toggle() async => _visible ? hide() : show();

  Future<void> show() async {
    final display = await screenRetriever.getPrimaryDisplay();
    final area = display.visibleSize ?? display.size;
    final origin = display.visiblePosition ?? Offset.zero;
    final scale = display.scaleFactor?.toDouble() ?? 1.0;
    final w = panelSize.width, h = panelSize.height;
    // Windows: taskbar at the bottom, tray at the right -> anchor bottom-right of the work area.
    // Linux/macOS: top bar -> anchor top-right.
    final x = origin.dx + area.width / scale - w - 12;
    final y = Platform.isWindows ? origin.dy + area.height / scale - h - 12 : origin.dy + 12;
    await windowManager.setPosition(Offset(x, y));
    _ignoreBlur = true;
    await windowManager.show();
    await windowManager.focus();
    _visible = true;
    Future.delayed(const Duration(milliseconds: 300), () => _ignoreBlur = false);
  }

  Future<void> hide() async {
    _visible = false;
    await windowManager.hide();
  }

  // ---- tray events ----
  @override
  void onTrayIconMouseDown() => toggle();

  @override
  void onTrayIconRightMouseDown() => trayManager.popUpContextMenu();

  @override
  void onTrayMenuItemClick(MenuItem menuItem) {
    switch (menuItem.key) {
      case 'open':
        show();
      case 'quit':
        onQuit();
    }
  }

  // ---- window events ----
  @override
  void onWindowBlur() {
    if (!_ignoreBlur) hide();   // click outside the popover closes it, like a menubar app
  }

  @override
  void onWindowClose() => hide();
}

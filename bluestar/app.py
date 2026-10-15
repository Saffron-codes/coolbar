"""Entry point: GTK on the main thread, BLE + tray D-Bus item on a background asyncio thread."""
from __future__ import annotations

import copy
import logging
import os
import signal
import sys

# Popup windows need exact placement; GTK3 can only do that on X11, which XWayland provides.
os.environ.setdefault("GDK_BACKEND", "x11")

import gi  # noqa: E402

gi.require_version("Gtk", "3.0")
from gi.repository import GLib, Gtk  # noqa: E402

from .ble import LinkState, Worker  # noqa: E402
from .panel import Panel  # noqa: E402
from .tray import register  # noqa: E402

ICON = "weather-snow-symbolic"
TITLE = "Blue Star AC"


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    logging.basicConfig(level=logging.DEBUG if "-v" in argv else logging.INFO,
                        format="%(asctime)s %(name)s %(levelname)s %(message)s")
    tray: list = []

    def quit_app() -> None:
        worker.stop()
        worker.join(timeout=4)        # let the BLE session disconnect, or the AC stays "connected" to nobody
        Gtk.main_quit()

    panel = Panel(on_change=lambda st: worker.post(lambda: worker.apply(st)),
                  on_pair=lambda: worker.post(worker.pair), on_quit=quit_app)

    def on_state(state: LinkState) -> None:
        GLib.idle_add(panel.update, copy.copy(state))
        if tray:
            try:
                tray[0].set_title(f"{TITLE} – {state.message or state.phase}")
                if state.phase == "connected" and state.ac_known:
                    tray[0].set_label(f"{state.ac.temp}°" if state.ac.power else "off")
                else:
                    tray[0].set_label("")
            except Exception as e:  # noqa: BLE001 - a tooltip glitch must never take the BLE loop down
                logging.warning("tray update failed: %s", e)

    worker = Worker(on_state=on_state)

    async def start_tray() -> None:
        try:
            tray.append(await register(lambda: GLib.idle_add(panel.toggle), ICON, TITLE))
            logging.info("tray item registered")
        except Exception as e:  # noqa: BLE001
            logging.error("tray registration failed (is the AppIndicator extension enabled?): %s", e)

    worker.extra_tasks.append(start_tray)
    worker.start()
    for sig in (signal.SIGTERM, signal.SIGINT):           # disconnect the AC cleanly on kill/Ctrl-C
        GLib.unix_signal_add(GLib.PRIORITY_HIGH, sig, lambda *_: (quit_app(), False)[1])
    try:
        Gtk.main()
    except KeyboardInterrupt:
        quit_app()
    return 0


if __name__ == "__main__":
    sys.exit(main())

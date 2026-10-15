"""StatusNotifierItem (the freedesktop tray protocol GNOME's AppIndicator extension speaks), via dbus_next.

We deliberately export NO menu (`Menu = /NO_DBUSMENU`, `ItemIsMenu = false`) so a left click
reaches `Activate`, which toggles our own panel - the macOS menubar-app behaviour.
"""
from __future__ import annotations

import asyncio
import os
from typing import Callable

from dbus_next.aio import MessageBus
from dbus_next.constants import PropertyAccess
from dbus_next.service import ServiceInterface, dbus_property, method, signal

WATCHER = "org.kde.StatusNotifierWatcher"


class StatusNotifierItem(ServiceInterface):
    def __init__(self, on_activate: Callable[[], None], icon: str, title: str):
        super().__init__("org.kde.StatusNotifierItem")
        self._on_activate = on_activate
        self._icon = icon
        self._title = title
        self._status = "Active"
        self._label = ""

    # -- properties the host reads ------------------------------------------
    @dbus_property(access=PropertyAccess.READ)
    def Category(self) -> "s":
        return "Hardware"

    @dbus_property(access=PropertyAccess.READ)
    def Id(self) -> "s":
        return "coolbar"

    @dbus_property(access=PropertyAccess.READ)
    def Title(self) -> "s":
        return self._title

    @dbus_property(access=PropertyAccess.READ)
    def Status(self) -> "s":
        return self._status

    @dbus_property(access=PropertyAccess.READ)
    def WindowId(self) -> "i":
        return 0

    @dbus_property(access=PropertyAccess.READ)
    def IconName(self) -> "s":
        return self._icon

    @dbus_property(access=PropertyAccess.READ)
    def IconThemePath(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def IconPixmap(self) -> "a(iiay)":
        return []

    @dbus_property(access=PropertyAccess.READ)
    def OverlayIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def AttentionIconName(self) -> "s":
        return ""

    @dbus_property(access=PropertyAccess.READ)
    def ToolTip(self) -> "(sa(iiay)ss)":
        return ["", [], self._title, ""]

    @dbus_property(access=PropertyAccess.READ)
    def ItemIsMenu(self) -> "b":
        return False

    @dbus_property(access=PropertyAccess.READ)
    def Menu(self) -> "o":
        return "/NO_DBUSMENU"

    @dbus_property(access=PropertyAccess.READ)
    def XAyatanaLabel(self) -> "s":
        return self._label

    @dbus_property(access=PropertyAccess.READ)
    def XAyatanaLabelGuide(self) -> "s":
        return "88°"

    # -- methods the host calls ---------------------------------------------
    @method()
    def Activate(self, x: "i", y: "i"):
        self._on_activate()

    @method()
    def SecondaryActivate(self, x: "i", y: "i"):
        self._on_activate()

    @method()
    def ContextMenu(self, x: "i", y: "i"):
        self._on_activate()

    @method()
    def Scroll(self, delta: "i", orientation: "s"):
        pass

    @method()
    def ProvideXdgActivationToken(self, token: "s"):
        pass

    # -- signals -------------------------------------------------------------
    @signal()
    def NewIcon(self):
        pass

    @signal()
    def NewTitle(self):
        pass

    @signal()
    def NewToolTip(self):
        pass

    @signal()
    def NewStatus(self) -> "s":
        return self._status

    @signal()
    def XAyatanaNewLabel(self) -> "ss":
        return [self._label, "88°"]

    # -- helpers -------------------------------------------------------------
    def set_icon(self, name: str) -> None:
        if name != self._icon:
            self._icon = name
            self.emit_properties_changed({"IconName": name})
            self.NewIcon()

    def set_label(self, label: str) -> None:
        """Text shown next to the icon in the top bar (GNOME AppIndicator supports the Ayatana label)."""
        if label != self._label:
            self._label = label
            self.emit_properties_changed({"XAyatanaLabel": label})
            self.XAyatanaNewLabel()

    def set_title(self, title: str) -> None:
        if title != self._title:
            self._title = title
            self.emit_properties_changed({"Title": title, "ToolTip": ["", [], title, ""]})
            self.NewTitle()
            self.NewToolTip()


async def register(on_activate: Callable[[], None], icon: str, title: str) -> StatusNotifierItem:
    bus = await MessageBus().connect()
    item = StatusNotifierItem(on_activate, icon, title)
    bus.export("/StatusNotifierItem", item)
    name = f"org.kde.StatusNotifierItem-{os.getpid()}-1"
    await bus.request_name(name)
    # The watcher lives in gnome-shell's extension; it may come up after us (e.g. at login), so retry.
    for attempt in range(60):
        try:
            intro = await bus.introspect(WATCHER, "/StatusNotifierWatcher")
            watcher = bus.get_proxy_object(WATCHER, "/StatusNotifierWatcher", intro).get_interface(WATCHER)
            await watcher.call_register_status_notifier_item(name)
            break
        except Exception:  # noqa: BLE001
            if attempt == 59:
                raise
            await asyncio.sleep(5)
    item._bus = bus  # keep alive
    return item

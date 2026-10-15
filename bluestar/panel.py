"""The drop-down panel: an undecorated popup under the top bar, drawn like a macOS menubar popover.

Feature set = the IR remote: power, temperature, mode, fan, 5-in-1 convertible, turbo, timer,
vertical/horizontal swing, energy save, sleep, light. Layout, top to bottom:
  room temperature · light · power
  animated indoor unit (airflow speed from fan, colour from mode, louver sweep from swing)
  big set-point (counts to new values) · chips: Turbo / Energy save / Sleep
  slider with − / +
  tiles: Mode · Fan · 5-in-1 · Timer  /  Swing ↕ · Swing ↔
  footer: Connected / Syncing…
"""
from __future__ import annotations

import math
import time
from dataclasses import replace
from typing import Callable

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk  # noqa: E402

from .ble import LinkState  # noqa: E402
from .commands import (CONV_LEVELS, FANS, MODES, SWING_AUTO, TEMP_MAX, TEMP_MIN,  # noqa: E402
                       TIMER_PRESETS, ACState)

PANEL_WIDTH = 420
HOLD_AFTER_USER_CHANGE = 3.0      # seconds during which AC pushes do not overwrite the controls

CSS = b"""
window.bs-panel { background-color: transparent; }
.bs-card { background-color: rgba(22,22,26,0.97); border-radius: 18px; padding: 14px 16px 12px 16px;
           border: 1px solid rgba(255,255,255,0.09); color: #f2f2f2; }
.bs-dim   { color: rgba(255,255,255,0.5); font-size: 11px; }
.bs-room  { color: rgba(255,255,255,0.8); font-size: 12px; }
.bs-roomv { color: #ffffff; font-size: 12px; font-weight: 700; }
.bs-msg   { color: rgba(255,255,255,0.8); font-size: 11px; }
.bs-foot  { color: rgba(255,255,255,0.6); font-size: 11px; }
.bs-ok  { color: #34c759; }
.bs-warn { color: #ff9f0a; }
.bs-err { color: #ff453a; }

.bs-card button { background-image: none; background-color: rgba(255,255,255,0.07);
                  border: 1px solid rgba(255,255,255,0.06); color: #f2f2f2; box-shadow: none; text-shadow: none;
                  transition: background-color 120ms ease, border-color 120ms ease, color 120ms ease; }
.bs-card button:hover  { background-color: rgba(255,255,255,0.13); }
.bs-card button:active { background-color: rgba(255,255,255,0.2); }
.bs-round  { border-radius: 19px; min-width: 36px; min-height: 36px; padding: 0; }
.bs-hdrbtn { border-radius: 17px; min-width: 32px; min-height: 32px; padding: 0; }
.bs-hdrbtn.on  { background-color: rgba(255,214,10,0.16); border-color: rgba(255,214,10,0.5); color: #ffd60a; }
.bs-power.on { background-color: rgba(52,199,89,0.18); border-color: rgba(52,199,89,0.6); color: #34c759; }

.bs-chip { border-radius: 15px; padding: 5px 10px; font-size: 11px; font-weight: 600; }
.bs-chip.on { background-color: rgba(10,132,255,0.18); border-color: rgba(10,132,255,0.6); color: #7cc4ff; }
.bs-chip.turbo.on { background-color: rgba(255,69,58,0.16); border-color: rgba(255,69,58,0.6); color: #ff6b61; }
.bs-chip.esave.on { background-color: rgba(52,199,89,0.16); border-color: rgba(52,199,89,0.6); color: #4cd964; }
.bs-chip.sleep.on { background-color: rgba(191,90,242,0.16); border-color: rgba(191,90,242,0.6); color: #d08cff; }

.bs-tile { border-radius: 12px; padding: 8px 9px 7px 9px; min-height: 0; }
.bs-tile.active { border-color: rgba(10,132,255,0.5); background-color: rgba(10,132,255,0.13); }
.bs-tile-cap { color: rgba(255,255,255,0.5); font-size: 10px; }
.bs-tile-val { color: #ffffff; font-size: 12px; font-weight: 700; }

.bs-card scale trough { min-height: 30px; border-radius: 15px; background-color: rgba(255,255,255,0.08); border: none; }
.bs-card scale highlight { border-radius: 15px; background-color: rgba(255,255,255,0.16); }
.bs-card scale slider { min-width: 22px; min-height: 22px; margin: -4px; border-radius: 9px;
                        background-color: #ececec; border: none; box-shadow: 0 2px 6px rgba(0,0,0,0.45); }
.bs-card scale slider:hover { background-color: #ffffff; }

popover.bs-pop, popover.bs-pop > contents, popover.bs-pop.background {
    background-color: rgba(34,34,40,0.99); border: 1px solid rgba(255,255,255,0.12); border-radius: 12px;
    padding: 4px; box-shadow: 0 8px 24px rgba(0,0,0,0.5); color: #f2f2f2; }
popover.bs-pop button.bs-item { background-image: none; background-color: transparent; border: none; box-shadow: none;
    text-shadow: none; border-radius: 8px; padding: 6px 10px; min-width: 140px; min-height: 0; color: #f2f2f2; font-size: 12px;
    transition: background-color 100ms ease; }
popover.bs-pop button.bs-item:hover { background-color: rgba(255,255,255,0.1); }
popover.bs-pop button.bs-item.current { color: #7cc4ff; }
popover.bs-pop button.bs-item label { color: inherit; }
.bs-quit { background-color: transparent; border: none; color: rgba(255,255,255,0.5); font-size: 11px; padding: 2px 6px; }
.bs-pairbox { background-color: rgba(10,132,255,0.12); border-radius: 12px; padding: 10px 12px; }
.bs-pair { background-color: #0a84ff; border-color: #0a84ff; color: white; font-weight: 600; }
"""

MODE_ICON = {"cool": "weather-snow-symbolic", "dry": "weather-showers-scattered-symbolic",
             "fan": "weather-windy-symbolic", "auto": "power-profile-balanced-symbolic"}
MODE_RGB = {"cool": (0.49, 0.77, 1.0), "dry": (0.37, 0.88, 0.78), "fan": (0.82, 0.82, 0.85),
            "auto": (0.71, 0.55, 1.0), "heat": (1.0, 0.62, 0.42)}
FAN_INTENSITY = {"low": 0.45, "medium": 0.7, "high": 1.0, "auto": 0.6}
PHASE_TEXT = {"connected": "Connected", "connecting": "Connecting…", "scanning": "Searching for the AC…",
              "error": "Not connected"}
PAIR_HELP = ("First-time pairing (one time only):\n"
             "1. On the remote set mode COOL, temperature 16 °C, fan AUTO.\n"
             "2. Press one special remote button (heart, bubbles, bulb or the 88 display button)\n"
             "    5 times within 7 seconds until the AC display blinks.\n"
             "3. Click Pair while it is blinking.")


def _ease_out(t: float) -> float:
    return 1 - (1 - t) ** 3


def _rounded_rect(cr, x, y, w, h, r):
    cr.new_sub_path()
    cr.arc(x + w - r, y + r, r, -math.pi / 2, 0)
    cr.arc(x + w - r, y + h - r, r, 0, math.pi / 2)
    cr.arc(x + r, y + h - r, r, math.pi / 2, math.pi)
    cr.arc(x + r, y + r, r, math.pi, 3 * math.pi / 2)
    cr.close_path()


def swing_label(v: int) -> str:
    return "Swing" if v == SWING_AUTO else ("Off" if v == 0 else f"Pos {v}")


def conv_label(v: int) -> str:
    return "Default" if v == 0 else f"Level {CONV_LEVELS.index(v)}" if v in CONV_LEVELS else str(v)


def timer_label(hours: int) -> str:
    return "Off" if hours <= 0 else f"{hours} h"


class Illustration(Gtk.DrawingArea):
    """The indoor unit with animated airflow underneath."""

    def __init__(self):
        super().__init__()
        self.set_size_request(PANEL_WIDTH - 32, 122)
        self.ac = ACState()
        self._flow = 0.0            # eased 0..1 airflow visibility
        self._phase = 0.0
        self._sweep = 0.0           # louver sweep phase
        self._last = None
        self.connect("draw", self._draw)
        self.add_tick_callback(self._tick)

    def set_state(self, ac: ACState) -> None:
        self.ac = ac
        self.queue_draw()

    def _tick(self, _w, clock) -> bool:
        now = clock.get_frame_time() / 1e6
        dt = 0 if self._last is None else min(0.05, now - self._last)
        self._last = now
        target = 1.0 if self.ac.power else 0.0
        if abs(self._flow - target) > 0.002:
            self._flow += (target - self._flow) * min(1.0, dt * 6)
            self.queue_draw()
        elif self._flow != target:
            self._flow = target
            self.queue_draw()
        if self._flow > 0.001:
            inten = 1.0 if self.ac.turbo else FAN_INTENSITY.get(self.ac.fan, 0.6)
            self._phase += dt * (0.8 + 1.8 * inten)
            if self.ac.vswing == SWING_AUTO or self.ac.hswing == SWING_AUTO:
                self._sweep += dt * 1.1
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _w, cr) -> bool:
        import cairo
        ac = self.ac
        W = self.get_allocated_width()
        cx, top = W / 2, 10
        uw, uh = 156, 44
        ux = cx - uw / 2
        dim = 0.55 + 0.45 * self._flow

        for i in range(6, 0, -1):                       # soft shadow
            cr.set_source_rgba(0, 0, 0, 0.05)
            _rounded_rect(cr, ux - i, top - i + 6, uw + 2 * i, uh + 2 * i, 12 + i)
            cr.fill()
        grad = cairo.LinearGradient(0, top, 0, top + uh)
        grad.add_color_stop_rgb(0, 0.97 * dim + 0.03, 0.97 * dim + 0.03, 0.98 * dim + 0.02)
        grad.add_color_stop_rgb(1, 0.80 * dim, 0.80 * dim, 0.82 * dim)
        cr.set_source(grad)
        _rounded_rect(cr, ux, top, uw, uh, 10)
        cr.fill()
        cr.set_source_rgba(0.12, 0.12, 0.14, 0.9)        # louver slot
        _rounded_rect(cr, ux + 12, top + uh - 12, uw - 24, 5, 2.5)
        cr.fill()
        if ac.power and ac.display:                       # display LED
            cr.set_source_rgba(0.2, 0.78, 0.35, 0.9)
            cr.arc(ux + uw - 16, top + 12, 2.2, 0, 2 * math.pi)
            cr.fill()

        if self._flow > 0.001:
            r, g, b = MODE_RGB.get(ac.mode, MODE_RGB["cool"])
            if ac.turbo:
                r, g, b = MODE_RGB["heat"] if ac.mode == "heat" else (0.6, 0.85, 1.0)
            inten = 1.0 if ac.turbo else FAN_INTENSITY.get(ac.fan, 0.6)
            # louver direction: vertical swing sweeps the fall angle, horizontal swing shifts sideways
            if ac.vswing == SWING_AUTO:
                tilt = math.sin(self._sweep) * 0.55
            elif ac.vswing == 0:
                tilt = 0.0
            else:
                tilt = (ac.vswing - 3) * 0.22
            if ac.hswing == SWING_AUTO:
                shift = math.sin(self._sweep * 0.8) * 18
            elif ac.hswing == 0:
                shift = 0.0
            else:
                shift = (ac.hswing - 3) * 9
            n = 7
            y0 = top + uh - 4
            length = 56 + 22 * inten
            for i in range(n):
                fx = ux + 22 + i * (uw - 44) / (n - 1) + shift
                offset = (self._phase * 40 + i * 13) % 40
                cr.set_line_width(2.0)
                cr.new_path()
                steps = 14
                for k in range(steps + 1):
                    t = k / steps
                    y = y0 + offset * 0.35 + t * length
                    x = fx + t * length * tilt + math.sin(t * 3.0 + self._phase * 2.2 + i * 0.7) * (4 + 5 * inten) * t
                    cr.move_to(x, y) if k == 0 else cr.line_to(x, y)
                pat = cairo.LinearGradient(0, y0, 0, y0 + length)
                base = 0.8 * self._flow * (0.45 + 0.55 * inten)
                pat.add_color_stop_rgba(0.0, r, g, b, base)
                pat.add_color_stop_rgba(0.6, r, g, b, base * 0.45)
                pat.add_color_stop_rgba(1.0, r, g, b, 0.0)
                cr.set_source(pat)
                cr.stroke()
        return True


class BigTemp(Gtk.DrawingArea):
    """Set-point readout that counts smoothly to new values and bounces on change."""

    def __init__(self):
        super().__init__()
        self.set_size_request(118, 54)
        self._shown = 24.0
        self._target = 24.0
        self._from = 24.0
        self._t0 = 0.0
        self._bounce = -10.0
        self.connect("draw", self._draw)
        self.add_tick_callback(self._tick)

    def set_value(self, v: int, animate: bool = True) -> None:
        if v == self._target:
            return
        self._from = self._shown
        self._target = float(v)
        now = time.monotonic()
        self._t0 = now if animate else -1.0
        self._bounce = now if animate else -10.0
        if not animate:
            self._shown = self._target
        self.queue_draw()

    def _tick(self, _w, _clock) -> bool:
        if self._shown != self._target:
            t = min(1.0, (time.monotonic() - self._t0) / 0.35) if self._t0 > 0 else 1.0
            self._shown = self._from + (self._target - self._from) * _ease_out(t)
            if t >= 1.0:
                self._shown = self._target
            self.queue_draw()
        elif time.monotonic() - self._bounce < 0.4:
            self.queue_draw()
        return GLib.SOURCE_CONTINUE

    def _draw(self, _w, cr) -> bool:
        H = self.get_allocated_height()
        bt = time.monotonic() - self._bounce
        scale = 1.0 + (0.06 * math.sin(bt / 0.4 * math.pi) if 0 <= bt < 0.4 else 0.0)
        cr.save()
        cr.translate(0, H / 2)
        cr.scale(scale, scale)
        cr.select_font_face("Inter", 0, 0)
        cr.set_font_size(46)
        cr.set_source_rgb(1, 1, 1)
        txt = f"{int(round(self._shown))}"
        cr.move_to(0, 17)
        cr.show_text(txt)
        adv = cr.text_extents(txt).x_advance
        cr.set_font_size(16)
        cr.set_source_rgba(1, 1, 1, 0.6)
        cr.move_to(adv + 4, -2)
        cr.show_text("°C")
        cr.restore()
        return True


class Tile(Gtk.Button):
    """A card: icon top-left, chevron top-right, caption, value. Click cycles through options."""

    def __init__(self, caption: str, icon: str, on_click: Callable[[], None]):
        super().__init__()
        self.get_style_context().add_class("bs-tile")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=3)
        head = Gtk.Box()
        self.icon = Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU)
        head.pack_start(self.icon, False, False, 0)
        head.pack_end(Gtk.Image.new_from_icon_name("pan-down-symbolic", Gtk.IconSize.MENU), False, False, 0)
        box.pack_start(head, False, False, 0)
        cap = Gtk.Label(label=caption, xalign=0)
        cap.get_style_context().add_class("bs-tile-cap")
        box.pack_start(cap, False, False, 0)
        self.value = Gtk.Label(label="", xalign=0)
        self.value.get_style_context().add_class("bs-tile-val")
        box.pack_start(self.value, False, False, 0)
        self.add(box)
        self.connect("clicked", lambda *_: on_click())

    def set(self, text: str, icon: str | None = None, active: bool = False) -> None:
        self.value.set_text(text)
        if icon:
            self.icon.set_from_icon_name(icon, Gtk.IconSize.MENU)
        ctx = self.get_style_context()
        ctx.add_class("active") if active else ctx.remove_class("active")


class Chip(Gtk.Button):
    """Small toggle pill with an icon and a label."""

    def __init__(self, text: str, icon: str, kind: str, on_click: Callable[[], None]):
        super().__init__()
        for c in ("bs-chip", kind):
            self.get_style_context().add_class(c)
        box = Gtk.Box(spacing=5)
        box.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
        box.pack_start(Gtk.Label(label=text), False, False, 0)
        self.add(box)
        self.connect("clicked", lambda *_: on_click())

    def set_on(self, on: bool) -> None:
        ctx = self.get_style_context()
        ctx.add_class("on") if on else ctx.remove_class("on")


class Panel(Gtk.Window):
    def __init__(self, on_change: Callable[[ACState], None], on_pair: Callable[[], None],
                 on_quit: Callable[[], None]):
        super().__init__(type=Gtk.WindowType.POPUP)
        self._on_change = on_change
        self._on_pair = on_pair
        self._on_quit = on_quit
        self._state = ACState()
        self._syncing = False
        self._grabbed = False
        self._show_pair = True
        self._hold_until = 0.0
        self._slider_timer = 0
        self._reflected = False

        self.get_style_context().add_class("bs-panel")
        self.set_default_size(PANEL_WIDTH, -1)
        self.set_resizable(False)
        self.set_keep_above(True)
        screen = self.get_screen()
        visual = screen.get_rgba_visual()
        if visual and screen.is_composited():
            self.set_visual(visual)
        self.set_app_paintable(True)
        prov = Gtk.CssProvider()
        prov.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_screen(screen, prov, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.add(self._build())
        self.connect("button-press-event", self._on_button_press)
        self.connect("key-press-event", self._on_key)

    # ------------------------------------------------------------------ UI
    def _build(self) -> Gtk.Widget:
        card = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        card.get_style_context().add_class("bs-card")

        head = Gtk.Box(spacing=6)
        room_ic = Gtk.Image.new_from_icon_name("display-brightness-symbolic", Gtk.IconSize.MENU)
        room_ic.set_opacity(0.7)
        head.pack_start(room_ic, False, False, 0)
        lab = Gtk.Label(label="Room")
        lab.get_style_context().add_class("bs-room")
        head.pack_start(lab, False, False, 0)
        self.room = Gtk.Label(label="—")
        self.room.get_style_context().add_class("bs-roomv")
        head.pack_start(self.room, False, False, 0)
        self.power = Gtk.Button()
        self.power.get_style_context().add_class("bs-hdrbtn")
        self.power.get_style_context().add_class("bs-power")
        self.power.add(Gtk.Image.new_from_icon_name("system-shutdown-symbolic", Gtk.IconSize.MENU))
        self.power.set_tooltip_text("Power")
        self.power.connect("clicked", lambda *_: self._set(power=not self._state.power))
        head.pack_end(self.power, False, False, 0)
        self.light = Gtk.Button()
        self.light.get_style_context().add_class("bs-hdrbtn")
        self.light.add(Gtk.Image.new_from_icon_name("display-brightness-symbolic", Gtk.IconSize.MENU))
        self.light.set_tooltip_text("Light (indoor unit display)")
        self.light.connect("clicked", lambda *_: self._set(display=not self._state.display))
        head.pack_end(self.light, False, False, 0)
        card.pack_start(head, False, False, 0)

        self.illus = Illustration()
        card.pack_start(self.illus, False, False, 0)

        row = Gtk.Box(spacing=6)
        self.big = BigTemp()
        row.pack_start(self.big, False, False, 0)
        chips = Gtk.Box(spacing=6, valign=Gtk.Align.CENTER)
        self.c_turbo = Chip("Turbo", "weather-storm-symbolic", "turbo", lambda: self._set(turbo=not self._state.turbo))
        self.c_esave = Chip("Energy save", "power-profile-power-saver-symbolic", "esave",
                            lambda: self._set(esave=not self._state.esave))
        self.c_sleep = Chip("Sleep", "weather-clear-night-symbolic", "sleep", lambda: self._set(sleep=not self._state.sleep))
        for c in (self.c_turbo, self.c_esave, self.c_sleep):
            chips.pack_start(c, False, False, 0)
        row.pack_end(chips, False, False, 0)
        card.pack_start(row, False, False, 0)

        srow = Gtk.Box(spacing=10)
        minus = self._round("list-remove-symbolic", lambda *_: self._bump(-1))
        plus = self._round("list-add-symbolic", lambda *_: self._bump(+1))
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, TEMP_MIN, TEMP_MAX, 1)
        self.scale.set_draw_value(False)
        self.scale.set_round_digits(0)
        self.scale.set_hexpand(True)
        self.scale.connect("value-changed", self._on_slider)
        srow.pack_start(minus, False, False, 0)
        srow.pack_start(self.scale, True, True, 0)
        srow.pack_start(plus, False, False, 0)
        card.pack_start(srow, False, False, 0)
        lim = Gtk.Box()
        lo = Gtk.Label(label=f"{TEMP_MIN}°", margin_start=52)
        hi = Gtk.Label(label=f"{TEMP_MAX}°", margin_end=52)
        for w in (lo, hi):
            w.get_style_context().add_class("bs-dim")
        lim.pack_start(lo, False, False, 0)
        lim.pack_end(hi, False, False, 0)
        card.pack_start(lim, False, False, 0)

        tiles = Gtk.Box(spacing=8, homogeneous=True, margin_top=2)
        self.t_mode = Tile("Mode", MODE_ICON["cool"], lambda: self._pick(
            self.t_mode, "mode", [(m, m.capitalize(), MODE_ICON[m]) for m in MODES]))
        self.t_fan = Tile("Fan speed", "weather-windy-symbolic", lambda: self._pick(
            self.t_fan, "fan", [(f, f.capitalize(), None) for f in FANS]))
        self.t_conv = Tile("5-in-1", "power-profile-balanced-symbolic", lambda: self._pick(
            self.t_conv, "conv", [(c, conv_label(c), None) for c in CONV_LEVELS]))
        self.t_timer = Tile("Timer", "preferences-system-time-symbolic", self._pick_timer)
        for t in (self.t_mode, self.t_fan, self.t_conv, self.t_timer):
            tiles.pack_start(t, True, True, 0)
        card.pack_start(tiles, False, False, 0)
        tiles2 = Gtk.Box(spacing=8, homogeneous=True)
        swings = (0, 1, 2, 3, 4, 5, SWING_AUTO)
        self.t_vswing = Tile("Swing ↕", "go-bottom-symbolic", lambda: self._pick(
            self.t_vswing, "vswing", [(v, swing_label(v), None) for v in swings]))
        self.t_hswing = Tile("Swing ↔", "go-last-symbolic", lambda: self._pick(
            self.t_hswing, "hswing", [(v, swing_label(v), None) for v in swings]))
        tiles2.pack_start(self.t_vswing, True, True, 0)
        tiles2.pack_start(self.t_hswing, True, True, 0)
        card.pack_start(tiles2, False, False, 0)

        self.pairbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=8)
        self.pairbox.get_style_context().add_class("bs-pairbox")
        help_lab = Gtk.Label(label=PAIR_HELP, xalign=0)
        help_lab.set_line_wrap(True)
        help_lab.set_max_width_chars(1)
        help_lab.set_size_request(PANEL_WIDTH - 60, -1)
        help_lab.get_style_context().add_class("bs-msg")
        self.pairbox.pack_start(help_lab, False, False, 0)
        pair_btn = Gtk.Button(label="Pair with AC", halign=Gtk.Align.START)
        pair_btn.get_style_context().add_class("bs-pair")
        pair_btn.connect("clicked", lambda *_: self._on_pair())
        self.pairbox.pack_start(pair_btn, False, False, 0)
        card.pack_start(self.pairbox, False, False, 0)

        foot = Gtk.Box(spacing=6, margin_top=4)
        self.spinner = Gtk.Spinner()
        self.foot_icon = Gtk.Image.new_from_icon_name("bluetooth-active-symbolic", Gtk.IconSize.MENU)
        self.foot = Gtk.Label(label="", xalign=0)
        self.foot.get_style_context().add_class("bs-foot")
        foot.pack_start(self.spinner, False, False, 0)
        foot.pack_start(self.foot_icon, False, False, 0)
        foot.pack_start(self.foot, True, True, 0)
        quit_btn = Gtk.Button(label="Quit")
        quit_btn.get_style_context().add_class("bs-quit")
        quit_btn.connect("clicked", lambda *_: self._on_quit())
        foot.pack_end(quit_btn, False, False, 0)
        card.pack_start(foot, False, False, 0)
        return card

    def _round(self, icon: str, cb) -> Gtk.Button:
        b = Gtk.Button(valign=Gtk.Align.CENTER)
        b.add(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU))
        b.get_style_context().add_class("bs-round")
        b.connect("clicked", cb)
        return b

    # --------------------------------------------------------------- events
    def _set(self, **kw) -> None:
        self._state = replace(self._state, **kw)
        self._hold_until = time.monotonic() + HOLD_AFTER_USER_CHANGE
        self._reflect(self._state, animate=True)
        self._on_change(self._state)

    def _bump(self, delta: int) -> None:
        self._set(temp=max(TEMP_MIN, min(TEMP_MAX, self._state.temp + delta)))

    def _pick(self, tile: Gtk.Widget, field: str, options: list) -> None:
        """Dropdown with every option for `field`; the current one is marked. Choosing sends it."""
        cur = getattr(self._state, field)
        pop = Gtk.Popover.new(tile)
        pop.set_position(Gtk.PositionType.TOP)
        pop.get_style_context().add_class("bs-pop")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=1)
        for value, label, icon in options:
            b = Gtk.Button()
            b.get_style_context().add_class("bs-item")
            row = Gtk.Box(spacing=8)
            if icon:
                row.pack_start(Gtk.Image.new_from_icon_name(icon, Gtk.IconSize.MENU), False, False, 0)
            row.pack_start(Gtk.Label(label=label, xalign=0), True, True, 0)
            if value == cur:
                b.get_style_context().add_class("current")
                row.pack_end(Gtk.Image.new_from_icon_name("object-select-symbolic", Gtk.IconSize.MENU), False, False, 0)
            b.add(row)

            def choose(_w, v=value):
                pop.popdown()
                if v != getattr(self._state, field):
                    self._set(**{field: v})
            b.connect("clicked", choose)
            box.pack_start(b, False, False, 0)
        box.show_all()
        pop.add(box)
        pop.popup()

    def _pick_timer(self) -> None:
        # the remote's TIMER button: an off-timer while running, an on-timer while off
        field = "offtimer" if self._state.power else "ontimer"
        verb = "Off in" if self._state.power else "On in"
        self._pick(self.t_timer, field, [(h, "Off" if h == 0 else f"{verb} {h} h", None) for h in TIMER_PRESETS])

    def _on_slider(self, scale) -> None:
        if self._syncing:
            return
        v = int(round(scale.get_value()))
        if v == self._state.temp:
            return
        self._state = replace(self._state, temp=v)
        self._hold_until = time.monotonic() + HOLD_AFTER_USER_CHANGE
        self.big.set_value(v)
        if self._slider_timer:
            GLib.source_remove(self._slider_timer)
        self._slider_timer = GLib.timeout_add(250, self._slider_commit)

    def _slider_commit(self) -> bool:
        self._slider_timer = 0
        self._on_change(self._state)
        return False

    def _on_key(self, _w, event) -> bool:
        if event.keyval == Gdk.KEY_Escape:
            self.hide_panel()
            return True
        return False

    def _on_button_press(self, _w, event) -> bool:
        x, y = self.get_position()
        w, h = self.get_size()
        inside = x <= event.x_root < x + w and y <= event.y_root < y + h
        if not inside:
            self.hide_panel()
            return True
        return False

    # ------------------------------------------------------------ show/hide
    def toggle(self) -> None:
        self.hide_panel() if self.get_visible() else self.show_panel()

    def show_panel(self) -> None:
        self.show_all()
        self.pairbox.set_visible(self._show_pair)
        self.spinner.set_visible(self.spinner.get_property("active"))
        mon = self.get_display().get_primary_monitor() or self.get_display().get_monitor(0)
        wa = mon.get_workarea()
        w, _h = self.get_size()
        self.move(wa.x + wa.width - w - 10, wa.y + 8)
        self.present()
        seat = self.get_display().get_default_seat()
        status = seat.grab(self.get_window(), Gdk.SeatCapabilities.ALL, True, None, None, None, None)
        self._grabbed = status == Gdk.GrabStatus.SUCCESS

    def hide_panel(self) -> None:
        if self._grabbed:
            self.get_display().get_default_seat().ungrab()
            self._grabbed = False
        self.hide()

    # --------------------------------------------------- updates from worker
    def update(self, link: LinkState) -> bool:
        connected = link.phase == "connected"
        self._show_pair = not link.paired
        self.pairbox.set_visible(self._show_pair)

        self.spinner.set_visible(link.busy)
        self.spinner.start() if link.busy else self.spinner.stop()
        self.foot_icon.set_visible(not link.busy)
        self.foot_icon.set_from_icon_name(
            "bluetooth-active-symbolic" if connected else "bluetooth-disconnected-symbolic", Gtk.IconSize.MENU)
        quiet = set(PHASE_TEXT.values()) | {"Looking for the AC…", "Connected – not paired yet", "Syncing…"}
        if link.busy:
            text = "Syncing…"
        elif link.message and link.message not in quiet:
            text = link.message
        else:
            text = PHASE_TEXT.get(link.phase, link.phase) + ("" if link.paired else " · not paired")
        self.foot.set_text(text)
        ctx = self.foot.get_style_context()
        for c in ("bs-ok", "bs-warn", "bs-err"):
            ctx.remove_class(c)
        ctx.add_class("bs-ok" if connected and link.paired and not link.busy
                      else ("bs-err" if link.phase == "error" else "bs-warn"))

        if link.ac.ambient is not None:
            self.room.set_text(f"{link.ac.ambient:g} °C")
        first = not self._reflected
        if link.ac_known and (first or (time.monotonic() >= self._hold_until and not link.busy)):
            self._reflect(link.ac, animate=not first)
            self._reflected = True
        return False

    def _reflect(self, ac: ACState, animate: bool) -> None:
        """Push an ACState into every widget without triggering change handlers."""
        self._syncing = True
        try:
            self._state = ac
            self.illus.set_state(ac)
            self.big.set_value(ac.temp, animate)
            if int(round(self.scale.get_value())) != ac.temp:
                self.scale.set_value(ac.temp)
            for btn, on in ((self.power, ac.power), (self.light, ac.display)):
                c = btn.get_style_context()
                c.add_class("on") if on else c.remove_class("on")
            self.c_turbo.set_on(ac.turbo)
            self.c_esave.set_on(ac.esave)
            self.c_sleep.set_on(ac.sleep)
            self.t_mode.set(ac.mode.capitalize(), MODE_ICON[ac.mode], active=ac.power)
            self.t_fan.set("Turbo" if ac.turbo else ac.fan.capitalize(), active=ac.power)
            self.t_conv.set(conv_label(ac.conv), active=ac.conv != 0)
            cool = ac.mode == "cool" and ac.power
            self.t_conv.set_sensitive(cool)            # 5-in-1 and Turbo exist only in Cool mode
            self.c_turbo.set_sensitive(cool)
            timer = ac.offtimer if ac.power else ac.ontimer
            self.t_timer.set(("Off in " if ac.power else "On in ") + timer_label(timer) if timer else "Off", active=timer > 0)
            self.t_vswing.set(swing_label(ac.vswing), active=ac.vswing == SWING_AUTO)
            self.t_hswing.set(swing_label(ac.hswing), active=ac.hswing == SWING_AUTO)
        finally:
            self._syncing = False

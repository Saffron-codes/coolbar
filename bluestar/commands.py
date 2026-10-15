"""AC state model and the Blue Star JSON encoding (reverse-engineered for interoperability and
verified key by key against the BI-IC318VNUS on 2026-10-15).

The feature set mirrors the IR remote: MODE, ON/OFF, FAN, 5-in-1 CONV, 5-in-1 TURBO, +/-, TIMER,
two SWING buttons, ENERGY SAVE, SLEEP, LIGHT. (CLOCK lives in the remote only.)

Desired-state encoding (every object also gets "src":"anble" and "ts": epoch ms, see ble.py):
    pow       0/1
    stemp     "24.0"                       (string, one decimal)
    mode      {"value": id, "stemp": "24.0", "fspd": n}   plain ints are ignored by the AC
              ids: 0 fan, 1 heat, 2 cool, 3 dry, 4 auto; fan mode forces stemp 24.0
    fspd      2 low, 3 medium, 4 high, 5 high-high, 6 turbo, 7 auto
    eco       {"value": level}             5-in-1 convertible: 0 default, 1,2,3,4,6 (5 is refused)
    turbo     0/1  (Cool mode only; turning it on sets fspd 4 + stemp 16 and clears eco)
    esave     0/1  ENERGY SAVE
    sleep     0/1
    display   0/1  LIGHT
    vswing    0 off, 1..5 fixed positions, 6 swing         (verified 0/3/6 round-trip)
    hswing    same scale
    offtimer  hours until power off (0 = none) - unit inferred: value 1 did not fire within 100 s,
              and the remote's timer counts hours. ontimer likewise while the AC is off.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

MODES = ("cool", "dry", "fan", "auto")
FANS = ("auto", "low", "medium", "high")
TEMP_MIN, TEMP_MAX = 16, 30

MODE_IDS = {"heat": 1, "cool": 2, "dry": 3, "auto": 4, "fan": 0}
FAN_IDS = {"low": 2, "medium": 3, "high": 4, "highhigh": 5, "turbo": 6, "auto": 7}
ID_MODES = {v: k for k, v in MODE_IDS.items()}
ID_FANS = {v: k for k, v in FAN_IDS.items()}
CONV_LEVELS = (0, 1, 2, 3, 4, 6)          # 5-in-1 convertible ids the unit accepts, 0 = default
SWING_AUTO = 6                            # 1..5 fixed louver positions, 6 = continuous swing
TIMER_PRESETS = (0, 1, 2, 4, 8)           # hours


@dataclass(frozen=True)
class ACState:
    power: bool = False
    temp: int = 24
    mode: str = "cool"
    fan: str = "auto"
    ambient: float | None = None      # room temperature (ctemp)
    conv: int = 0                     # eco / 5-in-1 level
    turbo: bool = False
    esave: bool = False
    sleep: bool = False
    display: bool = True
    vswing: int = SWING_AUTO
    hswing: int = SWING_AUTO
    offtimer: int = 0                 # hours
    ontimer: int = 0

    def with_temp(self, t: int) -> "ACState":
        return replace(self, temp=max(TEMP_MIN, min(TEMP_MAX, t)))

    def controls(self) -> tuple:
        return (self.power, self.temp, self.mode, self.fan, self.conv, self.turbo, self.esave,
                self.sleep, self.display, self.vswing, self.hswing, self.offtimer, self.ontimer)


_BOOL_KEYS = (("turbo", "turbo"), ("esave", "esave"), ("sleep", "sleep"), ("display", "display"))
_INT_KEYS = (("vswing", "vswing"), ("hswing", "hswing"), ("offtimer", "offtimer"), ("ontimer", "ontimer"))


def encode(state: ACState, prev: ACState | None = None) -> dict:
    """Desired-state object for a type-1 message: only fields that differ from `prev` (one tap, one
    field, like the app). With no `prev` the basic four are sent."""
    def changed(attr: str) -> bool:
        return prev is None or getattr(state, attr) != getattr(prev, attr)

    d: dict = {}
    if changed("power"):
        d["pow"] = 1 if state.power else 0
    if changed("mode"):
        d["mode"] = {"value": MODE_IDS[state.mode], "stemp": f"{state.temp:.1f}", "fspd": FAN_IDS[state.fan]}
    else:
        if changed("temp"):
            d["stemp"] = f"{state.temp:.1f}"
        if changed("fan"):
            d["fspd"] = FAN_IDS[state.fan]
    if prev is not None and changed("conv"):
        d["eco"] = {"value": state.conv}
    for attr, key in _BOOL_KEYS:
        if prev is not None and changed(attr):
            d[key] = 1 if getattr(state, attr) else 0
    for attr, key in _INT_KEYS:
        if prev is not None and changed(attr):
            d[key] = int(getattr(state, attr))
    return d


def _find_state_dict(obj) -> dict | None:
    if isinstance(obj, dict):
        if "pow" in obj or "stemp" in obj:
            return obj
        for v in obj.values():
            found = _find_state_dict(v)
            if found:
                return found
    return None


def plausible(s: dict) -> bool:
    """Reject a status whose values are physically impossible (a corrupted BLE fragment shows up this way)."""
    try:
        if "pow" in s and int(float(s["pow"])) not in (0, 1):
            return False
        if "stemp" in s and not (10.0 <= float(s["stemp"]) <= 35.0):
            return False
        if "ctemp" in s and not (-10.0 <= float(s["ctemp"]) <= 60.0):
            return False
    except (TypeError, ValueError):
        return False
    return True


def _int(v, default):
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return default


def decode(status: dict, base: ACState | None = None) -> ACState | None:
    """Merge a decrypted status push into an ACState."""
    s = _find_state_dict(status)
    if s is None or not plausible(s):
        return None
    cur = base or ACState()
    kw: dict = {}
    if "pow" in s:
        kw["power"] = bool(_int(s["pow"], 0))
    if "stemp" in s:
        try:
            kw["temp"] = int(round(float(s["stemp"])))
        except (TypeError, ValueError):
            pass
    if "mode" in s:
        kw["mode"] = ID_MODES.get(_int(s["mode"], -1), cur.mode)
    if "fspd" in s:
        name = ID_FANS.get(_int(s["fspd"], -1), cur.fan)
        kw["fan"] = {"highhigh": "high", "turbo": "high"}.get(name, name)
    if "ctemp" in s:
        try:
            kw["ambient"] = float(s["ctemp"])
        except (TypeError, ValueError):
            pass
    if "eco" in s:
        kw["conv"] = _int(s["eco"], cur.conv)
    for attr, key in _BOOL_KEYS:
        if key in s:
            kw[attr] = bool(_int(s[key], 0))
    for attr, key in _INT_KEYS:
        if key in s:
            kw[attr] = _int(s[key], getattr(cur, attr))
    return replace(cur, **kw)


def matches(desired: dict, status: dict) -> bool:
    """True when every field we asked for is reflected in the status the AC pushed back."""
    s = _find_state_dict(status) or {}
    if not plausible(s):
        return False
    for k, v in desired.items():
        if k in ("src", "ts"):
            continue
        if isinstance(v, dict):                     # object form: only "value" is binding
            if not matches({k: v["value"]}, status):
                return False
            continue
        if k not in s:
            return False
        try:
            if abs(float(s[k]) - float(v)) > 0.01:
                return False
        except (TypeError, ValueError):
            if str(s[k]) != str(v):
                return False
    return True

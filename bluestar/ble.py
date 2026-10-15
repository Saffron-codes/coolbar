"""BLE session to the AC (asyncio) plus the background worker thread that the GTK app drives.

Protocol (reverse-engineered for interoperability):
    1. connect, BluFi DH negotiation -> AES session
    2. custom-data JSON frames, all carrying "type":
         0/6  pairing: {"type":0,"uat":U} then {"type":6,"uat":U}; AC answers type 6 with pid, firmware...
              The AC only answers while it is in pairing mode (remote button pressed 5x within 7 s).
         1    control: {"type":1,"uat":U,"state":{"desired":{...,"src":"anble"}}}
         5    status push: {"type":5,"state":"(<pid>|<base64 iv+AES-CBC(json)>)"}, key = U[:16]
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Callable

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from dbus_next import BusType
from dbus_next.aio import MessageBus

from . import blufi, config
from .commands import ACState, decode, encode, matches

log = logging.getLogger("bluestar.ble")
NAME_PREFIX = "BLUAC_"


# ----------------------------------------------------------------------------- helpers
async def _bluez(fn):
    bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
    try:
        intro = await bus.introspect("org.bluez", "/")
        om = bus.get_proxy_object("org.bluez", "/", intro).get_interface("org.freedesktop.DBus.ObjectManager")
        return await fn(bus, await om.call_get_managed_objects())
    finally:
        bus.disconnect()


async def bluez_mtu(address: str) -> int:
    async def go(_bus, objs):
        dev = "dev_" + address.replace(":", "_")
        for path, ifaces in objs.items():
            ch = ifaces.get("org.bluez.GattCharacteristic1")
            if ch and dev in path and ch["UUID"].value == blufi.WRITE_UUID and "MTU" in ch:
                return ch["MTU"].value
        return 23
    try:
        return await _bluez(go)
    except Exception:  # noqa: BLE001
        return 23


async def drop_leftover_links() -> str | None:
    """Disconnect any BLUAC_* device BlueZ still holds a link to. The ESP32 stops advertising while
    linked, and a half-dead leftover link hangs connects, so we always start from a clean scan."""
    async def go(bus, objs):
        for path, ifaces in objs.items():
            dev = ifaces.get("org.bluez.Device1")
            if dev and "Name" in dev and dev["Name"].value.startswith(NAME_PREFIX) and dev["Connected"].value:
                dintro = await bus.introspect("org.bluez", path)
                d1 = bus.get_proxy_object("org.bluez", path, dintro).get_interface("org.bluez.Device1")
                await d1.call_disconnect()
                return dev["Address"].value
        return None
    try:
        return await _bluez(go)
    except Exception as e:  # noqa: BLE001
        log.debug("bluez lookup failed: %s", e)
        return None


def decrypt_status(b64: str, uat: str) -> dict:
    raw = base64.b64decode(b64)
    dec = Cipher(algorithms.AES(uat[:16].encode()), modes.CBC(raw[:16])).decryptor()
    plain = dec.update(raw[16:]) + dec.finalize()
    txt = plain.decode("ascii", "replace").rstrip("\x00 \r\n\t")
    end = txt.rfind("}")                      # NoPadding on the AC side: filler may follow the JSON
    return json.loads(txt[:end + 1] if end >= 0 else txt)


async def find_ac(timeout: float = 12.0):
    await drop_leftover_links()
    return await BleakScanner.find_device_by_filter(
        lambda d, ad: (d.name or ad.local_name or "").startswith(NAME_PREFIX), timeout=timeout)


# ----------------------------------------------------------------------------- session
class PairingTimeout(RuntimeError):
    pass


class ACSession:
    """One connected, negotiated BluFi link to the AC."""

    def __init__(self, client: BleakClient, cfg: config.DeviceConfig, mtu: int, on_status=None):
        self.client = client
        self.cfg = cfg
        self.bf = blufi.BluFi(client, mtu=mtu, log=log.debug)
        self.on_status = on_status                 # callback(ACState, raw_dict)
        self.ac: ACState | None = None
        self.last_status: dict = {}
        self.version = ""
        self._custom: asyncio.Queue[dict] = asyncio.Queue()
        self._status_waiters: list[asyncio.Future] = []
        self._pump_task: asyncio.Task | None = None

    async def start(self) -> None:
        await self.bf.start()
        await self.bf.negotiate()
        v = await self.bf.query(blufi.CTRL_GET_VERSION)      # before the pump owns the receive queue
        self.version = f"{v.data[0]}.{v.data[1]}" if len(v.data) >= 2 else v.data.hex()
        self._pump_task = asyncio.ensure_future(self._pump())
        if self.cfg.paired:
            await self.hello()

    async def hello(self, timeout: float = 5.0) -> dict | None:
        """Type 7: present the pairing token on this connection. The app does this right after every
        control connection; without it the AC ignores type-1 commands. The AC answers with a status push."""
        await self._send({"type": 7, "uat": self.cfg.uat})
        try:
            return await self.wait_status(timeout)
        except asyncio.TimeoutError:
            log.warning("no status after hello (type 7)")
            return None

    async def stop(self) -> None:
        if self._pump_task:
            self._pump_task.cancel()
        await self.bf.stop()

    async def _pump(self) -> None:
        while True:
            try:
                f = await self.bf.recv(timeout=3600)
            except asyncio.TimeoutError:
                continue
            if not f.is_custom:
                log.debug("rx %s", f)
                continue
            try:
                obj = json.loads(f.data.decode("utf-8"))
            except ValueError:
                log.warning("rx custom (not json): %s", f.data[:80])
                continue
            log.info("rx custom: %s", json.dumps(obj)[:300])
            if obj.get("type") == 5:
                self._on_type5(obj)
            else:
                self._custom.put_nowait(obj)

    def _on_type5(self, obj: dict) -> None:
        if not self.cfg.paired:
            log.info("status push received but not paired, cannot decrypt")
            return
        try:
            pid, _, enc = str(obj.get("state", "")).strip("()").partition("|")
            status = decrypt_status(enc, self.cfg.uat)
        except Exception as e:  # noqa: BLE001
            log.warning("status decrypt failed: %s", e)
            return
        log.info("status from %s: %s", pid, json.dumps(status)[:300])
        self.last_status = status
        self.ac = decode(status, self.ac) or self.ac
        for fut in self._status_waiters:
            if not fut.done():
                fut.set_result(status)
        self._status_waiters.clear()
        if self.on_status and self.ac is not None:
            self.on_status(self.ac, status)

    async def wait_status(self, timeout: float) -> dict:
        fut = asyncio.get_running_loop().create_future()
        self._status_waiters.append(fut)
        return await asyncio.wait_for(fut, timeout)

    async def _send(self, obj: dict) -> None:
        raw = json.dumps(obj, separators=(",", ":")).encode()
        log.info("tx custom: %s", raw.decode())
        await self.bf.send_custom(raw)

    async def _recv_type(self, t: int, timeout: float) -> dict:
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            obj = await asyncio.wait_for(self._custom.get(), max(0.05, deadline - loop.time()))
            if obj.get("type") == t:
                return obj

    # -- pairing ----------------------------------------------------------------
    async def pair(self, timeout: float = 20.0) -> config.DeviceConfig:
        """Bind with a fresh token. The AC must be in pairing mode (blinking)."""
        uat = str(uuid.uuid4())
        await self._send({"type": 0, "uat": uat})
        await asyncio.sleep(0.3)
        await self._send({"type": 6, "uat": uat})
        try:
            reply = await self._recv_type(6, timeout)
        except asyncio.TimeoutError:
            raise PairingTimeout("AC did not answer the pairing request. Put it in pairing mode first "
                                 "(remote button 5x within 7 s, AC display blinks) and retry.") from None
        self.cfg = config.DeviceConfig(uat=uat, pid=str(reply.get("pid", "")), address=self.client.address,
                                       info={k: v for k, v in reply.items() if k not in ("type", "pid")})
        config.save(self.cfg)
        log.info("paired: pid=%s info=%s", self.cfg.pid, self.cfg.info)
        return self.cfg

    # -- control ----------------------------------------------------------------
    async def send_desired(self, desired: dict, confirm_timeout: float = 6.0) -> tuple[bool, dict | None]:
        """Send a desired-state change; returns (confirmed, status) where confirmed means the AC pushed
        a status back that reflects every requested field within the timeout."""
        if not self.cfg.paired:
            raise RuntimeError("not paired")
        payload = dict(desired, src="anble", ts=int(time.time() * 1000))   # AC drops unstamped/old commands
        await self._send({"type": 1, "uat": self.cfg.uat, "state": {"desired": payload}})
        loop = asyncio.get_running_loop()
        deadline = loop.time() + confirm_timeout
        status = None
        while loop.time() < deadline:
            try:
                status = await self.wait_status(deadline - loop.time())
            except asyncio.TimeoutError:
                break
            if matches(desired, status):
                return True, status
        return False, status

    async def apply(self, new: ACState, prev: ACState | None) -> tuple[bool, dict | None, dict]:
        desired = encode(new, prev)
        if not desired:
            return True, self.last_status, desired
        ok, status = await self.send_desired(desired)
        return ok, status, desired

    async def request_status(self) -> dict | None:
        """Ask the AC to push its state (re-sending the hello does that)."""
        if not self.cfg.paired:
            return None
        if self.last_status:
            return self.last_status
        return await self.hello()


# ----------------------------------------------------------------------------- worker thread
@dataclass
class LinkState:
    phase: str = "scanning"          # scanning | connecting | connected | error
    address: str = ""
    paired: bool = False
    pid: str = ""
    blufi_version: str = ""
    message: str = ""
    ac: ACState = field(default_factory=ACState)
    ac_known: bool = False           # True once the AC has reported its real state
    busy: bool = False               # a command is in flight, waiting for the AC to confirm


class Worker(threading.Thread):
    """Runs one asyncio loop off the GTK thread. UI talks to it via `post`, it talks back via `on_state`."""

    def __init__(self, on_state: Callable[[LinkState], None]):
        super().__init__(name="ble-worker", daemon=True)
        self.loop = asyncio.new_event_loop()
        self.on_state = on_state
        self.cfg = config.load()
        self.state = LinkState(paired=self.cfg.paired, pid=self.cfg.pid)
        self._stop = threading.Event()
        self._dropped = asyncio.Event()
        self._task: asyncio.Future | None = None
        self.session: ACSession | None = None
        self.extra_tasks: list[Callable[[], "asyncio.coroutines"]] = []

    # ---- thread plumbing -------------------------------------------------
    def run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_until_complete(self._main())
        finally:
            self.loop.close()

    def stop(self) -> None:
        self._stop.set()

        def _cancel() -> None:
            self._dropped.set()
            if self._task and not self._task.done():
                self._task.cancel()
        self.loop.call_soon_threadsafe(_cancel)

    def post(self, coro_fn: Callable[[], "asyncio.coroutines"]) -> None:
        asyncio.run_coroutine_threadsafe(coro_fn(), self.loop)

    def _emit(self, **changes) -> None:
        for k, v in changes.items():
            setattr(self.state, k, v)
        if "phase" in changes or "message" in changes:
            log.info("%s: %s", self.state.phase, self.state.message)
        self.on_state(self.state)

    # ---- main loop -------------------------------------------------------
    async def _main(self) -> None:
        for factory in self.extra_tasks:
            asyncio.ensure_future(factory())
        while not self._stop.is_set():
            try:
                self._task = asyncio.ensure_future(self._session())
                await self._task
            except asyncio.CancelledError:
                break
            except Exception as e:  # noqa: BLE001 - keep the daemon alive, surface the error
                log.warning("session ended: %r", e)
                self._emit(phase="error", message=str(e) or type(e).__name__, address="")
            if not self._stop.is_set():
                await asyncio.sleep(3)

    async def _session(self) -> None:
        self._emit(phase="scanning", message="Looking for the AC…", address="")
        dev = await find_ac()
        if dev is None:
            self._emit(phase="error", message="AC not found over Bluetooth")
            return
        self._emit(phase="connecting", address=dev.address, message="Connecting…")
        self._dropped = asyncio.Event()
        client = BleakClient(dev, timeout=20,
                             disconnected_callback=lambda _c: self.loop.call_soon_threadsafe(self._dropped.set))
        async with client:
            mtu = await bluez_mtu(dev.address)
            session = ACSession(client, self.cfg, mtu, on_status=self._on_status)
            self.session = session
            await session.start()
            self._emit(phase="connected", blufi_version=session.version, paired=self.cfg.paired, pid=self.cfg.pid,
                       message="Connected" if self.cfg.paired else "Connected – not paired yet")
            try:
                await self._dropped.wait()
            finally:
                await session.stop()
                self.session = None
        self._emit(phase="scanning", message="Disconnected")

    def _on_status(self, ac: ACState, raw: dict) -> None:
        self.state.ac = ac
        self.state.ac_known = True
        if not self.state.busy:
            self.state.message = "Connected"
        self.on_state(self.state)

    # ---- commands (called via post) --------------------------------------
    async def pair(self) -> None:
        s = self.session
        if s is None or self.state.phase != "connected":
            self._emit(message="Not connected")
            return
        self._emit(message="Pairing… (AC must be blinking)")
        try:
            self.cfg = await s.pair()
        except PairingTimeout as e:
            self._emit(message=str(e))
            return
        except Exception as e:  # noqa: BLE001
            self._emit(message=f"Pairing failed: {e}")
            return
        self._emit(paired=True, pid=self.cfg.pid, message=f"Paired with {self.cfg.pid or 'AC'}")
        s.cfg = self.cfg
        await s.hello()

    async def apply(self, new: ACState) -> None:
        s = self.session
        prev = self.state.ac if self.state.ac_known else None
        self.state.ac = new
        if s is None or self.state.phase != "connected":
            self._emit(message="Not connected")
            return
        if not self.cfg.paired:
            self._emit(message="Not paired – press Pair while the AC is blinking")
            return
        self._emit(busy=True, message="Syncing…")
        try:
            ok, status, desired = await s.apply(new, prev)
        except Exception as e:  # noqa: BLE001
            self._emit(busy=False, message=f"Send failed: {e}")
            return
        if not desired:
            self._emit(busy=False, message="Connected")
            return
        what = ", ".join(f"{k}={v if not isinstance(v, dict) else v['value']}" for k, v in desired.items())
        if ok:
            self._emit(busy=False, message=f"AC confirmed {what}")
        elif status is None:
            self._emit(busy=False, message=f"Sent {what} – no reply from AC")
        else:
            self._emit(busy=False, message=f"Sent {what} – AC reported something else")

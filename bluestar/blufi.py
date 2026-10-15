"""Espressif BluFi transport with the security negotiation the Blue Star app performs.

Frame layout (ESP-IDF btc_blufi_prf.c / EspBlufi BlufiClientImpl.java):
    [type][frame_ctrl][seq][len][data...][crc_lo][crc_hi]
type       = (subtype << 2) | pkt_type      pkt_type 0 = CTRL, 1 = DATA
frame_ctrl = bit0 ENC, bit1 CHECKSUM, bit2 DIR (1 = device->app), bit3 REQ_ACK, bit4 FRAG
seq        = per-connection counter starting at 0, incremented for every frame incl. fragments
crc        = crc16 over seq|len|PLAINTEXT data, present when CHECKSUM bit set
enc        = AES-128-CFB128 over the data bytes only, IV = [seq, 0 * 15], key = MD5(DH shared secret)
frag       = data = [remaining_total lo, hi] + chunk

Security negotiation (required by the AC before any custom data):
    app -> dev  DATA/NEG  [0x00, len_hi, len_lo]                 (len of the next payload)
    app -> dev  DATA/NEG  [0x01, p_len(2), p, g_len(2), g, pub_len(2), pub]
    dev -> app  DATA/NEG  device public key (128 bytes)
    app -> dev  CTRL/SET_SEC_MODE [0x03]                          (data frames: enc + checksum)
"""
from __future__ import annotations

import asyncio
import hashlib
import secrets
import struct
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

SERVICE_UUID = "0000ffff-0000-1000-8000-00805f9b34fb"
WRITE_UUID = "0000ff01-0000-1000-8000-00805f9b34fb"   # app -> device
NOTIFY_UUID = "0000ff02-0000-1000-8000-00805f9b34fb"  # device -> app

PKT_CTRL, PKT_DATA = 0, 1

CTRL_ACK, CTRL_SET_SEC_MODE, CTRL_SET_OPMODE, CTRL_CONNECT_AP, CTRL_DISCONNECT_AP = 0, 1, 2, 3, 4
CTRL_GET_WIFI_STATUS, CTRL_DEAUTH_STA, CTRL_GET_VERSION, CTRL_DISCONNECT_BLE, CTRL_GET_WIFI_LIST = 5, 6, 7, 8, 9

DATA_NEG, DATA_STA_BSSID, DATA_STA_SSID, DATA_STA_PASSWD = 0, 1, 2, 3
DATA_WIFI_STATUS, DATA_VERSION, DATA_WIFI_LIST, DATA_ERROR, DATA_CUSTOM = 15, 16, 17, 18, 19

FC_ENC, FC_CHECK, FC_DIR, FC_ACK, FC_FRAG = 0x01, 0x02, 0x04, 0x08, 0x10

ERROR_NAMES = {
    0: "SEQUENCE_ERROR", 1: "CHECKSUM_ERROR", 2: "DECRYPT_ERROR", 3: "ENCRYPT_ERROR",
    4: "INIT_SECURITY_ERROR", 5: "DH_MALLOC_ERROR", 6: "DH_PARAM_ERROR", 7: "READ_PARAM_ERROR",
    8: "MAKE_PUBLIC_ERROR", 9: "DATA_FORMAT_ERROR", 10: "CALC_MD5_ERROR", 11: "WIFI_SCAN_ERROR",
}

# 1024-bit DH group hard-coded in EspBlufi (BlufiClientImpl.DH_P / DH_G)
DH_P = int(
    "cf5cf5c38419a724957ff5dd323b9c45c3cdd261eb740f69aa94b8bb1a5c96409153bd76b24222d03274e4725a5406092e9e82e9"
    "135c643cae98132b0d95f7d65347c68afc1e677da90e51bbab5f5cf429c291b4ba39c6b2dc5e8c7231e46aa7728e87664532cdf5"
    "47be20c9a3fa8342be6e34371a27c06f7dc0edddd2f86373", 16)
DH_G = 2
SEC_MODE_DATA_ENC_CHECK = 0x03


def crc16_be(data: bytes, crc: int = 0) -> int:
    """esp_crc16_be / BlufiCRC.calcCRC: CRC-16 poly 0x1021 MSB-first with ~crc in/out."""
    crc = (~crc) & 0xFFFF
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return (~crc) & 0xFFFF


def _aes_cfb(key: bytes, seq: int, data: bytes, encrypt: bool) -> bytes:
    iv = bytes([seq]) + bytes(15)
    c = Cipher(algorithms.AES(key), modes.CFB(iv))
    op = c.encryptor() if encrypt else c.decryptor()
    return op.update(data) + op.finalize()


@dataclass
class Frame:
    pkt_type: int
    subtype: int
    fc: int
    seq: int
    data: bytes

    @property
    def is_ctrl(self) -> bool:
        return self.pkt_type == PKT_CTRL

    @property
    def is_custom(self) -> bool:
        return self.pkt_type == PKT_DATA and self.subtype == DATA_CUSTOM

    def __str__(self) -> str:
        kind = "CTRL" if self.is_ctrl else "DATA"
        return f"<{kind} sub={self.subtype} fc=0x{self.fc:02x} seq={self.seq} data={self.data.hex()}>"


class BluFi:
    """BluFi session over a bleak client. Call `negotiate()` once after `start()` to turn on encryption."""

    def __init__(self, client, mtu: int = 23, log=print):
        self.client = client
        self.mtu = mtu
        self.log = log
        self.seq = -1
        self.key: bytes | None = None
        self._rx: asyncio.Queue[Frame] = asyncio.Queue()
        self._frag: dict[int, bytes] = {}
        self._frag_total: dict[int, int] = {}

    # ---------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self.seq = -1
        self.key = None
        await self.client.start_notify(NOTIFY_UUID, self._on_notify)

    async def stop(self) -> None:
        try:
            await self.client.stop_notify(NOTIFY_UUID)
        except Exception:  # noqa: BLE001 - best effort on teardown
            pass

    # ---------------------------------------------------------------- receive
    def _on_notify(self, _handle, raw: bytearray) -> None:
        raw = bytes(raw)
        if len(raw) < 4:
            self.log(f"rx short frame {raw.hex()}")
            return
        t, fc, seq, ln = raw[0], raw[1], raw[2], raw[3]
        data = raw[4:4 + ln]
        if fc & FC_ENC:
            if self.key is None:
                self.log(f"rx encrypted frame before key negotiation: {raw.hex()}")
                return
            data = _aes_cfb(self.key, seq, data, encrypt=False)
        if fc & FC_CHECK:
            want = struct.unpack("<H", raw[4 + ln:6 + ln])[0]
            got = crc16_be(bytes([seq, ln]) + data)
            if want != got:
                self.log(f"rx bad crc {want:04x} != {got:04x} in {raw.hex()}")
                return
        pkt_type, subtype = t & 0x03, t >> 2
        if fc & FC_FRAG:                                   # [total lo, hi] + chunk
            if t not in self._frag:
                self._frag_total[t] = data[0] | (data[1] << 8)
            self._frag[t] = self._frag.get(t, b"") + data[2:]
            return
        if t in self._frag:
            data = self._frag.pop(t) + data
            total = self._frag_total.pop(t, None)
            if total is not None and total != len(data):   # lost/duplicated fragment: drop, never decode garbage
                self.log(f"rx dropped reassembled frame: {len(data)} bytes, expected {total}")
                return
        self._rx.put_nowait(Frame(pkt_type, subtype, fc, seq, bytes(data)))

    async def recv(self, timeout: float = 3.0) -> Frame:
        return await asyncio.wait_for(self._rx.get(), timeout)

    async def recv_custom(self, timeout: float = 3.0) -> bytes:
        """Next custom-data payload, skipping anything else."""
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            f = await self.recv(max(0.05, deadline - loop.time()))
            if f.is_custom:
                return f.data
            if not f.is_ctrl and f.subtype == DATA_ERROR:
                code = f.data[0] if f.data else -1
                raise RuntimeError(f"device error {ERROR_NAMES.get(code, code)}")
            self.log(f"rx (ignored) {f}")

    # ---------------------------------------------------------------- send
    def _next_seq(self) -> int:
        self.seq = (self.seq + 1) & 0xFF
        return self.seq

    def _frame(self, pkt_type: int, subtype: int, data: bytes, enc: bool, check: bool, frag: bool) -> bytes:
        seq = self._next_seq()
        fc = (FC_ENC if enc else 0) | (FC_CHECK if check else 0) | (FC_FRAG if frag else 0)
        out = bytearray([(subtype << 2) | pkt_type, fc, seq, len(data)])
        crc = crc16_be(bytes([seq, len(data)]) + data) if check else None
        if enc and data:
            data = _aes_cfb(self.key, seq, data, encrypt=True)
        out += data
        if crc is not None:
            out += struct.pack("<H", crc)
        return bytes(out)

    async def send(self, pkt_type: int, subtype: int, data: bytes = b"", *, enc: bool | None = None,
                   check: bool = True) -> None:
        """Send one logical message, fragmenting exactly like EspBlufi does."""
        if enc is None:
            enc = self.key is not None and pkt_type == PKT_DATA
        limit = max(self.mtu - 4, 20) - (8 if check else 6)
        if len(data) <= limit:
            await self._write(self._frame(pkt_type, subtype, data, enc, check, frag=False))
            return
        pos = 0
        while pos < len(data):
            chunk = data[pos:pos + limit]
            pos += len(chunk)
            if 0 < len(data) - pos <= 2:               # Android folds a tiny tail into this fragment
                chunk += data[pos:]
                pos = len(data)
            last = pos >= len(data)
            payload = chunk if last else struct.pack("<H", len(data) - (pos - len(chunk))) + chunk
            await self._write(self._frame(pkt_type, subtype, payload, enc, check, frag=not last))

    async def _write(self, raw: bytes) -> None:
        await self.client.write_gatt_char(WRITE_UUID, raw, response=True)

    async def send_custom(self, payload: bytes) -> None:
        await self.send(PKT_DATA, DATA_CUSTOM, payload)

    async def query(self, ctrl_subtype: int, timeout: float = 3.0) -> Frame:
        await self.send(PKT_CTRL, ctrl_subtype, enc=False)
        f = await self.recv(timeout)
        if not f.is_ctrl and f.subtype == DATA_ERROR:
            code = f.data[0] if f.data else -1
            raise RuntimeError(f"device error {ERROR_NAMES.get(code, code)}")
        return f

    # ---------------------------------------------------------------- security
    async def negotiate(self, timeout: float = 8.0) -> None:
        priv = secrets.randbits(1023) | 1
        pub = pow(DH_G, priv, DH_P)
        p_b = DH_P.to_bytes(128, "big")
        g_b = bytes([DH_G])
        pub_b = pub.to_bytes(128, "big")
        body = (b"\x01" + struct.pack(">H", len(p_b)) + p_b + struct.pack(">H", len(g_b)) + g_b
                + struct.pack(">H", len(pub_b)) + pub_b)
        total = len(p_b) + len(g_b) + len(pub_b) + 6
        await self.send(PKT_DATA, DATA_NEG, b"\x00" + struct.pack(">H", total), enc=False, check=False)
        await asyncio.sleep(0.01)
        await self.send(PKT_DATA, DATA_NEG, body, enc=False, check=False)
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while True:
            f = await self.recv(max(0.05, deadline - loop.time()))
            if not f.is_ctrl and f.subtype == DATA_NEG:
                break
            if not f.is_ctrl and f.subtype == DATA_ERROR:
                raise RuntimeError(f"negotiation refused: {ERROR_NAMES.get(f.data[0] if f.data else -1)}")
            self.log(f"rx (ignored during negotiation) {f}")
        dev_pub = int.from_bytes(f.data, "big")
        if dev_pub == 0:
            raise RuntimeError("device sent empty public key")
        secret = pow(dev_pub, priv, DH_P).to_bytes(128, "big")   # RFC 2631 fixed-length, as BouncyCastle/mbedtls
        self.key = hashlib.md5(secret).digest()
        await self.send(PKT_CTRL, CTRL_SET_SEC_MODE, bytes([SEC_MODE_DATA_ENC_CHECK]), enc=False, check=True)


def describe_wifi_status(data: bytes) -> dict:
    """DATA_WIFI_STATUS: [opmode][sta_state][softap_conn_num] then TLVs (ssid/bssid/...)."""
    if len(data) < 3:
        return {"raw": data.hex()}
    opmode = {0: "NULL", 1: "STA", 2: "AP", 3: "APSTA"}.get(data[0], data[0])
    sta = {0: "CONNECTED", 1: "DISCONNECTED", 2: "CONNECTING", 3: "CONN_FAIL"}.get(data[1], data[1])
    out = {"opmode": opmode, "sta": sta, "softap_clients": data[2]}
    i = 3
    while i + 1 < len(data):
        t, ln = data[i], data[i + 1]
        v = data[i + 2:i + 2 + ln]
        if t == DATA_STA_SSID:
            out["ssid"] = v.decode(errors="replace")
        elif t == DATA_STA_BSSID:
            out["bssid"] = v.hex(":")
        else:
            out[f"tlv{t}"] = v.hex()
        i += 2 + ln
    return out

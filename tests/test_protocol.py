"""Pure-function tests for the Python protocol port. Values were captured from the real unit and are
shared with app/test/protocol_test.dart so both ports stay in sync."""
import json
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from coolbar import blufi, commands  # noqa: E402

FIXTURES = json.loads((pathlib.Path(__file__).parent / "fixtures.json").read_text())


def test_crc16_vectors():
    for hex_in, want in FIXTURES["crc16"]:
        assert blufi.crc16_be(bytes.fromhex(hex_in)) == want


def test_aes_cfb_roundtrip_and_vector():
    key = bytes.fromhex(FIXTURES["aes"]["key"])
    seq = FIXTURES["aes"]["seq"]
    plain = bytes.fromhex(FIXTURES["aes"]["plain"])
    enc = blufi._aes_cfb(key, seq, plain, encrypt=True)
    assert enc.hex() == FIXTURES["aes"]["cipher"]
    assert blufi._aes_cfb(key, seq, enc, encrypt=False) == plain


class _Writer:
    def __init__(self):
        self.frames = []

    async def __call__(self, b):
        self.frames.append(bytes(b))


def test_fragmentation_matches_espblufi_rules():
    import asyncio

    class Client:
        def __init__(self):
            self.w = _Writer()

        async def write_gatt_char(self, _uuid, data, response=True):
            await self.w(data)

    c = Client()
    bf = blufi.BluFi(c, mtu=23, log=lambda *_: None)
    payload = bytes(range(60))
    asyncio.run(bf.send(blufi.PKT_DATA, blufi.DATA_CUSTOM, payload))
    frames = c.w.frames
    # every frame fits the MTU, sequence numbers increase, fragments carry the remaining-length prefix
    assert all(len(f) <= 23 - 3 for f in frames)
    assert [f[2] for f in frames] == list(range(len(frames)))
    assert all(f[1] & blufi.FC_FRAG for f in frames[:-1]) and not (frames[-1][1] & blufi.FC_FRAG)
    body = b"".join(f[4:4 + f[3]][2:] for f in frames[:-1]) + frames[-1][4:4 + frames[-1][3]]
    assert body == payload


def test_reassembly_rejects_wrong_total():
    bf = blufi.BluFi(None, mtu=23, log=lambda *_: None)
    got = []
    bf._rx.put_nowait = got.append
    # two fragments declaring total 5 but delivering 6 bytes -> dropped
    bf._on_notify(0, bytes([blufi.DATA_CUSTOM << 2 | 1, blufi.FC_FRAG, 0, 5, 5, 0, 1, 2, 3]))
    bf._on_notify(0, bytes([blufi.DATA_CUSTOM << 2 | 1, 0, 1, 3, 4, 5, 6]))
    assert got == []


def test_encode_matches_app_rules():
    base = commands.ACState(power=True, temp=24, mode="cool", fan="auto")
    assert commands.encode(base.with_temp(25), base) == {"stemp": "25.0"}
    assert commands.encode(commands.ACState(power=False, temp=24), base) == {"pow": 0}
    d = commands.encode(commands.ACState(power=True, temp=24, mode="dry", fan="auto"), base)
    assert d == {"mode": {"value": 3, "stemp": "24.0", "fspd": 7}}
    assert commands.encode(commands.ACState(power=True, temp=24, conv=2), base) == {"eco": {"value": 2}}
    assert commands.encode(commands.ACState(power=True, temp=24, vswing=3), base) == {"vswing": 3}


def test_decode_status_fixture():
    st = commands.decode(FIXTURES["status"])
    assert st.power and st.temp == 16 and st.mode == "cool" and st.fan == "auto"
    assert st.ambient == 24.5 and st.vswing == 6 and st.display


def test_matches_handles_object_form_and_rejects_garbage():
    status = FIXTURES["status"]
    assert commands.matches({"mode": {"value": 2, "stemp": "99.0", "fspd": 1}}, status)
    assert not commands.matches({"stemp": "17.0"}, status)
    assert not commands.matches({"pow": 1}, {**status, "pow": 6, "stemp": "357.9"})

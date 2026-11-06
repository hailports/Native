import struct

from nativedisplay.catalog import override_modes
from nativedisplay.encode import (
    FLAG_BASE,
    FLAG_2X,
    TAIL,
    build_override,
    decode_entry,
    dump_plist,
    entries,
    load_plist,
    logical_modes,
)

# Bytes observed on a dummy panel and a built-in panel. They lock the codec.
MINI = [
    "000005a0000003840000000100200000",
    "000006900000041a0000000100200000",
    "00000b40000007080000000900200000",
    "00000b4000000708",
    "00000d20000008340000000900200000",
    "00000d2000000834",
    "00000560000004080000000100200000",
    "00000ac0000008100000000900200000",
    "00000ac000000810",
]
MACBOOK = [
    "00000d200000083400",
    "00000b400000070800",
    "00000a000000064000",
    "000008000000050000",
    "00000780000004b000000001",
    "00000540000003480000000100200000",
    "00000a80000006900000000900200000",
    "00000a8000000690",
    "00000540000003f00000000100200000",
    "00000a80000007e00000000900200000",
    "00000a80000007e0",
    "00000400000003000000000100200000",
    "00000800000006000000000900200000",
    "0000080000000600",
]


def test_entries_match_live_bytes():
    assert [blob.hex() for blob in entries(1440, 900)] == [
        "000005a0000003840000000100200000",
        "00000b40000007080000000900200000",
        "00000b4000000708",
    ]
    assert [blob.hex() for blob in entries(1680, 1050)] == [
        "000006900000041a0000000100200000",
        "00000d20000008340000000900200000",
        "00000d2000000834",
    ]
    assert [blob.hex() for blob in entries(1376, 1032)] == [
        "00000560000004080000000100200000",
        "00000ac0000008100000000900200000",
        "00000ac000000810",
    ]
    first = decode_entry(entries(1440, 900)[0])
    assert (first["w"], first["h"], first["flag"], first["tail"]) == (1440, 900, FLAG_BASE, TAIL)
    second = decode_entry(entries(1440, 900)[1])
    assert (second["w"], second["h"], second["flag"]) == (2880, 1800, FLAG_2X)


def test_round_trip_mini_modes_and_custom():
    modes = [(1440, 900), (1680, 1050), (1376, 1032), (1000, 800)]
    blobs = []
    for width, height in modes:
        blobs.extend(entries(width, height))
    assert logical_modes(blobs) == modes
    payload = build_override(1, 2, modes)
    loaded = load_plist(dump_plist(payload))
    assert logical_modes(loaded["scale-resolutions"]) == modes


def test_decode_live_fixtures():
    mini = logical_modes([bytes.fromhex(item) for item in MINI])
    assert mini == [(1440, 900), (1680, 1050), (1376, 1032)]
    mac = set(logical_modes([bytes.fromhex(item) for item in MACBOOK]))
    assert mac == {
        (1920, 1200),
        (1344, 840),
        (1344, 1008),
        (1024, 768),
        (1680, 1050),
        (1440, 900),
        (1280, 800),
        (1024, 640),
    }


def test_apple9_preserved_only_when_uncovered():
    extra = struct.pack(">IIB", 2222, 1112, 0)
    covered = struct.pack(">IIB", 2880, 1800, 0)
    payload = build_override(
        1,
        2,
        override_modes(),
        existing={
            "DisplayProductName": "Panel",
            "IODisplayEDID": b"keep",
            "scale-resolutions": [extra, covered],
        },
    )
    raws = payload["scale-resolutions"]
    assert extra in raws
    assert covered not in raws
    assert payload["IODisplayEDID"] == b"keep"
    logical = set(logical_modes(raws))
    assert (1111, 556) in logical
    assert (1440, 900) in logical
    assert (1376, 1032) in logical
    assert (1344, 1008) in logical

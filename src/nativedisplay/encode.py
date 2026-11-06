"""scale-resolutions codec for macOS display overrides.

Each logical WxH is written as three records, which is the encoding that makes
a size show up as a native HiDPI mode on a dummy panel and on a built-in panel:

  1x   16 bytes  width, height, flag 1, tail 0x200000
  2x   16 bytes  width*2, height*2, flag 9, tail 0x200000
  pair  8 bytes  width*2, height*2

Apple also stores some scaled modes as 9-byte records (width, height, 0x00)
and, less often, as 12-byte records (width, height, flag). Those are decoded
and kept when they name a logical size this catalog does not already emit.
"""

from __future__ import annotations

import plistlib
import struct

FLAG_BASE = 1
FLAG_2X = 9
TAIL = 0x200000


def entries(w: int, h: int) -> list[bytes]:
    if w < 1 or h < 1:
        raise ValueError(f"bad mode {w}x{h}")
    return [
        struct.pack(">IIII", w, h, FLAG_BASE, TAIL),
        struct.pack(">IIII", w * 2, h * 2, FLAG_2X, TAIL),
        struct.pack(">II", w * 2, h * 2),
    ]


def decode_entry(raw: bytes) -> dict:
    if len(raw) >= 16:
        w, h, flag, tail = struct.unpack(">IIII", raw[:16])
        return {"kind": "scaled", "w": w, "h": h, "flag": flag, "tail": tail, "raw": raw}
    if len(raw) == 12:
        w, h, flag = struct.unpack(">III", raw)
        return {"kind": "short", "w": w, "h": h, "flag": flag, "tail": None, "raw": raw}
    if len(raw) == 9:
        w, h = struct.unpack(">II", raw[:8])
        return {"kind": "apple9", "w": w, "h": h, "suffix": raw[8], "raw": raw}
    if len(raw) == 8:
        w, h = struct.unpack(">II", raw)
        return {"kind": "pair", "w": w, "h": h, "raw": raw}
    return {"kind": "unknown", "raw": raw}


def _logical_of(info: dict) -> tuple[int, int] | None:
    kind = info.get("kind")
    if kind == "scaled" and info.get("flag") == FLAG_BASE:
        return info["w"], info["h"]
    if kind == "short" and info.get("flag") == FLAG_BASE:
        return info["w"], info["h"]
    if kind == "apple9" and info["w"] % 2 == 0 and info["h"] % 2 == 0:
        # The 9-byte records on a built-in panel are 2x framebuffers
        # (3360x2100 is the HiDPI buffer for 1680x1050, not a 1x mode).
        return info["w"] // 2, info["h"] // 2
    return None


def logical_modes(blobs: list[bytes]) -> list[tuple[int, int]]:
    """Logical WxH values, flag-1 records first, then uncovered Apple 9-byte sizes."""
    decoded = [decode_entry(b) for b in blobs]
    found: list[tuple[int, int]] = []
    seen: set[tuple[int, int]] = set()
    deferred: list[tuple[int, int]] = []
    for info in decoded:
        logical = _logical_of(info)
        if logical is None:
            continue
        if info["kind"] == "apple9":
            deferred.append(logical)
            continue
        if logical not in seen:
            seen.add(logical)
            found.append(logical)
    for logical in deferred:
        if logical not in seen:
            seen.add(logical)
            found.append(logical)
    return found


def _covered(modes: list[tuple[int, int]]) -> set[tuple[int, int]]:
    covered: set[tuple[int, int]] = set()
    for w, h in modes:
        covered.add((w, h))
        covered.add((w * 2, h * 2))
    return covered


def preserved_blobs(existing: list[bytes], modes: list[tuple[int, int]]) -> list[bytes]:
    """Keep Apple-format records whose logical size is not in `modes`."""
    covered = _covered(modes)
    kept: list[bytes] = []
    for raw in existing:
        info = decode_entry(raw)
        logical = _logical_of(info)
        wh = (info.get("w"), info.get("h"))
        if info["kind"] == "unknown":
            kept.append(raw)
            continue
        if logical is None:
            continue
        if logical in covered or wh in covered:
            continue
        kept.append(raw)
    return kept


def build_override(
    vendor: int,
    product: int,
    modes: list[tuple[int, int]],
    existing: dict | None = None,
    name: str | None = None,
) -> dict:
    blobs: list[bytes] = []
    for w, h in modes:
        blobs.extend(entries(w, h))
    if existing:
        blobs.extend(preserved_blobs(list(existing.get("scale-resolutions") or []), modes))
        out = {k: v for k, v in existing.items() if k != "scale-resolutions"}
        out["DisplayVendorID"] = vendor
        out["DisplayProductID"] = product
        out["DisplayProductName"] = name or existing.get("DisplayProductName") or "Native Display"
        out["scale-resolutions"] = blobs
        return out
    return {
        "DisplayVendorID": vendor,
        "DisplayProductID": product,
        "DisplayProductName": name or "Native Display",
        "IOGFlags": 4,
        "scale-resolutions": blobs,
    }


def dump_plist(payload: dict) -> bytes:
    return plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=False)


def load_plist(data: bytes) -> dict:
    loaded = plistlib.loads(data)
    if not isinstance(loaded, dict):
        raise ValueError("display override is not a dictionary")
    return loaded

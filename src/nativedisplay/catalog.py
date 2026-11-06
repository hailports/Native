"""Named logical resolutions unlocked as native HiDPI modes.

The set is the Displays-style scaled list across 16:10, 16:9, and 4:3, plus
the tablet sizes that were injected as native modes on real panels:

  1344x1008   shared 4:3 tablet fallback (unrotated HiDPI); used when the client size is unknown
  1376x1032   13-inch iPad Pro logical (framebuffer 2752x2064); used when that client size is known
  1344x840    16:10 mode of the same width, used on a built-in panel
  1024x768    phone portrait base (rotated 90 when applied)

`add WxH` extends the list. Panel-specific odd scaled sizes that macOS already
advertises for one LCD are left alone; this catalog is what gets injected.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Mode:
    w: int
    h: int
    aspect: str
    aliases: tuple[str, ...] = ()

    @property
    def name(self) -> str:
        return f"{self.w}x{self.h}"

    @property
    def label(self) -> str:
        extra = ", ".join(self.aliases)
        return f"{self.name}  {self.aspect}" + (f"  ({extra})" if extra else "")


@dataclass(frozen=True)
class Profile:
    family: str
    w: int
    h: int
    hidpi: bool
    degree: int
    reason: str


def _m(w: int, h: int, aspect: str, *aliases: str) -> Mode:
    return Mode(w, h, aspect, aliases)


# Standard scaled logical sizes, then the proven injected natives.
CATALOG: tuple[Mode, ...] = (
    # 16:10 — Mac laptop / iMac scaled set, including sizes recovered from
    # Apple 9-byte and 12-byte records (1024x640, 1280x800, 1920x1200).
    _m(1024, 640, "16:10"),
    _m(1152, 720, "16:10"),
    _m(1280, 800, "16:10"),
    _m(1344, 840, "16:10", "16x10-narrow"),
    _m(1440, 900, "16:10", "16x10-compact"),
    _m(1680, 1050, "16:10", "16x10", "laptop", "mac"),
    _m(1920, 1200, "16:10"),
    _m(2048, 1280, "16:10"),
    _m(2304, 1440, "16:10"),
    _m(2560, 1600, "16:10"),
    _m(2880, 1800, "16:10"),
    _m(3072, 1920, "16:10"),
    _m(3840, 2400, "16:10"),
    # 16:9
    _m(1280, 720, "16:9", "16x9-small"),
    _m(1600, 900, "16:9"),
    _m(1920, 1080, "16:9", "16x9"),
    _m(2048, 1152, "16:9"),
    _m(2304, 1296, "16:9"),
    _m(2560, 1440, "16:9"),
    _m(2880, 1620, "16:9"),
    _m(3200, 1800, "16:9"),
    _m(3840, 2160, "16:9"),
    _m(4096, 2304, "16:9"),
    _m(5120, 2880, "16:9"),
    # 4:3, including iPad and phone bases.
    _m(640, 480, "4:3"),
    _m(800, 600, "4:3", "phone-compact"),
    _m(1024, 768, "4:3", "iphone", "phone"),
    _m(1152, 864, "4:3"),
    _m(1280, 960, "4:3"),
    _m(1344, 1008, "4:3", "ipad", "ipad-4x3", "tablet"),
    _m(1376, 1032, "4:3", "ipad-pro-13"),
    _m(1400, 1050, "4:3"),
    _m(1600, 1200, "4:3"),
    _m(1920, 1440, "4:3"),
    _m(2048, 1536, "4:3"),
    # Other current iPad Pro logical sizes (half the panel pixels).
    _m(1366, 1024, "4:3", "ipad-pro-12.9"),
    _m(1210, 834, "~3:2", "ipad-pro-11"),
)

PROFILES: dict[str, Profile] = {
    "ipad": Profile(
        "ipad",
        1344,
        1008,
        True,
        0,
        "tablet landscape fallback: 1344x1008 HiDPI, unrotated; nearest advertised 4:3 if that mode is not live yet",
    ),
    "iphone": Profile(
        "iphone",
        1024,
        768,
        True,
        90,
        "phone portrait: 1024x768 HiDPI rotated 90, or the nearest advertised 4:3 such as 800x600",
    ),
    "mac": Profile(
        "mac",
        1680,
        1050,
        True,
        0,
        "16:10 laptop canvas 1680x1050 HiDPI, or the nearest advertised 16:10 such as 1440x900",
    ),
}

_BY_NAME: dict[str, Mode] = {}
_BY_SIZE: dict[tuple[int, int], Mode] = {}
for _mode in CATALOG:
    _BY_SIZE[( _mode.w, _mode.h)] = _mode
    _BY_NAME[_mode.name] = _mode
    for _alias in _mode.aliases:
        _BY_NAME[_alias.lower()] = _mode


def lookup(name: str) -> Mode | None:
    key = name.strip().lower().replace(" ", "")
    if key in _BY_NAME:
        return _BY_NAME[key]
    parsed = parse_size(key)
    if parsed and parsed in _BY_SIZE:
        return _BY_SIZE[parsed]
    return None


def parse_size(text: str) -> tuple[int, int] | None:
    raw = text.strip().lower().replace(" ", "")
    if "x" not in raw:
        return None
    left, right = raw.split("x", 1)
    if not left.isdigit() or not right.isdigit():
        return None
    w, h = int(left), int(right)
    if w < 1 or h < 1 or w > 10000 or h > 10000:
        return None
    return w, h


def override_modes(extra: list[tuple[int, int]] | None = None) -> list[tuple[int, int]]:
    seen: set[tuple[int, int]] = set()
    out: list[tuple[int, int]] = []
    for mode in CATALOG:
        key = (mode.w, mode.h)
        if key not in seen:
            seen.add(key)
            out.append(key)
    for key in extra or []:
        if key not in seen:
            seen.add(key)
            out.append(key)
    return out


def aspects() -> set[str]:
    return {mode.aspect for mode in CATALOG}

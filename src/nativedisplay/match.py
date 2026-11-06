"""Choose a logical HiDPI mode for a viewer. Unknown sessions do not move the display."""

from __future__ import annotations

from dataclasses import dataclass

from nativedisplay.catalog import PROFILES, Profile

# Same-aspect nearest mode. 16:10 vs 16:9 is about 0.18, so 0.02 keeps a
# fallback inside the family (1344x1008 for 1376x1032, 1440x900 for 1680x1050)
# and refuses a different aspect.
ASPECT_TOLERANCE = 0.02
FAMILY_ORDER = ("iphone", "ipad", "mac")


@dataclass(frozen=True)
class Decision:
    w: int
    h: int
    hidpi: bool
    degree: int
    family: str | None
    reason: str
    verified: bool


def pick_mode(
    tw: int,
    th: int,
    want_hidpi: bool,
    modes: list[tuple[int, int, bool]],
) -> tuple[int, int, bool] | None:
    """Nearest advertised mode: aspect first, then area, then HiDPI preference.

    This is the display_autoresizer scorer. Callers that must stay on the
    target aspect apply ASPECT_TOLERANCE themselves.
    """
    if not modes or tw <= 0 or th <= 0:
        return None
    target_ar = tw / th

    def score(mode: tuple[int, int, bool]) -> tuple[float, float, float]:
        w, h, scaling = mode
        ar_pen = abs((w / h) - target_ar) * 5.0
        area_pen = abs((w * h) - (tw * th)) / 1_000_000.0
        hidpi_pen = 0.0 if scaling == want_hidpi else 0.4
        return ar_pen + area_pen + hidpi_pen

    return min(modes, key=score)


def logical_target(width: int, height: int) -> tuple[int, int]:
    """Map a panel pixel size onto a HiDPI logical size when it is an even 2x buffer."""
    if width >= 2000 and height >= 1500 and width % 2 == 0 and height % 2 == 0:
        return width // 2, height // 2
    return width, height


def _aspect_ok(w: int, h: int, tw: int, th: int) -> bool:
    return abs((w / h) - (tw / th)) <= ASPECT_TOLERANCE


def resolve_profile(
    profile: Profile,
    advertised: list[tuple[int, int, bool]] | None,
    *,
    native: tuple[int, int] | None = None,
) -> Decision | None:
    tw, th = profile.w, profile.h
    reason = profile.reason
    # Automatic iPad canvas stays 1344x1008 even if the client reports 2752x2064
    # panel pixels (which would otherwise become 1376x1032). iPad is landscape
    # only (degree 0). Only iPhone uses rotation.
    if native and profile.family != "ipad":
        tw, th = logical_target(*native)
        reason = f"{profile.family} native {native[0]}x{native[1]} -> logical {tw}x{th}"
    if advertised is None:
        return Decision(tw, th, profile.hidpi, profile.degree, profile.family, reason, False)
    chosen = pick_mode(tw, th, profile.hidpi, advertised)
    if chosen is None or not _aspect_ok(chosen[0], chosen[1], tw, th):
        return None
    w, h, hidpi = chosen
    note = reason
    if (w, h) != (tw, th):
        note = f"{reason}; advertised {w}x{h}"
    return Decision(w, h, hidpi, profile.degree, profile.family, note, True)


def resolve_size(
    width: int,
    height: int,
    advertised: list[tuple[int, int, bool]] | None,
    *,
    degree: int = 0,
) -> Decision | None:
    tw, th = logical_target(width, height)
    if advertised is None:
        return Decision(tw, th, True, degree, None, f"explicit {tw}x{th}", False)
    chosen = pick_mode(tw, th, True, advertised)
    if chosen is None or not _aspect_ok(chosen[0], chosen[1], tw, th):
        return None
    w, h, hidpi = chosen
    return Decision(w, h, hidpi, degree, None, f"explicit {tw}x{th}", True)


def decide(
    families: list[str],
    *,
    latch: str = "auto",
    advertised: list[tuple[int, int, bool]] | None = None,
    natives: dict[str, tuple[int, int]] | None = None,
    explicit: tuple[int, int] | None = None,
    explicit_degree: int = 0,
) -> Decision | None:
    """Pick one mode, or None when the display must be left alone.

    `latch="local"` is the desktop override: auto selection does nothing.
    An empty `families` list with no explicit size is "no hints".
    """
    if latch == "local" and explicit is None:
        return None
    if explicit is not None:
        return resolve_size(explicit[0], explicit[1], advertised, degree=explicit_degree)
    natives = natives or {}
    for family in FAMILY_ORDER:
        if family not in families:
            continue
        profile = PROFILES[family]
        return resolve_profile(profile, advertised, native=natives.get(family))
    return None

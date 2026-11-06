from nativedisplay.catalog import CATALOG, aspects, lookup, override_modes


def test_aspects_and_natives_present():
    found = aspects()
    assert {"16:10", "16:9", "4:3"} <= found
    sizes = {(mode.w, mode.h) for mode in CATALOG}
    for size in (
        (1440, 900),
        (1680, 1050),
        (1344, 840),
        (1280, 800),
        (1920, 1200),
        (1920, 1080),
        (2560, 1440),
        (3840, 2160),
        (1024, 768),
        (800, 600),
        (640, 480),
        (1376, 1032),
        (1344, 1008),
    ):
        assert size in sizes
    assert lookup("ipad").w == 1376
    assert lookup("ipad-4x3").name == "1344x1008"
    assert lookup("16x10").name == "1680x1050"
    assert lookup("iphone").name == "1024x768"
    assert len(override_modes()) == len(sizes)
    assert len({mode.name for mode in CATALOG}) == len(CATALOG)

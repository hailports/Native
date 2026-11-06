from nativedisplay.cli import detect_displays, main
from nativedisplay.discover import Viewer
from nativedisplay.encode import load_plist, logical_modes


def test_list_and_add_and_dry_setup(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("NATIVEDISPLAY_STATE", str(tmp_path))
    assert main(["list"]) == 0
    listed = capsys.readouterr().out
    assert "1376x1032" in listed
    assert "1344x1008" in listed
    assert "1680x1050" in listed
    assert "1920x1080" in listed
    assert main(["add", "1111x777", "--dry"]) == 0
    assert main(["setup", "--dry", "--vendor", "0x10", "--product", "0x20"]) == 0
    preview = tmp_path / "preview" / "DisplayProductID-20"
    logical = set(logical_modes(load_plist(preview.read_bytes())["scale-resolutions"]))
    assert (1111, 777) in logical
    assert (1376, 1032) in logical
    assert (1440, 900) in logical
    assert "WindowServer" in capsys.readouterr().out


def test_apply_family_and_unknown(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("NATIVEDISPLAY_STATE", str(tmp_path))
    monkeypatch.setattr("nativedisplay.cli.find_displayplacer", lambda: None)
    monkeypatch.setattr("nativedisplay.cli.current_viewers", lambda: [])
    assert main(["apply", "--ipad", "--dry"]) == 0
    assert "1344x1008" in capsys.readouterr().out
    assert main(["apply", "--16x10", "--dry"]) == 0
    assert "1680x1050" in capsys.readouterr().out
    assert main(["apply", "1376x1032", "--dry"]) == 0
    assert "1376x1032" in capsys.readouterr().out
    assert main(["apply", "--dry"]) == 0
    assert "unchanged" in capsys.readouterr().out


def test_apply_uses_reported_tablet_size(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("NATIVEDISPLAY_STATE", str(tmp_path))
    monkeypatch.setattr("nativedisplay.cli.find_displayplacer", lambda: None)
    monkeypatch.setattr(
        "nativedisplay.cli.current_viewers",
        lambda: [Viewer("ipad", "iPad-2752x2064", None, (2752, 2064), "dns")],
    )
    assert main(["apply", "--dry"]) == 0
    out = capsys.readouterr().out
    assert "1376x1032" in out
    assert "degree:0" in out


def test_setup_walkthrough(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("NATIVEDISPLAY_STATE", str(tmp_path))
    monkeypatch.setattr("nativedisplay.cli.find_displayplacer", lambda: None)
    assert main(["setup", "--dry", "--vendor", "0x11", "--product", "0x21"]) == 0
    out = capsys.readouterr().out
    assert "scale-resolutions" in out
    assert "sudo" in out
    assert "native status" in out
    assert "brew install displayplacer" in out
    assert "does not restart WindowServer" in out


def test_local_latch_blocks_watch(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv("NATIVEDISPLAY_STATE", str(tmp_path))
    monkeypatch.setattr("nativedisplay.cli.current_viewers", lambda: [])
    assert main(["local"]) == 0
    assert main(["watch", "--once", "--dry"]) == 0
    assert "local pin" in capsys.readouterr().out
    assert main(["auto"]) == 0


def test_detect_ioreg_text():
    text = '\n'.join(
        [
            '"DisplayVendorID" = 99',
            '"DisplayProductID" = 100',
            '"DisplayProductName" = "Panel"',
            '"DisplayVendorID" = 99',
            '"DisplayProductID" = 100',
        ]
    )
    found = detect_displays(text)
    assert found == [{"vendor": 99, "product": 100, "name": "Panel"}]

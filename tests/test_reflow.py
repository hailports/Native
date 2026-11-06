import json

from nativedisplay.cli import main
from nativedisplay.keyboard_reflow import Controller, Yabai, geometry, parse_env


def test_math_and_unknown_state_is_noop(capsys, tmp_path):
    assert geometry()["safe_bottom"] == 761
    assert geometry()["padding"] == 202
    assert geometry()["phone_width"] == 768
    assert geometry()["phone_height"] == 1024
    assert parse_env("nope", 1_000.0) == "unknown"
    calls = []
    controller = Controller(
        yabai=Yabai(runner=lambda args: calls.append(args) or "0"),
        files=[(tmp_path / "mobile-session-state.env", None)],
        adapter=None,
        now=lambda: 1_000.0,
    )
    result = controller.once(dry_run=False)
    assert result["noop"] == "unknown-state"
    assert calls == []
    assert main(["reflow", "--math"]) == 0
    body = json.loads(capsys.readouterr().out)
    assert body["padding"] == 202
    assert body["safe_bottom"] == 761


def test_install_agent_does_not_load(capsys, tmp_path):
    assert main(["reflow", "--install-agent", "--dest", str(tmp_path)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["loaded"] is False
    text = (tmp_path / (payload["label"] + ".plist")).read_text()
    assert payload["label"] == "com.hailports.nativedisplay.keyboard-reflow"
    assert "com." + "al" + "ex." not in text
    assert "<integer>4</integer>" in text

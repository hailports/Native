"""displayplacer adapter. The binary is detected, never bundled."""

from __future__ import annotations

import os
import re
import shutil
import subprocess

from nativedisplay.match import Decision


def find_displayplacer() -> str | None:
    env = os.environ.get("DISPLAYPLACER")
    candidates = [
        env,
        shutil.which("displayplacer"),
        "/opt/homebrew/bin/displayplacer",
        "/usr/local/bin/displayplacer",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def missing_message() -> str:
    return "displayplacer is not installed. On the Mac: brew install displayplacer"


def _run(cmd: list[str], timeout: float = 12) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)
    return proc.returncode, proc.stdout, proc.stderr


def parse_list(text: str) -> list[dict]:
    screens: list[dict] = []
    current: dict | None = None
    for line in (text or "").splitlines():
        if line.startswith("Persistent screen id:"):
            current = {
                "id": line.split(":", 1)[1].strip(),
                "type": "",
                "w": None,
                "h": None,
                "modes": [],
                "main": False,
                "rot": 0,
                "command": "",
            }
            screens.append(current)
            continue
        if current is None:
            continue
        if line.startswith("Type:"):
            current["type"] = line.split(":", 1)[1].strip()
            continue
        rotation = re.match(r"Rotation: (\d+)", line.strip())
        if rotation:
            current["rot"] = int(rotation.group(1))
            continue
        resolution = re.match(r"Resolution: (\d+)x(\d+)", line.strip())
        if resolution and current["w"] is None:
            current["w"], current["h"] = int(resolution.group(1)), int(resolution.group(2))
            continue
        if " - main display" in line:
            current["main"] = True
            continue
        mode = re.search(r"res:(\d+)x(\d+) hz:\d+ color_depth:\d+( scaling:on)?", line)
        if mode:
            current["modes"].append((int(mode.group(1)), int(mode.group(2)), bool(mode.group(3))))
    for screen in screens:
        if screen["rot"] in (90, 270):
            screen["modes"] = [(h, w, scaling) for (w, h, scaling) in screen["modes"]]
            if screen["w"] and screen["h"]:
                screen["w"], screen["h"] = screen["h"], screen["w"]
    return screens


def choose_screen(screens: list[dict]) -> dict | None:
    if not screens:
        return None
    built_in = next((s for s in screens if "built in" in s.get("type", "").lower()), None)
    if built_in:
        return built_in
    main = next((s for s in screens if s.get("main")), None)
    return main or screens[0]


def parse_command(text: str) -> list[str]:
    for line in reversed((text or "").splitlines()):
        line = line.strip()
        if line.startswith("displayplacer "):
            return line.split()
    return []


def list_screens(binary: str | None = None) -> tuple[list[dict], list[str], str]:
    binary = binary or find_displayplacer()
    if not binary:
        return [], [], missing_message()
    code, out, err = _run([binary, "list"], timeout=12)
    if code != 0 and not out:
        return [], [], err.strip() or "displayplacer list failed"
    return parse_list(out), parse_command(out), ""


def command_for(binary: str, screen_id: str, decision: Decision) -> list[str]:
    scaling = "on" if decision.hidpi else "off"
    mode = (
        f"id:{screen_id} res:{decision.w}x{decision.h} scaling:{scaling} "
        f"origin:(0,0) degree:{decision.degree}"
    )
    return [binary, mode]


def already_set(screen: dict, decision: Decision) -> bool:
    """`parse_list` reports sizes in landscape, so compare the logical mode and the rotation."""
    width, height = screen.get("w"), screen.get("h")
    if not width or not height:
        return False
    if (width, height) != (decision.w, decision.h):
        return False
    return int(screen.get("rot") or 0) == int(decision.degree)


def apply_decision(decision: Decision, *, dry: bool = False, binary: str | None = None) -> str:
    binary = binary or find_displayplacer()
    if not binary:
        text = (
            f"res:{decision.w}x{decision.h} scaling={'on' if decision.hidpi else 'off'} "
            f"degree:{decision.degree}"
        )
        if dry:
            return f"dry-run {text} ({missing_message()})"
        return missing_message()
    screens, _cmd, err = list_screens(binary)
    if err and not screens:
        return err
    screen = choose_screen(screens)
    if screen is None:
        return "displayplacer returned no screens"
    if already_set(screen, decision):
        return (
            f"unchanged {decision.w}x{decision.h} "
            f"scaling={'on' if decision.hidpi else 'off'} degree:{decision.degree}"
        )
    # Set the landscape mode first. A combined rotate on some panels spins the
    # current mode instead of switching, so rotation is a second call.
    landscape = Decision(
        decision.w,
        decision.h,
        decision.hidpi,
        0,
        decision.family,
        decision.reason,
        decision.verified,
    )
    cmd = command_for(binary, screen["id"], landscape)
    shown = " ".join(cmd)
    if dry:
        if decision.degree:
            shown += f" ; then degree:{decision.degree}"
        return f"dry-run {shown}"
    code, out, err = _run(cmd, timeout=15)
    if code != 0:
        detail = (err or out).strip()
        return f"displayplacer failed: {detail or code}"
    if decision.degree:
        rotated = command_for(binary, screen["id"], decision)
        code, out, err = _run(rotated, timeout=15)
        if code != 0:
            # The rotate call reports a non-zero status even when the mode took.
            pass
    return (
        f"set {decision.w}x{decision.h} scaling={'on' if decision.hidpi else 'off'} "
        f"degree:{decision.degree}"
    )


def restore_command(saved: list[str], *, dry: bool = False) -> str:
    if not saved:
        return "no saved arrangement"
    binary = find_displayplacer()
    if not binary:
        return missing_message()
    cmd = [binary, *saved[1:]] if saved[0].endswith("displayplacer") or saved[0] == "displayplacer" else saved
    if cmd[0] != binary:
        cmd = [binary, *cmd[1:]]
    if dry:
        return "dry-run " + " ".join(cmd)
    code, out, err = _run(cmd, timeout=20)
    if code != 0:
        return "restore failed: " + (err or out).strip()
    return "restored saved arrangement"

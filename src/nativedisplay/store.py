"""Local state: custom modes, the desktop latch, and the saved arrangement."""

from __future__ import annotations

import json
import os
from pathlib import Path


def state_dir() -> Path:
    override = os.environ.get("NATIVEDISPLAY_STATE")
    if override:
        path = Path(override)
    elif sys_darwin():
        path = Path.home() / "Library/Application Support/nativedisplay"
    else:
        root = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config"))
        path = root / "nativedisplay"
    path.mkdir(parents=True, exist_ok=True)
    return path


def sys_darwin() -> bool:
    return os.uname().sysname == "Darwin"


def _read(name: str) -> dict:
    path = state_dir() / name
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _write(name: str, data: dict) -> None:
    path = state_dir() / name
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def extra_modes() -> list[tuple[int, int]]:
    raw = _read("extras.json").get("modes") or []
    out: list[tuple[int, int]] = []
    for item in raw:
        if isinstance(item, list) and len(item) == 2:
            out.append((int(item[0]), int(item[1])))
    return out


def add_mode(width: int, height: int) -> list[tuple[int, int]]:
    modes = extra_modes()
    key = (width, height)
    if key not in modes:
        modes.append(key)
    _write("extras.json", {"modes": [list(item) for item in modes]})
    return modes


def latch() -> str:
    return "local" if (state_dir() / "local-override").exists() else "auto"


def set_latch(mode: str) -> None:
    path = state_dir() / "local-override"
    if mode == "local":
        path.write_text("local\n")
    else:
        path.unlink(missing_ok=True)


def save_arrangement(command: list[str]) -> None:
    if not command:
        return
    current = _read("arrangement.json")
    if current.get("command"):
        return
    _write("arrangement.json", {"command": command})


def saved_arrangement() -> list[str]:
    command = _read("arrangement.json").get("command") or []
    return [str(part) for part in command]


def last_applied() -> dict:
    return _read("applied.json")


def remember_applied(payload: dict) -> None:
    _write("applied.json", payload)

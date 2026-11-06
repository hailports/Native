"""nativedisplay command line."""

from __future__ import annotations

import argparse
import hashlib
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from nativedisplay import __version__
from nativedisplay.catalog import CATALOG, PROFILES, lookup, override_modes, parse_size
from nativedisplay.discover import current_viewers, viewer_from_parts
from nativedisplay.display import (
    apply_decision,
    find_displayplacer,
    list_screens,
    missing_message,
    restore_command,
)
from nativedisplay.encode import build_override, dump_plist, load_plist, logical_modes
from nativedisplay.match import decide
from nativedisplay.store import (
    add_mode,
    extra_modes,
    last_applied,
    latch,
    remember_applied,
    save_arrangement,
    saved_arrangement,
    set_latch,
    state_dir,
    sys_darwin,
)

ACTIVATION = (
    "New modes load on the next logout, display hotplug, or wake. "
    "This command does not restart WindowServer."
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="native",
        description="Native display resizing and desktop reduction for remote devices.",
    )
    parser.add_argument("--version", action="version", version=f"nativedisplay {__version__}")
    sub = parser.add_subparsers(dest="cmd", required=True)

    setup = sub.add_parser("setup", help="walk through installing the HiDPI override for each attached display")
    setup.add_argument("--dry", action="store_true", help="print the override and do not write it")
    setup.add_argument("--vendor", help="vendor id, decimal or 0x hex, with --product")
    setup.add_argument("--product", help="product id, decimal or 0x hex, with --vendor")

    sub.add_parser("status", help="show latch, viewers, and whether the override is installed")
    sub.add_parser("list", help="list catalog configs and any added sizes")

    apply = sub.add_parser("apply", help="set the display from the current viewer, a size, or a family")
    apply.add_argument("size", nargs="?", help="WxH logical or pixel size")
    apply.add_argument("--ipad", action="store_true")
    apply.add_argument("--iphone", action="store_true")
    apply.add_argument("--16x10", dest="sixteen_ten", action="store_true")
    apply.add_argument("--16x9", dest="sixteen_nine", action="store_true")
    apply.add_argument("--dry", action="store_true")

    add = sub.add_parser("add", help="remember WxH and merge it into the override encoding")
    add.add_argument("size", help="WxH, for example 1210x834")
    add.add_argument("--dry", action="store_true")

    watch = sub.add_parser("watch", help="keep the display matched to the current viewer")
    watch.add_argument("--interval", type=float, default=2.0)
    watch.add_argument("--once", action="store_true", help="single idempotent tick")
    watch.add_argument("--dry", action="store_true")

    for name, help_text in (
        ("local", "pin the desktop; ignore remote viewers until auto"),
        ("restore", "same as local: pin the desktop and put the saved arrangement back"),
        ("auto", "clear the local pin and follow viewers again"),
        ("sentinel", "restore the override file if it was deleted; never changes the live mode"),
    ):
        sub.add_parser(name, help=help_text)

    reflow = sub.add_parser(
        "reflow",
        help="inset windows above an iPhone on-screen keyboard; no-op unless that session is current",
    )
    reflow.add_argument("--dry", action="store_true", help="print the decision and do not change padding")
    reflow.add_argument("--status", action="store_true")
    reflow.add_argument("--math", action="store_true", help="print the calibrated 761/202 geometry")
    reflow.add_argument("--install-agent", action="store_true", help="write a LaunchAgent plist and do not load it")
    reflow.add_argument("--dest", default="", help="directory for the plist; used with --install-agent")
    return parser


def _parse_id(text: str) -> int:
    return int(text, 0)


def detect_displays(text: str | None = None) -> list[dict]:
    """Vendor and product from `ioreg`, same keys as the override generator.

    A display block is closed when the next vendor id starts, or at the end,
    so a product name that follows the two ids is kept.
    """
    if text is None:
        text = _ioreg_text()
    found: list[dict] = []
    seen: set[tuple[int, int]] = set()
    current: dict = {}

    def flush() -> None:
        if "DisplayVendorID" not in current or "DisplayProductID" not in current:
            current.clear()
            return
        vendor = int(current["DisplayVendorID"])
        product = int(current["DisplayProductID"])
        key = (vendor, product)
        if key not in seen and vendor and product:
            seen.add(key)
            found.append(
                {
                    "vendor": vendor,
                    "product": product,
                    "name": str(current.get("DisplayProductName") or "Native Display"),
                }
            )
        current.clear()

    for line in (text or "").splitlines():
        for key in ("DisplayVendorID", "DisplayProductID", "DisplayProductName"):
            match = re.search(rf'"{key}" = (?:"([^"]*)"|(\d+))', line)
            if not match:
                continue
            if key == "DisplayVendorID" and "DisplayProductID" in current:
                flush()
            current[key] = match.group(1) if match.group(1) is not None else int(match.group(2))
    flush()
    return found


def _ioreg_text() -> str:
    if not sys_darwin():
        return ""
    for class_name in ("AppleDisplay", "IODisplayConnect"):
        try:
            proc = subprocess.run(
                ["ioreg", "-l", "-w0", "-r", "-c", class_name],
                capture_output=True,
                text=True,
                timeout=8,
            )
        except (OSError, subprocess.TimeoutExpired):
            continue
        if proc.stdout.strip():
            return proc.stdout
    return ""


def override_path(vendor: int, product: int) -> Path:
    return Path(
        "/Library/Displays/Contents/Resources/Overrides/"
        f"DisplayVendorID-{vendor:x}/DisplayProductID-{product:x}"
    )


def _sentinel_root() -> Path:
    return Path("/Library/Application Support/nativedisplay")


def _install_bytes(dest: Path, payload: bytes) -> None:
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(payload)
        os.chmod(dest, 0o644)
        return
    staging = state_dir() / "staging" / dest.name
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(payload)
    subprocess.run(["sudo", "mkdir", "-p", str(dest.parent)], check=True)
    subprocess.run(["sudo", "cp", str(staging), str(dest)], check=True)
    subprocess.run(["sudo", "chown", "root:wheel", str(dest)], check=True)
    subprocess.run(["sudo", "chmod", "644", str(dest)], check=True)


def _write_sentinel(dest: Path, payload: bytes) -> None:
    folder = _sentinel_root() / "overrides"
    copy = folder / (dest.parent.name + "__" + dest.name)
    if hasattr(os, "geteuid") and os.geteuid() == 0:
        folder.mkdir(parents=True, exist_ok=True)
        copy.write_bytes(payload)
        return
    staging = state_dir() / "staging" / copy.name
    staging.parent.mkdir(parents=True, exist_ok=True)
    staging.write_bytes(payload)
    subprocess.run(["sudo", "mkdir", "-p", str(folder)], check=True)
    subprocess.run(["sudo", "cp", str(staging), str(copy)], check=True)
    subprocess.run(["sudo", "chmod", "644", str(copy)], check=True)


def _backup_existing(dest: Path) -> None:
    if not dest.exists():
        return
    stamp = time.strftime("%Y%m%d%H%M%S")
    backup = state_dir() / "backups" / f"{dest.parent.name}__{dest.name}.{stamp}"
    backup.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(dest, backup)
    except OSError:
        subprocess.run(["sudo", "cp", str(dest), str(backup)], check=False)


def build_for_display(display: dict, *, dry: bool) -> tuple[Path, bytes, list[tuple[int, int]]]:
    dest = override_path(display["vendor"], display["product"])
    existing = None
    if dest.exists():
        try:
            existing = load_plist(dest.read_bytes())
        except (OSError, ValueError):
            existing = None
    modes = override_modes(extra_modes())
    payload = build_override(
        display["vendor"],
        display["product"],
        modes,
        existing=existing,
        name=display.get("name"),
    )
    return dest, dump_plist(payload), logical_modes(payload["scale-resolutions"])


def cmd_setup(args: argparse.Namespace) -> int:
    print("Native setup writes HiDPI scale-resolutions for each attached display.")
    print("It will:")
    print("  1. Detect attached displays (or use the vendor and product you passed).")
    print("  2. Back up any previous override file.")
    print("  3. Write the scale-resolutions override. That needs sudo once.")
    if args.dry:
        print("Dry run: the override is not installed.")
    else:
        print("The live mode is not changed by this command.")
    if not find_displayplacer():
        print(missing_message())
        print("setup can still write the override. apply and watch need displayplacer to change the mode.")
    if args.vendor or args.product:
        if not (args.vendor and args.product):
            print("setup needs both --vendor and --product, or neither", file=sys.stderr)
            return 2
        displays = [{"vendor": _parse_id(args.vendor), "product": _parse_id(args.product), "name": "Native Display"}]
    else:
        displays = detect_displays()
    if not displays:
        print("No display vendor/product found. Pass --vendor and --product, or run this on the Mac.", file=sys.stderr)
        return 1
    for display in displays:
        dest, blob, modes = build_for_display(display, dry=args.dry)
        print(
            f"vendor=0x{display['vendor']:x} product=0x{display['product']:x} "
            f"name={display['name']} modes={len(modes)}"
        )
        print(f"  {dest}")
        if args.dry:
            preview = state_dir() / "preview" / dest.name
            preview.parent.mkdir(parents=True, exist_ok=True)
            preview.write_bytes(blob)
            print(f"  dry-run wrote {preview}")
            continue
        _backup_existing(dest)
        _install_bytes(dest, blob)
        _write_sentinel(dest, blob)
        print("  installed")
    print(ACTIVATION)
    print("Next:")
    print("  1. Log out, unplug and replug the display, or wake from sleep so the new modes load.")
    print("  2. Run: native status")
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    print("catalog")
    for mode in CATALOG:
        print("  " + mode.label)
    extras = extra_modes()
    known = {(mode.w, mode.h) for mode in CATALOG}
    added = [item for item in extras if item not in known]
    if added:
        print("added")
        for width, height in added:
            print(f"  {width}x{height}")
    print("profiles")
    for profile in PROFILES.values():
        print(f"  {profile.family}: {profile.w}x{profile.h} hidpi degree:{profile.degree}")
    return 0


def _explicit_from_args(args: argparse.Namespace) -> tuple[tuple[int, int] | None, int, list[str]]:
    families: list[str] = []
    degree = 0
    if getattr(args, "ipad", False):
        families.append("ipad")
    if getattr(args, "iphone", False):
        families.append("iphone")
        degree = PROFILES["iphone"].degree
    if getattr(args, "sixteen_ten", False):
        families.append("mac")
    if getattr(args, "sixteen_nine", False):
        size = parse_size("1920x1080")
        return size, 0, families
    size = None
    if getattr(args, "size", None):
        size = parse_size(args.size)
        if size is None:
            named = lookup(args.size)
            if named is None:
                raise ValueError(f"not a size or config: {args.size}")
            size = (named.w, named.h)
    elif families and not (args.ipad or args.iphone or args.sixteen_ten):
        pass
    if args.sixteen_nine and families:
        # An explicit 16:9 size wins over a family flag when both were passed.
        return size, degree, []
    if size and not families:
        return size, degree, []
    if families:
        return None, degree, families
    return size, degree, []


_NO_VIEWER = object()


def _decision_for(args: argparse.Namespace, advertised):
    try:
        size, degree, families = _explicit_from_args(args)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return None, 2
    if size is None and not families:
        viewers = current_viewers()
        families = [viewer.family for viewer in viewers if viewer.family]
        natives = {}
        for viewer in viewers:
            if viewer.family and viewer.native and viewer.family not in natives:
                natives[viewer.family] = viewer.native
        if not families and not natives:
            return _NO_VIEWER, 0
        chosen = decide(families, latch=latch(), advertised=advertised, natives=natives)
        return chosen, 0
    if families and size is None:
        chosen = decide(families, latch="auto", advertised=advertised, explicit_degree=degree)
        return chosen, 0
    chosen = decide([], latch="auto", advertised=advertised, explicit=size, explicit_degree=degree)
    return chosen, 0


def _advertised():
    screens, command, _err = list_screens()
    if command:
        save_arrangement(command)
    if not screens:
        return None
    screen = screens[0]
    for item in screens:
        if item.get("main") or "built in" in item.get("type", "").lower():
            screen = item
            break
    return list(screen.get("modes") or [])


def cmd_apply(args: argparse.Namespace) -> int:
    if latch() == "local" and not (args.size or args.ipad or args.iphone or args.sixteen_ten or args.sixteen_nine):
        print("local pin is set; display left unchanged (nativedisplay auto to follow viewers)")
        return 0
    advertised = _advertised() if find_displayplacer() else None
    chosen, code = _decision_for(args, advertised)
    if code:
        return code
    if chosen is _NO_VIEWER:
        print("no classified viewer; display left unchanged")
        return 0
    if chosen is None:
        print("no matching advertised mode; display left unchanged")
        if advertised is not None:
            print(ACTIVATION)
        return 0
    print(chosen.reason)
    result = apply_decision(chosen, dry=args.dry)
    print(result)
    if not args.dry and result.startswith("set"):
        remember_applied(
            {
                "w": chosen.w,
                "h": chosen.h,
                "hidpi": chosen.hidpi,
                "degree": chosen.degree,
                "family": chosen.family,
            }
        )
    return 0 if not result.startswith("displayplacer failed") else 1


def cmd_add(args: argparse.Namespace) -> int:
    size = parse_size(args.size)
    if size is None:
        print(f"not a size: {args.size}", file=sys.stderr)
        return 2
    modes = add_mode(*size)
    print(f"added {size[0]}x{size[1]} ({len(modes)} custom)")
    if args.dry:
        return 0
    displays = detect_displays()
    if not displays:
        print("saved for the next setup; no display detected on this machine")
        return 0
    args.dry = False
    args.vendor = None
    args.product = None
    print(ACTIVATION)
    return cmd_setup(args)


def _tick(dry: bool) -> str:
    if latch() == "local":
        return "local pin; unchanged"
    viewers = current_viewers()
    families = [viewer.family for viewer in viewers if viewer.family]
    natives = {}
    for viewer in viewers:
        if viewer.family and viewer.native and viewer.family not in natives:
            natives[viewer.family] = viewer.native
    if not families:
        return "no classified viewer; unchanged"
    advertised = _advertised() if find_displayplacer() else None
    # A watch tick must not guess a mode the panel has not advertised.
    if advertised is None:
        return "display modes unreadable; unchanged"
    chosen = decide(families, latch="auto", advertised=advertised, natives=natives)
    if chosen is None:
        return "no same-aspect advertised mode; unchanged"
    previous = last_applied()
    signature = {
        "w": chosen.w,
        "h": chosen.h,
        "hidpi": chosen.hidpi,
        "degree": chosen.degree,
        "family": chosen.family,
    }
    if previous == signature and not dry:
        return f"holding {chosen.w}x{chosen.h}"
    result = apply_decision(chosen, dry=dry)
    if not dry and (result.startswith("set") or result.startswith("unchanged")):
        remember_applied(signature)
    return result


def cmd_watch(args: argparse.Namespace) -> int:
    if args.once:
        print(_tick(args.dry))
        return 0
    while True:
        print(_tick(args.dry), flush=True)
        time.sleep(max(args.interval, 0.2))


def cmd_local(_args: argparse.Namespace) -> int:
    set_latch("local")
    saved = saved_arrangement()
    if saved:
        print(restore_command(saved))
    else:
        print("local pin set; no arrangement had been saved yet")
    print("viewers ignored until: nativedisplay auto")
    return 0


def cmd_auto(_args: argparse.Namespace) -> int:
    set_latch("auto")
    print("viewers followed again")
    return 0


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    digest.update(path.read_bytes())
    return digest.hexdigest()


def cmd_sentinel(_args: argparse.Namespace) -> int:
    root = _sentinel_root() / "overrides"
    if not root.is_dir():
        print("no sentinel copies; run nativedisplay setup first")
        return 0
    restored = 0
    for copy in sorted(root.iterdir()):
        if not copy.is_file() or "__" not in copy.name:
            continue
        vendor_dir, product = copy.name.split("__", 1)
        dest = Path("/Library/Displays/Contents/Resources/Overrides") / vendor_dir / product
        try:
            same = dest.is_file() and _sha(dest) == _sha(copy)
        except OSError:
            same = False
        if same:
            continue
        _install_bytes(dest, copy.read_bytes())
        restored += 1
        print(f"restored {dest}")
    if not restored:
        print("override files unchanged")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    print(f"nativedisplay {__version__}")
    print(f"latch: {latch()}")
    placer = find_displayplacer()
    print(f"displayplacer: {placer or 'missing'}")
    if not placer:
        print(missing_message())
    from nativedisplay.discover import tailscale_bin

    binary = tailscale_bin()
    print(f"tailscale: {binary or 'absent (other paths still classify viewers)'}")
    viewers = current_viewers()
    if viewers:
        for viewer in viewers:
            native = f"{viewer.native[0]}x{viewer.native[1]}" if viewer.native else "-"
            print(
                f"viewer: family={viewer.family or 'unknown'} host={viewer.hostname or '-'} "
                f"via={viewer.source} native={native}"
            )
    else:
        print("viewer: none")
    if sys_darwin():
        for display in detect_displays():
            path = override_path(display["vendor"], display["product"])
            mark = "installed" if path.exists() else "not installed"
            print(f"display: 0x{display['vendor']:x}/0x{display['product']:x} {mark}")
    else:
        print("display detect: run setup on the Mac")
    print(f"state: {state_dir()}")
    return 0


def cmd_reflow(args: argparse.Namespace) -> int:
    """Phone keyboard inset. Writes nothing unless the session is a live 768x1024 iPhone."""
    import json

    from nativedisplay.keyboard_reflow import Controller, geometry, render_agent

    if args.math:
        print(json.dumps(geometry(), sort_keys=True))
        return 0
    if args.install_agent:
        dest = Path(args.dest) if args.dest else Path.home() / "Library" / "Application Support" / "nativedisplay"
        dest.mkdir(parents=True, exist_ok=True)
        script = Path(__file__).resolve().parent / "keyboard_reflow.py"
        label = "com.hailports.nativedisplay.keyboard-reflow"
        text = render_agent(dest, script, dest / "session", label=label)
        target = dest / (label + ".plist")
        target.write_text(text, encoding="utf-8")
        print(json.dumps({"plist": str(target), "label": label, "loaded": False}))
        return 0
    controller = Controller()
    if args.dry:
        print(json.dumps(controller.once(dry_run=True), sort_keys=True))
        return 0
    if args.status:
        print(json.dumps(controller.status(), sort_keys=True))
        return 0
    result = controller.once(dry_run=False)
    if not result.get("ok") or result.get("moved") or result.get("restored"):
        print(json.dumps(result, sort_keys=True))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    commands = {
        "setup": cmd_setup,
        "status": cmd_status,
        "list": cmd_list,
        "apply": cmd_apply,
        "add": cmd_add,
        "watch": cmd_watch,
        "local": cmd_local,
        "restore": cmd_local,
        "auto": cmd_auto,
        "sentinel": cmd_sentinel,
        "reflow": cmd_reflow,
    }
    try:
        return commands[args.cmd](args)
    except subprocess.CalledProcessError as exc:
        print(f"command failed: {exc.cmd[0] if exc.cmd else 'setup'}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


# Imported so tests can build a hint without going through the live collectors.
_ = viewer_from_parts

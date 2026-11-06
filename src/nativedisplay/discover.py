"""Name a remote viewer without requiring Tailscale.

Proof that someone is viewing is an established Screen Sharing / VNC peer
(:5900, :5901, or the Apple Remote Desktop port :3283), a fresh Luna session,
or an explicit hint. The peer is classified from, in order:

  1. tailscale whois / status, only when the tailscale CLI is installed
  2. reverse DNS, mDNS via the system resolver, ARP / NDP hostnames
  3. a WxH carried in the hostname or hint text

An unnamed LAN or private peer is not guessed. An unnamed public peer is
treated as a tablet using the shared 4:3 fallback: that is how a Screens
Connect (or similar) relay presents itself, and it lets the host resize
with no client-side Native settings. Luna is also treated as a tablet.
"""

from __future__ import annotations

import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
from dataclasses import dataclass

# Tablets first. android / pixel / galaxy alone are not a phone: those
# names are shared with Android tablets.
TABLET_RX = re.compile(
    r"ipad|tablet|\btab\b|galaxy[-_ ]?tab|pixel[-_ ]?tab|android[-_ ]?tab|\bsm-x",
    re.I,
)
IPHONE_RX = re.compile(r"iphone|ipod|\bphone\b|android[-_ ]?phone", re.I)
MAC_RX = re.compile(
    r"macbook|imac|mac-?mini|mac-?pro|mac-?studio|\bmbp\b|\bmba\b|powerbook|\bmac\b",
    re.I,
)
SIZE_RX = re.compile(r"(\d{3,5})x(\d{3,5})", re.I)
SCREEN_PORTS = ("5900", "5901", "3283")
LUNA_PORTS = ("44554", "44555", "44556")


@dataclass(frozen=True)
class Viewer:
    family: str | None
    hostname: str | None
    address: str | None
    native: tuple[int, int] | None
    source: str


def classify_hostname(name: str | None) -> str | None:
    if not name:
        return None
    host = name.split(".")[0]
    if TABLET_RX.search(host):
        return "ipad"
    if IPHONE_RX.search(host):
        return "iphone"
    if MAC_RX.search(host):
        return "mac"
    return None


def native_in_text(text: str | None) -> tuple[int, int] | None:
    if not text:
        return None
    match = SIZE_RX.search(text)
    if not match:
        return None
    return int(match.group(1)), int(match.group(2))


def classify_whois(payload: dict | None) -> tuple[str | None, str | None]:
    """Read a tailscale whois JSON object. None means whois was not provided."""
    if not payload:
        return None, None
    node = payload.get("Node") or payload
    if not isinstance(node, dict):
        return None, None
    raw = node.get("HostName") or node.get("DNSName") or node.get("Name") or ""
    host = str(raw).split(".")[0] or None
    os_name = str(node.get("OS") or "").lower()
    family = classify_hostname(host)
    if family is None:
        if "ipados" in os_name:
            family = "ipad"
        elif "macos" in os_name or os_name == "mac":
            family = "mac"
        # Bare "ios" is an iPhone or an iPad. Bare "android" is a phone
        # or a tablet. Do not guess either.
    return family, host


def _nettop_remote_ip(remote: str) -> str:
    remote = (remote or "").strip()
    if remote.startswith("["):
        end = remote.find("]")
        if end > 0:
            return remote[1:end]
    if remote.count(":") == 1:
        return remote.rsplit(":", 1)[0]
    if "." in remote:
        host, _, port = remote.rpartition(".")
        if port.isdigit() and host.count(":") >= 2:
            return host
    if ":" in remote:
        host, _, port = remote.rpartition(":")
        if port.isdigit() and host.count(":") >= 2:
            return host
    return remote


def _is_loopback(ip: str) -> bool:
    return (not ip) or ip.startswith("127.") or ip in {"::1", "*", "0.0.0.0"}


def parse_nettop(text: str) -> list[str]:
    """Established screen-share peers from `nettop -m tcp -n -x`."""
    found: list[str] = []
    for line in (text or "").splitlines():
        if not any(f"{port}<->" in line for port in SCREEN_PORTS):
            continue
        if "Established" not in line:
            continue
        token = next((part for part in line.split() if "<->" in part), None)
        if not token:
            continue
        local, _, remote = token.partition("<->")
        if not any(local.endswith(f":{port}") or local.endswith(f".{port}") for port in SCREEN_PORTS):
            continue
        if remote in {"*.*", "*:*", "*", ""}:
            continue
        ip = _nettop_remote_ip(remote)
        if _is_loopback(ip) or ip in found:
            continue
        found.append(ip)
    return found


def _local_port(local: str) -> str | None:
    if local.endswith(tuple(f".{port}" for port in SCREEN_PORTS)) or local.endswith(
        tuple(f":{port}" for port in SCREEN_PORTS)
    ):
        return local.rsplit(".", 1)[-1].rsplit(":", 1)[-1]
    return None


def parse_netstat(text: str) -> list[str]:
    """Established screen-share peers from `netstat -an -p tcp`."""
    found: list[str] = []
    for line in (text or "").splitlines():
        if "ESTABLISHED" not in line:
            continue
        parts = line.split()
        if len(parts) < 5 or not parts[0].startswith("tcp"):
            continue
        local, remote = parts[3], parts[4]
        if _local_port(local) not in SCREEN_PORTS:
            continue
        if ":" in remote and remote.count(":") == 1:
            ip = remote.rsplit(":", 1)[0]
        else:
            ip = remote.rsplit(".", 1)[0]
        if _is_loopback(ip) or ip in found:
            continue
        found.append(ip)
    return found


def parse_lsof(text: str) -> list[str]:
    """Established peers from `lsof -nP -iTCP -sTCP:ESTABLISHED`."""
    found: list[str] = []
    for line in (text or "").splitlines():
        if "ESTABLISHED" not in line:
            continue
        for port in SCREEN_PORTS:
            marker = f":{port}->"
            if marker not in line:
                continue
            remote = line.split(marker, 1)[1].split()[0]
            ip = remote.rsplit(":", 1)[0].strip("[]")
            if _is_loopback(ip) or ip in found:
                continue
            found.append(ip)
    return found


def parse_luna_log(text: str) -> bool:
    for line in reversed((text or "").splitlines()):
        if "Server is alive with state:" in line:
            return "Active Services" in line
    return False


def parse_luna_netstat(text: str) -> bool:
    for line in (text or "").splitlines():
        if "ESTABLISHED" not in line:
            continue
        parts = line.split()
        if len(parts) < 5 or not parts[0].startswith("tcp"):
            continue
        local, remote = parts[3], parts[4]
        port = local.rsplit(".", 1)[-1].rsplit(":", 1)[-1]
        if port not in LUNA_PORTS:
            continue
        ip = remote.rsplit(".", 1)[0] if ":" not in remote else remote.rsplit(":", 1)[0]
        if not _is_loopback(ip):
            return True
    return False


def parse_arp(text: str) -> dict[str, str]:
    """Map address -> hostname from `arp -a` / `ndp -an` lines that include a name."""
    found: dict[str, str] = {}
    for line in (text or "").splitlines():
        # name (a.b.c.d) at ...
        match = re.match(r"\s*(\S+)\s+\(([^)]+)\)", line)
        if not match:
            continue
        name, ip = match.group(1), match.group(2)
        if name in {"?", "(incomplete)"} or name.startswith("("):
            continue
        if not classify_hostname(name) and not native_in_text(name):
            # Keep the name anyway; the classifier decides.
            pass
        found[ip] = name.split(".")[0]
    return found


def tailscale_bin() -> str | None:
    env = os.environ.get("TAILSCALE")
    candidates = [
        env,
        shutil.which("tailscale"),
        "/opt/homebrew/bin/tailscale",
        "/usr/local/bin/tailscale",
        "/Applications/Tailscale.app/Contents/MacOS/Tailscale",
    ]
    for path in candidates:
        if path and os.path.isfile(path) and os.access(path, os.X_OK):
            return path
    return None


def _run(cmd: list[str], timeout: float = 4) -> str:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return ""
    if proc.returncode != 0:
        return ""
    return proc.stdout


def tailscale_whois(ip: str, binary: str | None = None) -> dict | None:
    """whois one peer. Returns None when tailscale is absent or the lookup fails."""
    binary = binary if binary is not None else tailscale_bin()
    if not binary:
        return None
    cmd = [binary]
    if os.path.exists("/var/run/tailscaled.socket"):
        cmd.extend(["--socket", "/var/run/tailscaled.socket"])
    cmd.extend(["whois", "--json", ip])
    raw = _run(cmd, timeout=4)
    if not raw.strip():
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    node = payload.get("Node") if isinstance(payload.get("Node"), dict) else payload
    # Drop account fields before anything else sees the payload.
    return {
        "Node": {
            "HostName": node.get("HostName"),
            "DNSName": node.get("DNSName"),
            "Name": node.get("Name"),
            "OS": node.get("OS"),
        }
    }


def tailscale_status_names(binary: str | None = None) -> dict[str, str]:
    binary = binary if binary is not None else tailscale_bin()
    if not binary:
        return {}
    raw = _run([binary, "status", "--json"], timeout=4)
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    names: dict[str, str] = {}
    peers = list((payload.get("Peer") or {}).values())
    self_node = payload.get("Self") or {}
    if self_node:
        peers.append(self_node)
    for peer in peers:
        if not isinstance(peer, dict):
            continue
        name = str(peer.get("DNSName") or peer.get("HostName") or "").split(".")[0]
        if not name:
            continue
        for addr in peer.get("TailscaleIPs") or []:
            names[str(addr)] = name
    return names


def reverse_name(ip: str) -> str | None:
    try:
        host, _aliases, _addrs = socket.gethostbyaddr(ip)
    except (OSError, socket.herror, socket.gaierror):
        return None
    host = (host or "").rstrip(".")
    if not host or host == ip:
        return None
    return host.split(".")[0]


def identify_peers(
    addresses: list[str],
    *,
    dns,
    arp_names: dict[str, str] | None = None,
    status_names: dict[str, str] | None = None,
    whois=None,
) -> list[Viewer]:
    """Classify peers. `whois` is called only when the caller passes a callable."""
    arp_names = arp_names or {}
    status_names = status_names or {}
    viewers: list[Viewer] = []
    for ip in addresses:
        payload = whois(ip) if whois else None
        family, host = classify_whois(payload)
        source = "tailscale" if payload else ""
        if not host:
            host = status_names.get(ip)
            if host and not source:
                source = "tailscale"
                family = family or classify_hostname(host)
        if not host and dns:
            host = dns(ip)
            if host and not source:
                source = "dns"
                family = family or classify_hostname(host)
        if not host and ip in arp_names:
            host = arp_names[ip]
            source = source or "arp"
            family = family or classify_hostname(host)
        native = native_in_text(host)
        viewers.append(Viewer(family, host, ip, native, source or "peer"))
    return viewers


def viewer_from_parts(
    *,
    hostname: str | None = None,
    whois: dict | None = None,
    native: tuple[int, int] | None = None,
    source: str = "hint",
    address: str | None = None,
) -> Viewer:
    family, host = classify_whois(whois)
    host = hostname or host
    family = classify_hostname(host) or family
    native = native or native_in_text(host)
    used = source
    if whois and source == "hint":
        used = "tailscale"
    return Viewer(family, host, address, native, used)


def collect_peer_ips() -> list[str]:
    """Live screen-share peers. Empty on a machine with no such sockets."""
    netstat = shutil.which("netstat") or "/usr/sbin/netstat"
    text = _run([netstat, "-an", "-p", "tcp"], timeout=5) if os.path.exists(netstat) else ""
    if "ESTABLISHED" not in text:
        text = _run([netstat, "-an"], timeout=5) if os.path.exists(netstat) else text
    ips = parse_netstat(text)
    if ips:
        return ips
    nettop = "/usr/bin/nettop"
    if os.path.exists(nettop):
        top = _run([nettop, "-m", "tcp", "-l", "1", "-n", "-x", "-d", "0"], timeout=6)
        ips = parse_nettop(top)
        if ips:
            return ips
    lsof = shutil.which("lsof") or "/usr/sbin/lsof"
    if os.path.exists(lsof):
        listed = _run([lsof, "-nP", "-iTCP", "-sTCP:ESTABLISHED"], timeout=6)
        return parse_lsof(listed)
    return []


def luna_active() -> bool:
    from pathlib import Path

    log = Path.home() / "Library/Logs/luna-display-keepalive.log"
    try:
        age = __import__("time").time() - log.stat().st_mtime
    except OSError:
        age = None
    if age is not None and age <= 60:
        try:
            if parse_luna_log(log.read_text(errors="replace")[-8000:]):
                return True
        except OSError:
            pass
    netstat = shutil.which("netstat") or "/usr/sbin/netstat"
    if os.path.exists(netstat):
        return parse_luna_netstat(_run([netstat, "-an"], timeout=5))
    return False


def is_relay_address(ip: str) -> bool:
    """True for a globally routed peer. LAN, loopback, link-local, and
    shared (CGNAT / typical overlay) addresses stay unclassified.
    """
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return bool(addr.is_global)


def apply_relay_fallback(viewers: list[Viewer]) -> list[Viewer]:
    """Name an otherwise unclassifiable public screen-share peer as iPad.

    A Screens Connect (or similar) relay presents a public address we
    cannot reverse-name. The working host adapter treats that session as
    an iPad so the canvas still resizes with no client-side settings.
    Named peers and private addresses are left alone.
    """
    upgraded: list[Viewer] = []
    for viewer in viewers:
        if viewer.family is None and viewer.address and is_relay_address(viewer.address):
            upgraded.append(
                Viewer("ipad", viewer.hostname, viewer.address, viewer.native, "relay")
            )
        else:
            upgraded.append(viewer)
    return upgraded


def current_viewers() -> list[Viewer]:
    """Observers for one tick. Tailscale is consulted only when its CLI exists."""
    binary = tailscale_bin()
    whois = (lambda ip: tailscale_whois(ip, binary)) if binary else None
    status = tailscale_status_names(binary) if binary else {}
    arp_text = ""
    arp = shutil.which("arp")
    if arp:
        arp_text += _run([arp, "-a"], timeout=3)
    ndp = shutil.which("ndp")
    if ndp:
        arp_text += "\n" + _run([ndp, "-an"], timeout=3)
    viewers = apply_relay_fallback(
        identify_peers(
            collect_peer_ips(),
            dns=reverse_name,
            arp_names=parse_arp(arp_text),
            status_names=status,
            whois=whois,
        )
    )
    if luna_active():
        viewers.append(Viewer("ipad", None, None, None, "luna"))
    return viewers

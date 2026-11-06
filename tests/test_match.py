from nativedisplay.discover import (
    Viewer,
    apply_relay_fallback,
    classify_hostname,
    classify_whois,
    identify_peers,
    is_relay_address,
    parse_arp,
    parse_luna_log,
    parse_luna_netstat,
    parse_netstat,
    parse_nettop,
)
from nativedisplay.match import decide, pick_mode


def quad(*parts: int) -> str:
    return ".".join(str(part) for part in parts)


def test_hostname_families_select_native_modes():
    assert classify_hostname("ipad") == "ipad"
    assert classify_hostname("Office-iPhone") == "iphone"
    assert classify_hostname("MacBook-Pro") == "mac"
    assert classify_hostname("printer") is None

    ipad = decide(["ipad"])
    assert (ipad.w, ipad.h, ipad.hidpi, ipad.degree) == (1344, 1008, True, 0)
    phone = decide(["iphone"])
    assert (phone.w, phone.h, phone.hidpi, phone.degree) == (1024, 768, True, 90)
    mac = decide(["mac"])
    assert (mac.w, mac.h, mac.hidpi, mac.degree) == (1680, 1050, True, 0)
    assert decide([]) is None
    assert decide(["ipad"], latch="local") is None


def test_unknown_peer_does_not_change_and_whois_is_optional():
    called = []

    def whois(ip):
        called.append(ip)
        return {"Node": {"HostName": "ipad", "OS": "iOS"}}

    peer = quad(203, 0, 113, 9)
    quiet = identify_peers([peer], dns=lambda _ip: "printer", whois=None)
    assert called == []
    assert quiet[0].family is None
    assert decide([item.family for item in quiet if item.family]) is None

    named = identify_peers([peer], dns=lambda _ip: None, whois=whois)
    assert called == [peer]
    assert named[0].family == "ipad"
    assert named[0].source == "tailscale"


def test_whois_os_without_guessing_bare_ios():
    family, host = classify_whois({"Node": {"HostName": "office", "OS": "macOS"}})
    assert family == "mac"
    assert host == "office"
    family, _host = classify_whois({"Node": {"HostName": "office", "OS": "iOS"}})
    assert family is None
    family, _host = classify_whois({"Node": {"HostName": "ipad", "OS": "iOS"}})
    assert family == "ipad"
    assert classify_whois(None) == (None, None)


def test_pick_mode_prefers_exact_then_nearest_same_aspect():
    both = [(1344, 1008, True), (1680, 1050, True), (1376, 1032, True), (1920, 1080, True)]
    chosen = decide(["ipad"], advertised=both)
    assert (chosen.w, chosen.h, chosen.verified) == (1344, 1008, True)
    nearest = decide(["ipad"], advertised=[(1344, 1008, True), (1680, 1050, True)])
    assert (nearest.w, nearest.h) == (1344, 1008)
    laptop = decide(["mac"], advertised=[(1440, 900, True), (1920, 1080, True)])
    assert (laptop.w, laptop.h) == (1440, 900)
    phone = decide(["iphone"], advertised=[(800, 600, True), (1920, 1080, False)])
    assert (phone.w, phone.h, phone.degree) == (800, 600, 90)
    assert decide(["ipad"], advertised=[(1920, 1080, True)]) is None
    pixels = decide(
        ["ipad"],
        natives={"ipad": (2752, 2064)},
        advertised=[(1376, 1032, True), (1344, 1008, True)],
    )
    assert (pixels.w, pixels.h) == (1344, 1008)
    scored = pick_mode(1376, 1032, True, [(1344, 1008, False), (1344, 1008, True)])
    assert scored == (1344, 1008, True)


def test_socket_and_luna_parsers():
    host = quad(10, 1, 2, 3)
    peer = quad(203, 0, 113, 9)
    loop = quad(127, 0, 0, 1)
    netstat = f"tcp4 0 0 {host}.5900 {peer}.40000 ESTABLISHED\n"
    netstat += f"tcp4 0 0 {host}.5900 {loop}.40001 ESTABLISHED\n"
    netstat += f"tcp4 0 0 {host}.22 {peer}.40002 ESTABLISHED\n"
    assert parse_netstat(netstat) == [peer]
    nettop = f"tcp4 1 2 {host}:5900<->{peer}:50000 Established\n"
    nettop += f"tcp4 0 0 {host}:5900<->*:* Listen\n"
    assert parse_nettop(nettop) == [peer]
    assert parse_luna_log("noise\nServer is alive with state: Active Services\n")
    assert not parse_luna_log("Server is alive with state: Idle\n")
    luna = f"tcp4 0 0 {host}.44554 {peer}.9 ESTABLISHED\n"
    assert parse_luna_netstat(luna)
    arp = parse_arp(f"ipad ({peer}) at aa on en0\n? ({host}) at bb on en0\n")
    assert arp[peer] == "ipad"
    assert host not in arp


def test_public_unnamed_peer_is_ipad_relay():
    assert is_relay_address("8.8.8.8")
    assert not is_relay_address("192.168.1.20")
    assert not is_relay_address("10.0.0.8")
    assert not is_relay_address("100.64.1.20")
    assert not is_relay_address("127.0.0.1")
    assert not is_relay_address("not-an-ip")

    public = Viewer(None, "relay-node", "8.8.8.8", None, "peer")
    private = Viewer(None, "printer", "192.168.1.20", None, "peer")
    overlay = Viewer(None, None, "100.64.1.20", None, "peer")
    named = Viewer("iphone", "Office-iPhone", "8.8.8.8", None, "dns")
    out = apply_relay_fallback([public, private, overlay, named])
    assert (out[0].family, out[0].source) == ("ipad", "relay")
    assert out[1].family is None and out[1].source == "peer"
    assert out[2].family is None
    assert (out[3].family, out[3].source) == ("iphone", "dns")
    assert decide([item.family for item in out if item.family]).family == "iphone"


# Changelog

## Native 1.0 — 2026-11-06

First public release.

- Host-side auto resize to the viewer's logical size, with no extra client settings.
- Any tablet, not iPad-only. Names with ipad, tablet, or tab (including Galaxy-Tab, Pixel-Tablet, and SM-X) classify as a tablet.
- When the Mac can see a reported tablet size, Native matches that canvas. A reported 2752x2064 becomes 1376x1032. A reported 2560x1600 becomes 1280x800. Otherwise the shared 4:3 fallback is 1344x1008.
- iPhone portrait at 1024x768 HiDPI rotated 90 (768x1024), plus the keyboard inset. Phones are the only viewers that rotate.
- A bare android, pixel, or galaxy name does not auto-resize.
- Tailscale is optional. Reverse DNS, mDNS, and ARP/NDP still classify viewers.
- An unnamed public relay uses the tablet fallback, so a Screens Connect-style session still resizes. An unnamed LAN or private address is left unchanged.
- The command is `native`. `nativedisplay` is an alias.
- Self-guided CLI setup: run `./install.sh`, then `native setup`.

`native setup` writes the scale-resolutions override. It does not restart WindowServer. New modes load on the next logout, display unplug/replug, or wake.

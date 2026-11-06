# Native

Native display resizing and desktop reduction for remote devices.

The command is `native`. `nativedisplay` is installed as an alias.

When an iPad, iPhone, or Mac is viewing this Mac, `native` sets the host display to that client's native logical size. Detection runs entirely on the Mac: any VNC-compatible viewer that connects to the built-in screen sharing ports is seen without extra client settings. That includes Apple Screen Sharing, Screens, built-in VNC, RealVNC, TightVNC, TigerVNC, and Jump Desktop in VNC mode. Luna is detected on its own. A VPN or overlay network is optional and only helps name the device. HiDPI is used when the panel advertises it. The same modes are unlocked on a built-in LCD and on a dummy HDMI panel.

## Install

```sh
brew install displayplacer
git clone https://github.com/hailports/Native.git
cd Native
./install.sh
```

`install.sh` uses `pipx install .` when pipx is present, and `pip install --user .` otherwise.

`displayplacer` applies the mode. Install it with Homebrew. Native does not bundle it.

A Homebrew formula is in `Formula/nativedisplay.rb` (HEAD only, depends on `displayplacer` and `python@3.12`):

```sh
brew install --HEAD --formula ./Formula/native.rb
```

Tailscale is not required. If the `tailscale` command is installed, peer names from `tailscale whois` and `tailscale status` are used. If it is absent, Screen Sharing sockets, reverse DNS, mDNS, ARP/NDP, and Luna still classify the viewer.

## Setup, once per display

```sh
native setup
```

That asks for sudo one time. It reads the attached display's vendor and product from `ioreg`, writes a `scale-resolutions` override, and backs up any previous file. The override is installed at:

```
/Library/Displays/Contents/Resources/Overrides/DisplayVendorID-<hex>/DisplayProductID-<hex>
```

Each logical `WxH` is stored as three records: the 1x size (flag 1), the 2x framebuffer (flag 9, tail `0x200000`), and the bare 2x pair. That is what makes macOS treat the size as a native HiDPI mode. Sizes already stored in Apple's shorter 9-byte or 12-byte form are kept when they are not already in the catalog. Other keys in an existing override, including the EDID, are kept.

`setup` does not restart WindowServer. New modes load on the next logout, display unplug/replug, or wake. Do that once on each Mac after setup. Until then, `apply` only selects a mode the panel already advertises.

`nativedisplay sentinel` puts the file back if something deletes it. It does not change the live resolution. `nativedisplay add 1210x834` records another client size with the same encoding and merges it on the next setup (or immediately, when a display is detected).

## How a viewer is chosen

`native apply` and `native watch` look for an established Screen Sharing or VNC peer on ports 5900, 5901, and 3283 (`netstat`, then `nettop`, then `lsof`). Any VNC-compatible client that connects to those host ports is seen; the client does not need Native installed or extra settings. A fresh Luna "Active Services" line, or Luna's own TCP ports, counts as an iPad. An unnamed public peer on those ports is also treated as an iPad, which covers a Screens Connect (or similar) relay that hides the real device name.

The peer name is resolved in this order:

1. `tailscale whois`, then `tailscale status`, only when the `tailscale` CLI is on the machine. Account fields from whois are not kept.
2. Reverse DNS / the system resolver (mDNS names that the resolver already knows).
3. Hostnames in `arp -a` and `ndp -an`.

A name containing `ipad` is an iPad. `iphone`, `ipod`, `android`, `pixel`, `galaxy`, or `phone` is a phone. `macbook`, `imac`, `mac mini`, `mac pro`, `mac studio`, or `mac` is a 16:10 laptop. `tailscale whois` can also classify `macOS`, `iPadOS`, and `android` when the hostname itself is generic. A bare `iOS` result is not guessed, because it is either an iPhone or an iPad.

If several viewers match, the phone wins, then the iPad, then the Mac.

| Viewer | Mode |
| --- | --- |
| iPad | Landscape only: 1344x1008 HiDPI, unrotated. There is no iPad portrait mode. If 1344x1008 is not advertised yet, the nearest 4:3 HiDPI mode is used. 1376x1032 stays in the catalog as an unlocked size (`native apply 1376x1032`). |
| iPhone or other phone | Portrait: 1024x768 HiDPI, rotated 90 (focused display 768x1024), plus the keyboard inset below that 3:4 canvas. If that mode is missing, the nearest 4:3 HiDPI mode, such as 800x600, still rotated. This is the only client that uses rotation. |
| Mac laptop | 1680x1050 HiDPI. If that mode is missing, the nearest 16:10 HiDPI mode, such as 1440x900. |

A `WxH` in the hostname is the client's pixel size. Even sizes at or above 2000x1500 are treated as a 2x framebuffer and halved before matching. Matching keeps the aspect ratio, prefers the exact size, then the nearest area, and prefers HiDPI. A different aspect is not applied.

If the peer cannot be classified, the display is left as it is. Unnamed LAN or private addresses are not guessed.

`nativedisplay local` (and `restore`) pins the desktop and replays the arrangement saved before the first remote change. `nativedisplay auto` follows viewers again. `watch` is a poll (default 2 seconds). It skips a tick when the choice is unchanged, when no viewer is classified, or when the mode list cannot be read.

## Commands

```sh
native setup
native status
native list
native apply                 # current viewer
native apply 1680x1050
native apply --ipad
native apply --iphone
native apply --16x10
native apply --16x9
native add 1210x834
native watch
native local                 # desktop wins
native auto
native sentinel
native reflow --math
native reflow --dry
native reflow --install-agent
```

`--dry` on `setup`, `apply`, `add`, `watch`, and `reflow` prints the action and does not change the display or install the override.

## iPhone keyboard inset

After the desktop is the phone's portrait canvas (1024x768 HiDPI, rotated 90, so the focused display is 768x1024 points), `nativedisplay reflow` keeps windows above the on-screen keyboard.

It runs only when a fresh session file says `mobile_connected=1` and `mobile_profile=iphone`, and the focused display is 768x1024. The measured window bottom is y=761. The keyboard row begins near y=852 (91 points of room). Usable bottom was 963, so the global bottom padding is 202. That padding is global, not per space. The previous global value is saved and put back on the next positively identified non-phone session. Floating windows this tool moved are clamped to y<=761 and restored later. Anyone else is left alone.

Missing, stale (older than 45 seconds), malformed, or future-dated state does nothing. If the window manager that applies the padding is missing, reflow does nothing. `reflow` with no flags is one tick. `--dry` prints the math and does not set padding. `--install-agent` writes a plist and does not load it.

`native list` prints every unlocked logical resolution. The catalog is the usual scaled set across 16:10, 16:9, and 4:3, plus 1344x1008, 1376x1032, 1344x840, and the other iPad Pro logical sizes. Odd scaled sizes that macOS already builds for one specific LCD stay as they are; this tool adds modes, it does not remove the panel's own list.

If another program is already changing the resolution, do not run `native watch` at the same time. `setup` only writes the override file.

## Tests

```sh
python3 -m pytest
```

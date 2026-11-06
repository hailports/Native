#!/bin/sh
# Install Native for the current user. Setup runs later, on the Mac, and is the step that asks for sudo.
set -eu
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required and was not found." >&2
  echo "Install Python 3, then run ./install.sh again." >&2
  echo "On a Mac: xcode-select --install" >&2
  echo "Or install Python from https://www.python.org/downloads/" >&2
  exit 1
fi

if command -v pipx >/dev/null 2>&1; then
  pipx install --force .
else
  python3 -m pip install --user .
  echo "If native is not on PATH, add the user script directory that pip just printed."
  echo "That directory is often ~/Library/Python/*/bin or ~/.local/bin."
  echo "Example: export PATH=\"\$HOME/.local/bin:\$PATH\""
fi

if command -v displayplacer >/dev/null 2>&1 \
  || [ -x /opt/homebrew/bin/displayplacer ] \
  || [ -x /usr/local/bin/displayplacer ]; then
  echo "displayplacer: found"
else
  echo "displayplacer is not installed."
  echo "Next step for that tool: brew install displayplacer"
fi

echo "Next steps:"
echo "  1. native setup"
echo "  2. Log out, unplug and replug the display, or wake from sleep so the new modes load."
echo "  3. native status"
echo "  4. Optional: native watch"

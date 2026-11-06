#!/bin/sh
# Install nativedisplay for the current user. One sudo happens later, on setup.
set -eu
cd "$(dirname "$0")"

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if command -v pipx >/dev/null 2>&1; then
  pipx install --force .
else
  python3 -m pip install --user .
  echo "If nativedisplay is not on PATH, add the user script directory that pip just printed."
fi

if command -v displayplacer >/dev/null 2>&1 \
  || [ -x /opt/homebrew/bin/displayplacer ] \
  || [ -x /usr/local/bin/displayplacer ]; then
  echo "displayplacer: found"
else
  echo "displayplacer is not installed. On the Mac: brew install displayplacer"
fi

echo "Next, on the Mac: nativedisplay setup"
echo "Then log out, replug the display, or wake from sleep so the new modes load."

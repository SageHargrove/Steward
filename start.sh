#!/usr/bin/env bash
# Steward, on Linux and macOS.
#
# The Windows equivalent is START.bat. Everything below this launcher is plain
# Python and works the same on either: the two places the operating systems
# differ, detaching the bot and stopping it, are handled in ui/app.py.

set -euo pipefail
cd "$(dirname "$0")/ui"

echo
echo "  Steward"
echo "  ======="
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "  Python 3 is not installed, or is not on PATH."
  echo "  Install it from your package manager or python.org, then run this again."
  echo
  exit 1
fi

echo "  Checking the bits it needs..."
python3 -m pip install --disable-pip-version-check -q -r requirements.txt

echo "  Done."
echo
echo "  ------------------------------------------------------------------"
echo "   KEEP THIS TERMINAL OPEN while you use the setup page."
echo "   Your bot token lives in this process's memory and nowhere else,"
echo "   so closing it forgets the token. Nothing already built is affected."
echo "  ------------------------------------------------------------------"
echo

exec python3 app.py

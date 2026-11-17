#!/bin/bash
# Install OKR Drum from source on a Mac (alternative to the .pkg). Double-click in Finder.
# Needs Python 3.10-3.13 (python.org installer or Homebrew).
cd "$(dirname "$0")" || exit 1
PY="$(command -v python3)"
[ -z "$PY" ] && { echo "Python 3 not found - install it from python.org first."; read -r -p "Press Enter"; exit 1; }
"$PY" -m venv .venv && source .venv/bin/activate && python -m pip install --upgrade pip && pip install -r requirements.txt \
  && echo && echo "Installed. Start OKR Drum with run_mac.command" || echo "Installation failed - see above."
read -r -p "Press Enter to close"

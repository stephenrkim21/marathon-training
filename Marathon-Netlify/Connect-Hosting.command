#!/bin/bash
set -e
cd "$(dirname "$0")"
PYTHON=""
for candidate in /Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12 /opt/homebrew/bin/python3.12 /usr/local/bin/python3.12; do
  if [ -x "$candidate" ]; then PYTHON="$candidate"; break; fi
done
if [ -z "$PYTHON" ]; then PYTHON="$(command -v python3.12 || true)"; fi
if [ -z "$PYTHON" ]; then echo 'Python 3.12 is required. Use the Mac where your Garmin app already works.'; read -r -p 'Press Return to close.'; exit 1; fi
"$PYTHON" -m venv .hosting-venv
.hosting-venv/bin/python -m pip install --disable-pip-version-check --quiet -r austin-plan/requirements.hosted.txt
.hosting-venv/bin/python tools/connect_hosting.py
read -r -p 'Press Return to close.'

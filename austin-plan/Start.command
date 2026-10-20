#!/bin/bash
# Repair this app locally. No files or credentials are uploaded anywhere.
set -Eeuo pipefail
umask 077

finish_error() {
  printf '\nSetup stopped at line %s. Your saved data has not been deleted.\n' "$1"
  printf 'Send the error above to the chat. Do not share passwords or verification codes.\n'
  read -r -p 'Press Return to close. ' _ || true
}
trap 'finish_error "$LINENO"' ERR

printf '\nSTEPHEN — ROAD TO 3:40\nLaunch your private training app\n\n'

PROJECT=''
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
for candidate in \
  "$SCRIPT_DIR/austin-plan" \
  "$SCRIPT_DIR" \
  "$HOME/Documents/Codex/2026-10-20/austin-plan" \
  "$HOME/Downloads/austin-plan"; do
  if [[ -f "$candidate/server/app.py" && -f "$candidate/server/core.py" && -f "$candidate/public/plan.json" ]]; then
    PROJECT="$candidate"
    break
  fi
done
if [[ -z "$PROJECT" ]]; then
  printf 'Could not find the complete austin-plan project.\nMove this launcher next to the austin-plan folder, then open it again.\n'
  exit 1
fi
cd -- "$PROJECT"
printf 'Project: %s\n' "$PROJECT"

PYTHON_BIN=''
for candidate in \
  '/Library/Frameworks/Python.framework/Versions/3.12/bin/python3.12' \
  '/opt/homebrew/bin/python3.12' \
  '/usr/local/bin/python3.12'; do
  if [[ -x "$candidate" ]]; then PYTHON_BIN="$candidate"; break; fi
done
if [[ -z "$PYTHON_BIN" ]]; then PYTHON_BIN="$(command -v python3.12 || true)"; fi
if [[ -z "$PYTHON_BIN" ]]; then
  printf 'Python 3.12 is not installed or could not be found. Install it, then run this launcher again.\n'
  exit 1
fi
"$PYTHON_BIN" -c 'import sys; assert sys.version_info[:2] == (3,12); print("Python", sys.version.split()[0])'

printf '\n1. Applying the login fix...\n'
"$PYTHON_BIN" - <<'PY'
from datetime import datetime
from pathlib import Path
import shutil
p = Path('server/app.py')
s = p.read_text()
old = "('Referrer-Policy','no-referrer')"
new = "('Referrer-Policy','same-origin')"
if old in s:
    fixed = s.replace(old, new)
    compile(fixed, str(p), 'exec')
    backup = p.with_name('app.py.before-login-fix-' + datetime.now().strftime('%Y%m%d-%H%M%S-%f'))
    shutil.copy2(p, backup)
    p.write_text(fixed)
    print('Fixed the privacy header; the original app.py was backed up.')
elif new in s:
    compile(s, str(p), 'exec')
    print('The login header is already fixed.')
else:
    raise SystemExit('This app.py differs from the supplied version. Stopped without changing it.')
if "env.get('HTTP_ORIGIN')!=origin" not in p.read_text():
    raise SystemExit('Origin validation differs from the expected app. Stopped for review.')
print('Origin validation remains enabled. Saved passwords and Garmin tokens were not changed.')
PY

printf '\n2. Checking the Python environment...\n'
if [[ -x .venv/bin/python ]] && .venv/bin/python -c 'import sys; assert sys.version_info[:2] == (3,12)' >/dev/null 2>&1; then
  printf 'Existing Python 3.12 environment is usable.\n'
else
  if [[ -e .venv ]]; then
    mv -- .venv ".venv-before-repair-$(date +%Y%m%d-%H%M%S)-$$"
  fi
  "$PYTHON_BIN" -m venv .venv
fi
if ! .venv/bin/python -c 'from garminconnect import Garmin' >/dev/null 2>&1; then
  printf 'Installing the project dependencies...\n'
  .venv/bin/python -m pip install --upgrade pip
  .venv/bin/python -m pip install -r requirements.txt
else
  printf 'Garmin library is installed.\n'
fi
export PYTHONPYCACHEPREFIX="$PROJECT/.pycache"
unset APP_ORIGIN ADMIN_PASSWORD_HASH DATA_DIR
export SYNC_ENABLED=1

printf '\n3. Checking saved setup...\n'
HAS_PASSWORD="$(.venv/bin/python -c 'from server.core import Store; print("yes" if Store().meta("password_hash") else "no")')"
if [[ "$HAS_PASSWORD" != yes ]]; then
  printf 'No saved app password in this project. Create one below; it is separate from Garmin.\n'
  .venv/bin/python -m server.setup password
else
  printf 'Your saved app password will be used.\n'
fi
HAS_TOKENS="$(.venv/bin/python -c 'from pathlib import Path; p=Path("data/garmin"); print("yes" if p.is_dir() and any(f.is_file() for f in p.rglob("*")) else "no")')"
if [[ "$HAS_TOKENS" != yes ]]; then
  printf 'No Garmin session in this project. Sign in below; password typing will stay invisible.\n'
  .venv/bin/python -m server.setup garmin
else
  printf 'Your saved Garmin session will be used.\n'
fi

printf '\n4. Checking for an older app instance...\n'
PIDS="$(lsof -nP -t -iTCP:8765 -sTCP:LISTEN 2>/dev/null || true)"
for pid in $PIDS; do
  PROCESS_CMD="$(ps -p "$pid" -o command= || true)"
  PROCESS_USER="$(ps -p "$pid" -o user= | tr -d ' ' || true)"
  PROCESS_DIR="$(lsof -a -p "$pid" -d cwd -Fn 2>/dev/null | sed -n 's/^n//p' || true)"
  if [[ "$PROCESS_USER" == "$(id -un)" && "$PROCESS_CMD" == *"-m server.app"* ]] && \
     [[ "$PROCESS_DIR" == "$PROJECT" || "$PROCESS_DIR" == "$HOME/Downloads/austin-plan" || "$PROCESS_DIR" == "$HOME/Documents/Codex/2026-10-20/austin-plan" ]]; then
    printf 'Stopping the older marathon app (process %s).\n' "$pid"
    kill -TERM "$pid"
  else
    printf 'Port 8765 belongs to a different or unrecognized process. It was not stopped.\n'
    printf 'Close that service and reopen this launcher.\n'
    exit 1
  fi
done
for attempt in {1..20}; do
  if ! lsof -nP -t -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then break; fi
  sleep 0.25
done
if lsof -nP -t -iTCP:8765 -sTCP:LISTEN >/dev/null 2>&1; then
  printf 'The older process has not released port 8765. Stopped without forcing it.\n'
  exit 1
fi

printf '\n5. Starting your private app...\n'
.venv/bin/python -u -m server.app &
SERVER_PID=$!
cleanup() { kill -TERM "$SERVER_PID" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM
READY=0
for attempt in {1..40}; do
  if ! kill -0 "$SERVER_PID" 2>/dev/null; then
    printf 'The server stopped. See the error above.\n'
    exit 1
  fi
  if curl --noproxy '*' --silent --fail --max-time 1 http://127.0.0.1:8765/health >/dev/null; then READY=1; break; fi
  sleep 0.25
done
if [[ "$READY" != 1 ]]; then printf 'Server did not become ready. See the error above.\n'; exit 1; fi
HEADER="$(curl --noproxy '*' --silent --fail --max-time 3 --head http://127.0.0.1:8765/login)"
if ! printf '%s\n' "$HEADER" | tr -d '\r' | grep -Eiq '^Referrer-Policy: same-origin$'; then
  printf 'The running server did not return the fixed login header. Stopped for review.\n'
  exit 1
fi
printf '\nREADY — login header verified on the running server.\n'
printf 'Sign in with your APP password in the browser.\n'
printf 'Keep this window open. Press Control+C here to stop the app.\n'
printf 'This runs locally only. No hosting was purchased or configured.\n\n'
open http://127.0.0.1:8765/login
wait "$SERVER_PID"

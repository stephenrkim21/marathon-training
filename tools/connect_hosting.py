#!/usr/bin/env python3
"""Mac-only interactive configuration. Secrets go to the clipboard, never chat or source."""
import base64
import getpass
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tempfile
from urllib.parse import urlsplit

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'austin-plan'))
from server.core import Store, password_hash
from server.adaptive import Planner
from server.hosted_worker import seal, pack, remote, dashboard


def copy_value(label,value):
    subprocess.run(['pbcopy'],input=value.encode(),check=True)
    input(f'Copied {label} to your clipboard. Paste it into the indicated secret value, save, then press Return here. ')


def main():
    if sys.platform!='darwin' or not sys.stdin.isatty():raise ValueError('Run this interactively in Terminal on your Mac.')
    origin=input('Your production Netlify address (https://name.netlify.app): ').strip().rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:raise ValueError('Enter just your HTTPS site address.')
    candidates=[Path.home()/'Documents/Codex/2026-10-20/austin-plan',Path.home()/'Downloads/austin-plan']
    found=next((p for p in candidates if (p/'data/training.sqlite').is_file() and (p/'data/garmin').is_dir()),None)
    value=input(f'Path to your working local app [{found or "enter full path"}]: ').strip()
    local=Path(value).expanduser() if value else found
    if not local or not (local/'data/training.sqlite').is_file() or not (local/'data/garmin').is_dir():raise ValueError('A working local app with saved Garmin login is required.')
    config=local/'data/hosting-secrets.json'
    if config.exists():
        saved=json.loads(config.read_text())
        if saved['origin']!=origin:raise ValueError('A different hosted address is already configured. Keep the original address or follow the migration guide.')
        encoded=saved['password_hash'];secret=saved['worker_secret'];key=saved['state_key']
        print('Reusing your saved hosting configuration and password. No keys changed.')
    else:
        password=getpass.getpass('Choose a NEW hosted app password (8+ characters): ')
        if len(password)<8 or password!=getpass.getpass('Repeat hosted app password: '):raise ValueError('Passwords must match and contain at least 8 characters.')
        encoded=password_hash(password);secret=secrets.token_urlsafe(48);key=base64.b64encode(os.urandom(32)).decode()
        # Recoverable setup: interrupted runs reuse these keys instead of destroying access to hosted state.
        with config.open('x',opener=lambda path,flags:os.open(path,flags,0o600)) as out:
            json.dump({'origin':origin,'password_hash':encoded,'worker_secret':secret,'state_key':key},out)
        print('Hosting recovery keys saved privately in your local app data folder. Keep a secure backup of that folder.')
    print('\nIn Netlify: Project configuration → Environment variables. Add each variable for production Functions (or all scopes). Values are copied one at a time. Never put these in GitHub source files.')
    for label,value in [('APP_ORIGIN',origin),('ADMIN_PASSWORD_HASH',encoded),('WORKER_SECRET',secret)]:
        copy_value('Netlify '+label,value)
    print('\nIn your GitHub repository: Settings → Secrets and variables → Actions → New repository secret.')
    for label,value in [('APP_ORIGIN',origin),('WORKER_SECRET',secret),('STATE_KEY',key)]:
        copy_value('GitHub '+label,value)
    subprocess.run(['pbcopy'],input=b'',check=True)
    # Netlify env edits require a new production deploy before the worker endpoint can authenticate.
    input('\nIn Netlify, trigger a production deploy and wait for Published. Then press Return to upload the encrypted initial state. ')
    current=remote(origin,secret)
    if current.get('sealed'):
        from server.hosted_worker import unseal
        hosted=unseal(current['sealed'],key)
        if input('Hosted journal already exists. Refresh ONLY its Garmin login from this Mac? [y/N]: ').strip().lower()=='y':
            hosted['tokens']=pack(Store(local/'data'))['tokens']
            with tempfile.TemporaryDirectory() as folder:
                from server.hosted_worker import restore
                target=restore(hosted,folder)
                planner=Planner(target,ROOT/'austin-plan/public/plan.json')
                remote(origin,secret,{'generation':current['generation'],'sealed':seal(pack(target),key),
                                     'dashboard':dashboard(target,planner),'ack':[]})
            print('Hosted Garmin login updated. Hosted activities and plan history preserved.')
        print('Run Garmin sync in GitHub Actions. Existing hosted data was preserved.')
        return
    with tempfile.TemporaryDirectory() as folder:
        source=Store(local/'data');payload=pack(source)
        from server.hosted_worker import restore
        target=restore(payload,folder)
        # Do not migrate local sessions, login attempts, or the local password into hosted state.
        with target.db() as db:
            db.execute('DELETE FROM sessions');db.execute('DELETE FROM attempts');db.execute("DELETE FROM meta WHERE key='password_hash'")
        planner=Planner(target,ROOT/'austin-plan/public/plan.json')
        remote(origin,secret,{'generation':current['generation'],'sealed':seal(pack(target),key),
                              'dashboard':dashboard(target,planner),'ack':[]})
    print('\nConnected. Open GitHub → Actions → Garmin sync → Run workflow. Then open your Netlify address and sign in with the NEW app password.')
    print('Keep your local app as your backup. Do not delete it.')

if __name__=='__main__':
    try:main()
    except KeyboardInterrupt:print('\nCancelled. No secrets printed. Rerun setup to restart.')
    except Exception as error:
        print('Setup stopped:',type(error).__name__+'. No secret values were printed. Check your settings before retrying.')
        raise SystemExit(1)

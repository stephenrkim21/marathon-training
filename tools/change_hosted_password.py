"""Rotate only the hosted website password; never display credentials."""
import getpass
import hashlib
import json
import os
from pathlib import Path
import secrets
import subprocess
import tempfile

def main():
    default=Path.home()/'Documents/Codex/2026-10-20/austin-plan'
    folder=Path(input(f'Working app folder [{default}]: ').strip() or default).expanduser()
    config=folder/'data/hosting-secrets.json'
    if not config.is_file():
        raise SystemExit('Saved hosting configuration not found. Use the working app folder you used in Connect-Hosting, then try again. No changes made.')
    saved=json.loads(config.read_text())
    password=getpass.getpass('New website password (8+ characters, hidden): ')
    if len(password)<8:raise SystemExit('Use at least 8 characters. No changes made.')
    if password!=getpass.getpass('Repeat new website password: '):raise SystemExit('Passwords did not match. No changes made.')
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),bytes.fromhex(salt),600000).hex()
    encoded=salt+':'+digest
    subprocess.run(['pbcopy'],input=encoded.encode(),check=True)
    saved['password_hash']=encoded
    fd,name=tempfile.mkstemp(prefix='.hosting-password-',dir=config.parent)
    try:
        with os.fdopen(fd,'w') as out:json.dump(saved,out)
        os.replace(name,config)
    finally:
        if os.path.exists(name):os.unlink(name)
    print('New password hash copied to clipboard. No password was printed.')
    print('Netlify → Project configuration → Environment variables → ADMIN_PASSWORD_HASH: replace its value by pasting, then save.')
    print('After uploading the included source changes to GitHub, trigger a production deploy. Sign in with your new password after Published.')
    print('Existing website sessions will be invalidated. Garmin tokens and hosting encryption keys were not changed.')

if __name__=='__main__':main()

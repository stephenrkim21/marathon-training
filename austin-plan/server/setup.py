"""Interactive local-only setup. Never run through an agent capturing input."""
import getpass
import os
import sys
from .core import Store, password_hash

def main():
    if not sys.stdin.isatty():raise SystemExit('Run this yourself in an interactive terminal; never paste credentials into chat.')
    store=Store()
    command=sys.argv[1] if len(sys.argv)>1 else ''
    if command=='password':
        password=getpass.getpass('Create app password (14+ characters): ')
        if len(password)<14:raise SystemExit('Use at least 14 characters.')
        if getpass.getpass('Repeat app password: ')!=password:raise SystemExit('Passwords did not match.')
        store.meta('password_hash',password_hash(password))
        with store.db() as db:db.execute('DELETE FROM sessions')
        print('App password saved securely. Existing sessions revoked.')
    elif command=='garmin':
        from garminconnect import Garmin
        tokens=store.directory/'garmin'
        tokens.mkdir(exist_ok=True,mode=0o700)
        client=Garmin(email=input('Garmin email: ').strip(),password=getpass.getpass('Garmin password: '),prompt_mfa=lambda:getpass.getpass('Garmin verification code: '))
        client.login(str(tokens))
        # Older releases use Garth token storage; newer releases save in login().
        if hasattr(client,'garth'):client.garth.dump(str(tokens))
        for file in tokens.rglob('*'):
            if file.is_file():file.chmod(0o600)
        if not any(tokens.iterdir()):raise SystemExit('No tokens saved; check installed library documentation before hosting.')
        store.meta('backfilled',False)
        print('Garmin session saved. Your Garmin password was not saved by this app.')
    else:raise SystemExit('Usage: python -m server.setup password | garmin')

if __name__=='__main__':main()

"""Initialize mounted-volume ownership, then run the service without root access."""
import os
from pathlib import Path
from urllib.parse import urlsplit

def main():
    origin=os.environ.get('APP_ORIGIN','').rstrip('/')
    parsed=urlsplit(origin)
    if parsed.scheme!='https' or not parsed.hostname or parsed.path or parsed.query or parsed.fragment or parsed.username:
        raise SystemExit('Set APP_ORIGIN to the exact HTTPS site origin before starting production.')
    os.environ['APP_ORIGIN']=origin
    data=Path(os.environ.get('DATA_DIR','/data'))
    if not data.is_absolute() or data==Path('/'):
        raise SystemExit('DATA_DIR must be an absolute dedicated data directory.')
    data.mkdir(parents=True,exist_ok=True,mode=0o700)
    if os.geteuid()==0:
        os.chown(data,10001,10001)
        for root,dirs,files in os.walk(data):
            for name in dirs+files:
                p=Path(root)/name
                if not p.is_symlink():os.chown(p,10001,10001)
        os.setgroups([]);os.setgid(10001);os.setuid(10001)
    os.umask(0o077)
    port=int(os.environ.get('PORT','8080'))
    if not 1<=port<=65535:raise SystemExit('Invalid port.')
    os.execvp('gunicorn',['gunicorn','server.app:app','--bind',f'0.0.0.0:{port}','--workers','1','--threads','4','--timeout','120'])

if __name__=='__main__':main()

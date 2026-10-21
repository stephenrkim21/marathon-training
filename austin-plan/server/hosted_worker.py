"""One-shot hourly worker. Private state is encrypted before leaving this process."""
import base64
import json
import os
import tempfile
import zlib
from datetime import date, datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from .core import ROOT, Store, Sync
from .adaptive import Planner, today_local

AAD = b'stephen-marathon-state-v1'


def seal(payload, key):
    nonce=os.urandom(12)
    return base64.b64encode(nonce+AESGCM(base64.b64decode(key,validate=True)).encrypt(nonce,zlib.compress(json.dumps(payload).encode()),AAD)).decode()


def unseal(encoded, key):
    raw=base64.b64decode(encoded,validate=True)
    return json.loads(zlib.decompress(AESGCM(base64.b64decode(key,validate=True)).decrypt(raw[:12],raw[12:],AAD)))


def pack(store):
    # SQLite backup avoids copying an open database/WAL inconsistently.
    import sqlite3
    with tempfile.TemporaryDirectory() as folder:
        file=Path(folder)/'snapshot.sqlite'
        with store.db() as source, sqlite3.connect(file) as destination:source.backup(destination)
        database=base64.b64encode(file.read_bytes()).decode()
    tokens={file.name:base64.b64encode(file.read_bytes()).decode() for file in (store.directory/'garmin').glob('*.json') if file.is_file()}
    return {'version':1,'database':database,'tokens':tokens}


def restore(payload, directory):
    if payload.get('version')!=1:raise ValueError('Unknown state version')
    directory=Path(directory);directory.mkdir(parents=True,exist_ok=True,mode=0o700)
    if payload.get('database'):
        (directory/'training.sqlite').write_bytes(base64.b64decode(payload['database'],validate=True))
        (directory/'training.sqlite').chmod(0o600)
    tokens=directory/'garmin';tokens.mkdir(mode=0o700,exist_ok=True)
    for name,content in payload.get('tokens',{}).items():
        if Path(name).name!=name or '/' in name or '\\' in name or not name.endswith('.json'):raise ValueError('Invalid token filename')
        file=tokens/name;file.write_bytes(base64.b64decode(content,validate=True));file.chmod(0o600)
    return Store(directory)


def dashboard(store, planner):
    coach=planner.snapshot()
    return {'plan':coach.pop('plan'),'coach':coach,'runs':store.runs(),'syncedAt':store.meta('syncedAt'),
            'sync':store.meta('sync') or {'state':'needs_auth','message':'Connect Garmin on your Mac first.'},
            'processedAt':datetime.now(timezone.utc).isoformat()}


def process(store, commands, sync=True):
    planner=Planner(store,ROOT/'public/plan.json')
    if sync:Sync(store).once()
    results=[]
    # Commands are replay-safe: the applied command and outcome commit in the encrypted database.
    with store.db() as db:db.execute('CREATE TABLE IF NOT EXISTS hosted_commands(id TEXT PRIMARY KEY, result TEXT NOT NULL)')
    for command in commands:
        with store.db() as db:row=db.execute('SELECT result FROM hosted_commands WHERE id=?',(command['id'],)).fetchone()
        if row:
            results.append({'id':command['id'],'error':row[0] or None});continue
        error=''
        try:
            path=command['path'];body=command['body']
            # Record a delayed check-in on its original Chicago date, never as today's recovery report.
            if path=='/api/checkin':planner.checkin(body,today=date.fromisoformat(command['date']),review=command['date']==today_local().isoformat())
            elif path=='/api/adaptive/mode':planner.set_enabled(body.get('enabled'))
            elif path=='/api/adaptive/undo':planner.undo(body['revision'])
            elif path=='/api/adaptive/approve':planner.approve(body['id'])
            else:raise ValueError('Unknown action')
        except (ValueError,KeyError,TypeError):error='This action could not be applied. Refresh and review the current plan before trying again.'
        with store.db() as db:db.execute('INSERT INTO hosted_commands VALUES (?,?)',(command['id'],error))
        results.append({'id':command['id'],'error':error or None})
    planner.evaluate()
    result=dashboard(store,planner)
    result['actionResults']=results[-20:]
    return result


def remote(origin, secret, body=None):
    if not origin.startswith('https://') or origin.rstrip('/')!=origin:raise ValueError('Use an HTTPS origin without a trailing slash')
    request=Request(origin+'/api/worker',data=json.dumps(body).encode() if body is not None else None,
                    headers={'Authorization':'Bearer '+secret,'Content-Type':'application/json'})
    with urlopen(request,timeout=40) as response:return json.load(response)


def main():
    origin=os.environ['APP_ORIGIN'];secret=os.environ['WORKER_SECRET'];key=os.environ['STATE_KEY']
    current=remote(origin,secret)
    if not current.get('sealed'):raise ValueError('Run tools/connect_hosting.py on your Mac to seed the hosted journal first.')
    with tempfile.TemporaryDirectory() as folder:
        store=restore(unseal(current['sealed'],key),folder)
        result=process(store,current['commands'])
        remote(origin,secret,{'generation':current['generation'],'sealed':seal(pack(store),key),
                              'dashboard':result,'ack':[c['id'] for c in current['commands']]})
        print('Hosted review finished. Garmin status:',result['sync']['state'])

if __name__=='__main__':
    try:main()
    except Exception as error:
        # Never print HTTP bodies, decrypted state, tokens, secrets, or upstream exception text.
        print('Hosted sync did not finish:',type(error).__name__+'. Existing hosted state was preserved.')
        raise SystemExit(1)

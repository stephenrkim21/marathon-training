"""Private single-athlete storage and Garmin sync; no web credential collection."""
import hashlib
import hmac
import json
import os
import secrets
import sqlite3
import threading
import time
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get('DATA_DIR', str(ROOT / 'data')))

def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac('sha256', password.encode(), bytes.fromhex(salt), 600000)
    return salt + ':' + digest.hex()

def verify(password, encoded):
    try:
        return hmac.compare_digest(password_hash(password, encoded.split(':')[0]), encoded)
    except (ValueError, TypeError):
        return False

class Store:
    def __init__(self, directory=DATA):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.path = self.directory / 'training.sqlite'
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS activities(id TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS meta(key TEXT PRIMARY KEY, value TEXT);
            CREATE TABLE IF NOT EXISTS sessions(token TEXT PRIMARY KEY, expires REAL);
            CREATE TABLE IF NOT EXISTS attempts(key TEXT PRIMARY KEY, count INTEGER, until REAL);
            ''')
        self.path.chmod(0o600)

    def db(self):
        return sqlite3.connect(str(self.path), timeout=20)

    def meta(self, key, value=None):
        with self.db() as db:
            if value is not None:
                db.execute('INSERT OR REPLACE INTO meta VALUES (?,?)', (key, json.dumps(value)))
            row = db.execute('SELECT value FROM meta WHERE key=?', (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def runs(self):
        with self.db() as db:
            return sorted([json.loads(r[0]) for r in db.execute('SELECT body FROM activities')], key=lambda a:a['start'], reverse=True)

    def upsert(self, activities):
        with self.db() as db:
            db.executemany('INSERT OR REPLACE INTO activities VALUES (?,?)', [(a['id'], json.dumps(a)) for a in activities])

    def session(self):
        token = secrets.token_urlsafe(32)
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE expires < ?', (time.time(),))
            db.execute('INSERT INTO sessions VALUES (?,?)', (hashlib.sha256(token.encode()).hexdigest(),time.time()+86400))
        return token

    def authorized(self, token):
        with self.db() as db:
            row = db.execute('SELECT expires FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),)).fetchone()
        return bool(row and row[0] > time.time())

    def logout(self, token):
        with self.db() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (hashlib.sha256(token.encode()).hexdigest(),))

    def attempt(self, key):
        # Global limit is intentional for this single-user app; proxy IPs aren't trusted.
        with self.db() as db:
            row = db.execute('SELECT count,until FROM attempts WHERE key=?',(key,)).fetchone()
            count, until = row if row and row[1]>time.time() else (0,time.time()+900)
            if count >= 10:return False
            db.execute('INSERT OR REPLACE INTO attempts VALUES (?,?,?)',(key,count+1,until))
        return True

def compact(a):
    if a.get('activityType',{}).get('typeKey') not in {'running','trail_running','treadmill_running','track_running','virtual_run','indoor_running'}:
        return None
    start = a.get('startTimeLocal')
    if not start or not a.get('activityId'):return None
    return {'id':str(a['activityId']), 'name':a.get('activityName','Run'), 'date':start[:10], 'start':start,
            'distance':max(0,float(a.get('distance') or 0)), 'moving':max(0,float(a.get('movingDuration') or a.get('duration') or 0)),
            'elapsed':max(0,float(a.get('elapsedDuration') or a.get('duration') or 0)),
            'hr':a.get('averageHR'), 'maxHr':a.get('maxHR'), 'deviceId':str(a.get('deviceId') or '')}

class Sync:
    def __init__(self, store, factory=None):
        self.store = store
        self.factory = factory
        self.lock = threading.Lock()
        self.failures = 0

    def once(self):
        if not self.lock.acquire(blocking=False):return
        try:
            if self.factory:
                client = self.factory()
            else:
                from garminconnect import Garmin
                tokens = self.store.directory / 'garmin'
                if not tokens.exists() or not any(tokens.iterdir()):
                    self.store.meta('sync', {'state':'needs_auth', 'message':'Connect Garmin locally using the setup command.'})
                    return
                client = Garmin()
                client.login(str(tokens))
            device = os.environ.get('GARMIN_DEVICE_ID','')
            plan = json.loads((ROOT/'public/plan.json').read_text())
            start = (date.fromisoformat(plan['weeks'][0]['start'])-timedelta(days=56)).isoformat()
            # Initial history backfill; subsequent runs rescan latest 100 for edits and late uploads.
            initial = not self.store.meta('backfilled') or self.store.meta('history_start')!=start
            found = []
            completed = False
            for offset in range(0, 10000 if initial else 100, 100):
                batch = client.get_activities(offset,100)
                for raw in batch:
                    a = compact(raw)
                    if a and a['date'] >= start and (not device or a['deviceId']==device):found.append(a)
                if len(batch)<100 or any((a.get('startTimeLocal') or '9999')[:10]<start for a in batch):
                    completed = True
                    break
            self.store.upsert(found)
            if not self.factory and hasattr(client, 'garth'):
                client.garth.dump(str(self.store.directory / 'garmin'))
            if not self.factory:
                for file in (self.store.directory / 'garmin').rglob('*'):
                    if file.is_file():file.chmod(0o600)
            if initial and completed:
                self.store.meta('backfilled',True)
                self.store.meta('history_start',start)
            self.store.meta('syncedAt',datetime.now(timezone.utc).isoformat())
            self.store.meta('sync', {'state':'ready','message':'Garmin connected', 'deviceFilter':device or 'All running devices'})
            self.failures = 0
        except Exception as e:
            # Never expose upstream errors: they can contain session data or credentials.
            self.failures += 1
            self.store.meta('sync', {'state':'error','message':'Garmin sync failed. Check connectivity or reconnect locally.', 'errorType':type(e).__name__})
        finally:
            self.lock.release()

    def loop(self, stop):
        while not stop.is_set():
            self.once()
            stop.wait(min(3600, 600 * (2 ** min(self.failures, 3))))

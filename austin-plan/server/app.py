"""WSGI web service. Production: one Gunicorn process with a background sync thread."""
import atexit
import json
import mimetypes
import os
import threading
import time
from .adaptive import Planner
from http.cookies import SimpleCookie
from urllib.parse import parse_qs
from .core import ROOT, Store, Sync, verify

LOGIN = '''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stephen · Sign in</title><style>body{background:#101512;color:#f5f4e9;font:18px system-ui;max-width:360px;margin:15vh auto;padding:24px}h1{font-size:42px}input,button{box-sizing:border-box;width:100%;padding:16px;margin:12px 0;font:inherit}button{background:#d0ed73;border:0;border-radius:8px}small{color:#aab2a7}</style><h1>Your road<br>to 3:40.</h1><p>Stephen’s private training journal</p><form action="/login" method="post"><label for="password">App password</label><input id="password" name="password" type="password" autocomplete="current-password" required minlength="14"><button>Sign in</button></form><small>Use your app password. Garmin sign-in happens separately on your Mac.</small></html>'''

class App:
    def __init__(self, store=None):
        self.store=store or Store()
        self.planner=Planner(self.store, ROOT/"public/plan.json")

    def __call__(self, env, respond):
        path=env.get('PATH_INFO','/')
        method=env.get('REQUEST_METHOD','GET')
        origin=os.environ.get('APP_ORIGIN','http://127.0.0.1:8765').rstrip('/')
        headers=[('Cache-Control','no-store'),('X-Content-Type-Options','nosniff'),('Referrer-Policy','same-origin'),('X-Frame-Options','DENY'),('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'")]
        secure=origin.startswith('https://')
        if secure:headers.append(('Strict-Transport-Security','max-age=31536000'))
        def send(status, body, mime='application/json', extra=()):
            if not isinstance(body,(str,bytes)):body=json.dumps(body)
            if isinstance(body,str):body=body.encode()
            respond(status, headers+[('Content-Type',mime),('Content-Length',str(len(body)))]+list(extra))
            return [b'' if method=='HEAD' else body]
        def cookie(token, age=86400):
            return ('Set-Cookie',f'session={token}; HttpOnly; SameSite=Strict; Path=/; Max-Age={age}'+('; Secure' if secure else ''))
        if method not in ('GET','HEAD','POST'):return send('405 Method Not Allowed',{'error':'Method not allowed'})
        if method=='POST' and env.get('HTTP_ORIGIN')!=origin:
            return send('403 Forbidden',{'error':'Invalid origin'})
        if path=='/health':return send('200 OK',{'ok':True})
        if path=='/login' and method in ('GET','HEAD'):return send('200 OK',LOGIN,'text/html; charset=utf-8')
        if path=='/login' and method=='POST':
            if not self.store.attempt('login'):return send('429 Too Many Requests',{'error':'Wait 15 minutes before retrying'})
            encoded=os.environ.get('ADMIN_PASSWORD_HASH') or self.store.meta('password_hash')
            if not encoded:return send('503 Service Unavailable',{'error':'Run local app password setup first'})
            try:length=int(env.get('CONTENT_LENGTH') or 0)
            except ValueError:return send('400 Bad Request',{'error':'Invalid request'})
            if length>4096 or length<0:return send('413 Content Too Large',{'error':'Request too large'})
            password=parse_qs(env['wsgi.input'].read(length).decode()).get('password',[''])[0]
            if not verify(password,encoded):return send('401 Unauthorized',{'error':'Incorrect app password'})
            return send('303 See Other','',extra=[('Location','/'),cookie(self.store.session())])
        jar=SimpleCookie()
        try:jar.load(env.get('HTTP_COOKIE',''))
        except Exception:pass
        token=jar['session'].value if 'session' in jar else ''
        if not self.store.authorized(token):
            if path.startswith('/api/'):return send('401 Unauthorized',{'error':'Sign in required'})
            return send('303 See Other','',extra=[('Location','/login')])
        if path=='/logout' and method=='POST':
            self.store.logout(token)
            return send('303 See Other','',extra=[('Location','/login'),cookie('',0)])
        if method=='POST' and path.startswith('/api/'):
            try:
                length=int(env.get('CONTENT_LENGTH') or 0)
                if not 0<length<=4096:raise ValueError('Invalid request size.')
                body=json.loads(env['wsgi.input'].read(length).decode())
                if not isinstance(body,dict):raise ValueError('Expected a JSON object.')
                if path=='/api/checkin':self.planner.checkin(body)
                elif path=='/api/adaptive/mode':self.planner.set_enabled(body.get('enabled'))
                elif path=='/api/adaptive/undo':
                    if type(body.get('revision')) is not int:raise ValueError('Invalid revision.')
                    self.planner.undo(body['revision'])
                elif path=='/api/adaptive/approve':self.planner.approve(body.get('id'))
                else:return send('404 Not Found',{'error':'Not found'})
                return send('200 OK',{'ok':True})
            except (ValueError,UnicodeDecodeError) as error:
                return send('400 Bad Request',{'error':str(error)})
        if method=='POST':return send('404 Not Found',{'error':'Not found'})
        if path=='/api/dashboard':
            coach=self.planner.snapshot()
            return send('200 OK',{'plan':coach.pop('plan'),'coach':coach,'runs':self.store.runs(), 'syncedAt':self.store.meta('syncedAt'),'sync':self.store.meta('sync') or {'state':'needs_auth','message':'Garmin has not been connected'}})
        name='index.html' if path=='/' else path.lstrip('/')
        file=(ROOT/'public'/name).resolve()
        if not file.is_relative_to((ROOT/'public').resolve()) or not file.is_file():return send('404 Not Found',{'error':'Not found'})
        return send('200 OK',file.read_bytes(),mimetypes.guess_type(str(file))[0] or 'application/octet-stream')

app=App()
stop=threading.Event()
def background():
    sync=Sync(app.store)
    next_sync=0
    while not stop.is_set():
        if os.environ.get('SYNC_ENABLED','1')=='1' and time.monotonic()>=next_sync:
            sync.once()
            next_sync=time.monotonic()+min(3600,600*(2**min(sync.failures,3)))
        try:
            app.planner.evaluate()
        except Exception as error:
            app.store.meta('planner_error',{'type':type(error).__name__,'message':'Plan evaluation paused; existing plan preserved.'})
        stop.wait(60)

if os.environ.get('BACKGROUND_ENABLED','1')=='1':
    threading.Thread(target=background,daemon=True).start()
atexit.register(stop.set)

if __name__=='__main__':
    from wsgiref.simple_server import make_server
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIServer
    class LocalServer(ThreadingMixIn,WSGIServer):
        daemon_threads=True
    with make_server('127.0.0.1',8765,app,server_class=LocalServer) as server:
        print('Private app: http://127.0.0.1:8765',flush=True)
        server.serve_forever()

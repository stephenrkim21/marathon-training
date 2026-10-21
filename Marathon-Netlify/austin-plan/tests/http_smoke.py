"""Exercise the real Gunicorn/HTTP stack with a disposable account, never Garmin."""
import http.cookiejar,json,os,socket,subprocess,sys,tempfile,time,urllib.request,urllib.error
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from server.core import Store,password_hash

def main():
 with tempfile.TemporaryDirectory() as tmp:
  store=Store(tmp);store.meta('password_hash',password_hash('fixture-private-password'))
  with socket.socket() as s:s.bind(('127.0.0.1',0));port=s.getsockname()[1]
  base=f'http://127.0.0.1:{port}'
  env=dict(os.environ,DATA_DIR=tmp,APP_ORIGIN=base,BACKGROUND_ENABLED='0',SYNC_ENABLED='0')
  p=subprocess.Popen([sys.executable,'-m','gunicorn','server.app:app','--bind',f'127.0.0.1:{port}','--workers','1','--threads','4'],env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
  client=urllib.request.build_opener(urllib.request.ProxyHandler({}),urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
  def post(path,body,origin=base):
   return client.open(urllib.request.Request(base+path,data=json.dumps(body).encode(),headers={'Origin':origin,'Content-Type':'application/json'}),timeout=3)
  try:
   for _ in range(100):
    try:client.open(base+'/health',timeout=.2);break
    except (OSError,urllib.error.URLError):time.sleep(.05)
   else:raise RuntimeError('Gunicorn did not become ready')
   r=client.open(base+'/login');assert r.headers['Referrer-Policy']=='same-origin'
   client.open(urllib.request.Request(base+'/login',data=b'password=fixture-private-password',headers={'Origin':base,'Content-Type':'application/x-www-form-urlencoded'}))
   for path in ['/','/app.js','/app.css','/icons/icon-192.png']:
    assert client.open(base+path).code==200
   before=json.load(client.open(base+'/api/dashboard'))
   post('/api/checkin',dict(soreness=4,fatigue=4,effort=7,pain=False))
   after=json.load(client.open(base+'/api/dashboard'));assert after['coach']['history'][0]['source']=='automatic'
   post('/api/adaptive/undo',{'revision':after['coach']['history'][0]['id']})
   assert json.load(client.open(base+'/api/dashboard'))['plan']==before['plan']
   try:post('/api/adaptive/mode',{'enabled':False},'null')
   except urllib.error.HTTPError as e:assert e.code==403
   else:raise AssertionError('Null origin allowed')
   post('/logout',{})
   try:client.open(base+'/api/dashboard')
   except urllib.error.HTTPError as e:assert e.code==401
   else:raise AssertionError('Signed-out data access allowed')
   print('Gunicorn HTTP smoke test passed: login, private assets, check-in, adaptation, undo, CSRF, logout.')
  finally:
   p.terminate()
   try:p.wait(timeout=5)
   except subprocess.TimeoutExpired:p.kill();p.wait()

if __name__=='__main__':main()

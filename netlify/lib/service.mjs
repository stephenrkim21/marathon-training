import { randomBytes, createHash, timingSafeEqual, pbkdf2 as pbkdf2Callback } from 'node:crypto';
import { promisify } from 'node:util';
const pbkdf2=promisify(pbkdf2Callback);
const hash=s=>createHash('sha256').update(s).digest('hex');
const equal=(a,b)=>typeof a==='string'&&typeof b==='string'&&Buffer.byteLength(a)===Buffer.byteLength(b)&&timingSafeEqual(Buffer.from(a),Buffer.from(b));
const day=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const LOGIN=`<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Stephen · Sign in</title><style>body{background:#101512;color:#f5f4e9;font:18px system-ui;max-width:360px;margin:15vh auto;padding:24px}input,button{box-sizing:border-box;width:100%;padding:16px;margin:12px 0;font:inherit}button{background:#d0ed73;border:0;border-radius:8px}</style><h1>Your road<br>to 3:40.</h1><p>Stephen’s private training journal</p><form action="/login" method="post"><label for="password">App password</label><input id="password" name="password" type="password" autocomplete="current-password" required minlength="8"><button>Sign in</button></form><small>Use your app password, not your Garmin password.</small></html>`;
const ASSETS={'index.html':'text/html; charset=utf-8','app.js':'text/javascript; charset=utf-8','app.css':'text/css; charset=utf-8','manifest.webmanifest':'application/manifest+json','sw.js':'text/javascript','img/bg.jpg':'image/jpeg','icons/icon-192.png':'image/png','icons/icon-512.png':'image/png','icons/apple-touch-icon.png':'image/png','fonts/Interstate-Black.otf':'font/otf'};
const headers={'Cache-Control':'no-store','X-Content-Type-Options':'nosniff','Referrer-Policy':'same-origin','X-Frame-Options':'DENY','Strict-Transport-Security':'max-age=31536000','Content-Security-Policy':"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self'; font-src 'self'; frame-ancestors 'none'; form-action 'self'; base-uri 'none'"};
function validate(path,b){
 if(!b||Array.isArray(b)||typeof b!=='object')throw Error('Expected an object.');
 if(path==='/api/checkin'){
  if(Object.keys(b).sort().join(',')!=='effort,fatigue,pain,soreness')throw Error('Invalid check-in.');
  for(const [key,max] of [['soreness',5],['fatigue',5],['effort',10]])if(!Number.isInteger(b[key])||b[key]<1||b[key]>max)throw Error('Score out of range.');
  if(typeof b.pain!=='boolean')throw Error('Pain must be true or false.');
 }else if(path==='/api/adaptive/mode'){if(typeof b.enabled!=='boolean')throw Error('Invalid mode.');}
 else if(path==='/api/adaptive/undo'){if(!Number.isSafeInteger(b.revision)||b.revision<1)throw Error('Invalid revision.');}
 else if(path==='/api/adaptive/approve'){if(typeof b.id!=='string'||!(/^[a-f0-9]{64}$/).test(b.id))throw Error('Invalid proposal.');}
 else throw Error('Unknown action.');
}
export function createService({store,asset,env}){
 async function atomic(key,update){
  const s=store();
  for(let n=0;n<12;n++){
   const entry=await s.getWithMetadata(key,{type:'json'});
   const value=await update(entry?.data??null);
   const result=await s.setJSON(key,value,entry?{onlyIfMatch:entry.etag}:{onlyIfNew:true});
   if(result.modified)return value;
  }
  throw Error('Storage busy. Try again.');
 }
 return async function(request){
  const url=new URL(request.url),pathname=url.pathname,method=request.method;
  const reply=(status,body,mime='application/json',extra={})=>new Response(method==='HEAD'?null:(typeof body==='string'||body instanceof Uint8Array?body:JSON.stringify(body)),{status,headers:{...headers,'Content-Type':mime,...extra}});
  const redirect=(where,extra={})=>reply(303,'','text/plain',{Location:where,...extra});
  const cookie=(token,age=86400)=>`session=${token}; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=${age}`;
  try{
   // Preview deployments never read or modify production data.
   if(env.CONTEXT!=='production')return reply(503,{error:'Private app is enabled only on the production deployment.'});
   let origin;
   try{origin=new URL(env.APP_ORIGIN).origin;if(!env.APP_ORIGIN.startsWith('https://')||origin!==env.APP_ORIGIN)throw Error();}
   catch{return reply(503,{error:'Complete the hosting configuration first.'});}
   if(url.origin!==origin)return reply(421,{error:'Use the configured app address.'});
   if(!['GET','HEAD','POST'].includes(method))return reply(405,{error:'Method not allowed'});
   if(method==='POST'&&request.headers.get('origin')!==origin&&pathname!=='/api/worker')return reply(403,{error:'Invalid origin'});
   if(pathname==='/health')return reply(200,{ok:true});
   const s=store();
   if(pathname==='/api/worker'){
    if(!env.WORKER_SECRET||env.WORKER_SECRET.length<40||!equal(request.headers.get('authorization'),`Bearer ${env.WORKER_SECRET}`))return reply(401,{error:'Unauthorized'});
    if(method==='GET'){
     const current=await s.get('journal',{type:'json'});
     return reply(200,{sealed:current?.sealed??null,commands:current?.commands??[],generation:current?.generation??0});
    }
    if(method!=='POST')return reply(405,{error:'Method not allowed'});
    const raw=await limited(request,6_000_000),body=JSON.parse(raw);
    if(typeof body.sealed!=='string'||!body.sealed||!body.dashboard?.plan||!Array.isArray(body.ack)||!Number.isSafeInteger(body.generation))return reply(400,{error:'Invalid worker payload'});
    let conflict=false;
    await atomic('journal',current=>{
     current??={commands:[],generation:0};
     if((current.generation??0)!==body.generation){conflict=true;return current;}
     const allowed=new Set(current.commands.map(c=>c.id));
     if(body.ack.some(id=>!allowed.has(id)))throw Error('Invalid acknowledgement');
     return {...current,sealed:body.sealed,dashboard:body.dashboard,commands:current.commands.filter(c=>!body.ack.includes(c.id)),generation:body.generation+1};
    });
    return reply(conflict?409:200,{ok:!conflict});
   }
   if(pathname==='/login'&&(method==='GET'||method==='HEAD'))return reply(200,LOGIN,'text/html; charset=utf-8');
   if(pathname==='/login'&&method==='POST'){
    const encoded=env.ADMIN_PASSWORD_HASH;
    if(!encoded||!(/^[a-f0-9]{32}:[a-f0-9]{64}$/).test(encoded))return reply(503,{error:'Set up the app password first.'});
    let allowed=false;
    await atomic('login-attempts',v=>{
     const now=Date.now();if(!v||v.until<=now)v={count:0,until:now+900000};
     allowed=v.count<10;return {...v,count:Math.min(10,v.count+1)};
    });
    if(!allowed)return reply(429,{error:'Wait 15 minutes before retrying.'});
    const password=new URLSearchParams(await limited(request,4096)).get('password')??'';
    const [salt,digest]=encoded.split(':');
    const actual=await pbkdf2(password,Buffer.from(salt,'hex'),600000,32,'sha256');
    if(!equal(actual.toString('hex'),digest))return reply(401,{error:'Incorrect app password'});
    const token=randomBytes(32).toString('hex'),id=hash(encoded+token);
    await atomic('sessions',v=>[...(v??[]).filter(x=>x.expires>Date.now()).slice(-9),{id,expires:Date.now()+86400000}]);
    return redirect('/',{'Set-Cookie':cookie(token)});
   }
   const token=(request.headers.get('cookie')??'').split(';').map(v=>v.trim()).find(v=>v.startsWith('session='))?.slice(8)??'';
   const sessions=await s.get('sessions',{type:'json'})??[];
   const ident=hash((env.ADMIN_PASSWORD_HASH??'')+token);
   const authorized=/^[a-f0-9]{64}$/.test(token)&&sessions.some(x=>x.expires>Date.now()&&equal(x.id,ident));
   if(!authorized)return pathname.startsWith('/api/')?reply(401,{error:'Sign in required'}):redirect('/login');
   if(pathname==='/logout'&&method==='POST'){
    await atomic('sessions',v=>(v??[]).filter(x=>x.id!==ident&&x.expires>Date.now()));
    return redirect('/login',{'Set-Cookie':cookie('',0)});
   }
   if(pathname==='/api/dashboard'&&(method==='GET'||method==='HEAD')){
    const journal=await s.get('journal',{type:'json'});
    if(!journal?.dashboard)return reply(503,{error:'Waiting for the first hosted sync. Run Garmin sync in GitHub Actions after connecting.'});
    return reply(200,{...journal.dashboard,hosting:{intervalMinutes:60,pending:journal.commands?.length??0,lastProcessed:journal.dashboard.processedAt}});
   }
   if(method==='POST'&&pathname.startsWith('/api/')){
    let body;
    try{body=JSON.parse(await limited(request,4096));validate(pathname,body);}catch{return reply(400,{error:'Invalid action or check-in.'});}
    const command={id:randomBytes(16).toString('hex'),path:pathname,body,date:day(),created:new Date().toISOString()};
    let full=false;
    await atomic('journal',v=>{
     v??={commands:[],generation:0};if(v.commands.length>=100){full=true;return v;}
     return {...v,commands:[...v.commands,command]};
    });
    return reply(full?429:202,full?{error:'Too many pending changes. Wait for the next sync.'}:{ok:true,queued:true,message:'Saved for the next hourly review. If you reported pain, pause running now rather than waiting for the app.'});
   }
   if(method==='POST')return reply(404,{error:'Not found'});
   const name=pathname==='/'?'index.html':pathname.slice(1);
   if(!Object.hasOwn(ASSETS,name))return reply(404,{error:'Not found'});
   try{return reply(200,await asset(name),ASSETS[name]);}catch{return reply(404,{error:'Not found'});}
  }catch{return reply(503,{error:'The journal is temporarily unavailable. Please try again.'});}
 };
}
async function limited(request,max){
 const reader=request.body?.getReader();if(!reader)return '';
 let length=0;const chunks=[];
 while(true){const {done,value}=await reader.read();if(done)break;length+=value.length;if(length>max){await reader.cancel();throw Error('Request too large');}chunks.push(value);}
 return Buffer.concat(chunks).toString('utf8');
}

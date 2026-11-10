import { test } from 'node:test';
import assert from 'node:assert/strict';
import { pbkdf2Sync } from 'node:crypto';
import { createService } from '../netlify/lib/service.mjs';
class Memory {
 data=new Map();count=0;
 async get(k){return structuredClone(this.data.get(k)?.data??null)}
 async getWithMetadata(k){return structuredClone(this.data.get(k)??null)}
 async setJSON(k,value,condition){
  const old=this.data.get(k);
  if(condition.onlyIfNew&&old||condition.onlyIfMatch&&old?.etag!==condition.onlyIfMatch)return {modified:false};
  this.data.set(k,{data:structuredClone(value),etag:String(++this.count)});return {modified:true};
 }
}
const origin='https://training.example';const password='a new private app password';const salt='ab'.repeat(16);
const encoded=salt+':'+pbkdf2Sync(password,Buffer.from(salt,'hex'),600000,32,'sha256').toString('hex');
function fixture(){const memory=new Memory(),env={CONTEXT:'production',APP_ORIGIN:origin,ADMIN_PASSWORD_HASH:encoded,WORKER_SECRET:'x'.repeat(64)};const service=createService({store:()=>memory,asset:async name=>Buffer.from('private asset '+name),env});return {memory,env,service};}
function req(path,{method='GET',body,cookie,worker=false,originHeader=origin}={}){return new Request(origin+path,{method,headers:{...(method==='POST'?{Origin:originHeader}:{}),...(cookie?{Cookie:cookie}:{}),...(worker?{Authorization:'Bearer '+'x'.repeat(64)}:{})},body:body===undefined?undefined:typeof body==='string'?body:JSON.stringify(body)});}
async function login(f){const response=await f.service(req('/login',{method:'POST',body:new URLSearchParams({password}).toString()}));assert.equal(response.status,303);assert.match(response.headers.get('set-cookie'),/HttpOnly; Secure; SameSite=Strict/);return response.headers.get('set-cookie').split(';')[0];}
test('visitors can read the training page and workout summaries, while private data and edits require sign-in',async()=>{
 const f=fixture();
 const workout={id:'123',name:'Private name',type:'strength_training',date:'2026-11-10',distance:0,moving:600,elapsed:650,hr:155,deviceId:'456'};
 const plan={weeks:[{days:[{miles:0,desc:'Recovery check-in: you reported pain.'}]}]};
 await f.memory.setJSON('journal',{dashboard:{plan,workouts:[workout],runs:[{...workout,type:undefined}],coach:{checkin:{pain:true}},sync:{state:'ready',deviceFilter:'456'}},commands:[],sealed:'private'}, {onlyIfNew:true});
 for(const path of ['/','/app.js','/icons/icon-192.png'])assert.equal((await f.service(req(path))).status,200);
 assert.equal((await f.service(req('/plan.json'))).status,404);
 const response=await f.service(req('/api/dashboard'));
 assert.equal(response.status,200);
 const guest=await response.json();
 assert.deepEqual(guest.workouts,[{type:workout.type,date:workout.date,distance:0,moving:600,elapsed:650}]);
 assert.equal(guest.runs[0].type,'running');
 assert.equal(guest.plan.weeks[0].days[0].desc,'Rest today. Skip catch-up mileage.');
 assert.equal(guest.coach,undefined);
 assert.equal(guest.sync.deviceFilter,undefined);
 assert.equal((await f.service(req('/api/checkin',{method:'POST',body:{}}))).status,401);
 assert.equal((await f.service(req('/api/worker'))).status,401);
 const cookie=await login(f);
 const owner=await (await f.service(req('/api/dashboard',{cookie}))).json();
 assert.deepEqual(owner.workouts,[workout]);
 assert.equal(owner.coach.checkin.pain,true);
});
test('login, logout and password rotation revoke server-side sessions',async()=>{
 const f=fixture();
 const body={soreness:2,fatigue:2,effort:4,pain:false};
 const edit=cookie=>f.service(req('/api/checkin',{method:'POST',cookie,body}));
 const cookie=await login(f);
 assert.equal((await edit(cookie)).status,202);
 assert.equal((await f.service(req('/logout',{method:'POST',cookie}))).status,303);
 assert.equal((await edit(cookie)).status,401);
 const another=await login(f);
 f.env.ADMIN_PASSWORD_HASH='cd'.repeat(16)+':'+encoded.split(':')[1];
 assert.equal((await edit(another)).status,401);
});
test('null and foreign origins rejected including logged-in actions',async()=>{const f=fixture(),cookie=await login(f);for(const originHeader of ['null','https://attacker.example'])assert.equal((await f.service(req('/api/checkin',{method:'POST',cookie,originHeader,body:{}}))).status,403);});
test('atomic attempt budget cannot be bypassed by concurrent requests',async()=>{const f=fixture();const responses=await Promise.all(Array.from({length:15},()=>f.service(req('/login',{method:'POST',body:'password=wrong'}))));assert.equal(responses.filter(r=>r.status===401).length,10);assert.equal(responses.filter(r=>[429,503].includes(r.status)).length,5);});
test('queued check-in schema validates and worker publication preserves concurrent new commands',async()=>{const f=fixture(),cookie=await login(f);const post=b=>f.service(req('/api/checkin',{method:'POST',cookie,body:b}));assert.equal((await post({pain:'no'})).status,400);const b={soreness:2,fatigue:2,effort:4,pain:false};await post(b);const snapshot=await (await f.service(req('/api/worker',{worker:true}))).json();await post({...b,fatigue:4});const commit={sealed:'encrypted opaque state',dashboard:{plan:{weeks:[]}},ack:snapshot.commands.map(c=>c.id),generation:0};assert.equal((await f.service(req('/api/worker',{method:'POST',worker:true,body:commit}))).status,200);const current=await f.memory.get('journal');assert.equal(current.commands.length,1);assert.equal(current.commands[0].body.fatigue,4);assert.equal((await f.service(req('/api/worker',{method:'POST',worker:true,body:commit}))).status,409);assert.equal((await f.memory.get('journal')).generation,1);});
test('parallel check-ins are all saved without lost updates',async()=>{const f=fixture(),cookie=await login(f);const responses=await Promise.all(Array.from({length:8},()=>f.service(req('/api/checkin',{method:'POST',cookie,body:{soreness:2,fatigue:2,effort:4,pain:false}}))));assert.ok(responses.every(r=>r.status===202));assert.equal((await f.memory.get('journal')).commands.length,8);});
test('preview and alternate host cannot touch production data',async()=>{const f=fixture();f.env.CONTEXT='deploy-preview';assert.equal((await f.service(req('/api/worker',{worker:true}))).status,503);f.env.CONTEXT='production';assert.equal((await f.service(new Request('https://alternate.example/login'))).status,421);});
test('only explicit assets served; saved state and baseline never served as static files',async()=>{const f=fixture(),cookie=await login(f);for(const path of ['/plan.json','/../server/core.py','/data/training.sqlite','/fonts/../../server/core.py'])assert.equal((await f.service(req(path,{cookie}))).status,404);assert.equal((await f.service(req('/fonts/Interstate-Black.otf',{cookie}))).status,200);});

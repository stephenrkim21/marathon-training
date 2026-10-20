'use strict';
let editingCheckin=false;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const miles=m=>m/1609.344;
const pace=s=>!Number.isFinite(s)||s<=0?'—':`${Math.floor(Math.round(s)/60)}:${String(Math.round(s)%60).padStart(2,'0')}`;
const duration=s=>`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const dateLabel=s=>new Date(s+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'});
function totals(runs){return {distance:runs.reduce((n,r)=>n+r.distance,0),moving:runs.reduce((n,r)=>n+r.moving,0)}}
function activity(r){return `<div class="actual"><a target="_blank" rel="noopener noreferrer" href="https://connect.garmin.com/modern/activity/${encodeURIComponent(r.id)}">${esc(r.name)} ↗</a><div class="metrics"><span>${miles(r.distance).toFixed(2)}<small>MILES</small></span><span>${pace(r.moving/miles(r.distance))}<small>PACE / MI</small></span><span>${duration(r.moving)}<small>MOVING TIME</small></span><span>${duration(r.elapsed)}<small>ELAPSED TIME</small></span><span>${r.hr?Math.round(r.hr):'—'}<small>AVG HR</small></span></div></div>`}
async function load(){
 $('refresh').disabled=true;
 try{
 const response=await fetch('/api/dashboard',{cache:'no-store'});
 if(response.status===401){location.replace('/login');return;}
 if(!response.ok)throw Error('Could not load your journal. Try refreshing.');
 const {plan,runs,sync,syncedAt,coach}=await response.json();
 renderCoach(coach);
 const current=plan.weeks.find(w=>w.start<=today()&&today()<=w.end);
 const weekRuns=current?runs.filter(r=>r.date>=current.start&&r.date<=current.end):[];
 const sum=totals(weekRuns);
 $('distance').textContent=miles(sum.distance).toFixed(1);
 $('duration').textContent=duration(sum.moving);
 $('pace').textContent=pace(sum.moving/miles(sum.distance));
 $('count').textContent=weekRuns.length;
 $('syncState').textContent=sync.message;
 $('syncTime').textContent=syncedAt?`Last successful sync ${new Date(syncedAt).toLocaleString()} · checks every 10 minutes${sync.deviceFilter?' · '+sync.deviceFilter:''}`:'Waiting for your first Garmin sync. No sample workouts are shown.';
 $('review').textContent=plan.status;
 const open=new Set([...document.querySelectorAll('details[open]')].map(el=>el.id));
 const first=!$('weeks').children.length;
 $('weeks').innerHTML=plan.weeks.map(w=>{
 const wr=runs.filter(r=>r.date>=w.start&&r.date<=w.end),t=totals(wr),actual=miles(t.distance);
 return `<details id="week-${w.week}" ${(open.has(`week-${w.week}`)||(first&&w===current))?'open':''}><summary><div><span class="week-label">Week ${w.week} · ${esc(w.phase)}</span><span class="week-date">${dateLabel(w.start)} – ${dateLabel(w.end)}</span></div><div class="week-total">${actual.toFixed(1)} / ${w.total} mi<small>${duration(t.moving)} completed · ${wr.length} runs</small></div></summary><div class="progress"><i style="width:${Math.min(100,100*actual/w.total)||0}%"></i></div>${w.days.map(d=>{
 const dr=wr.filter(r=>r.date===d.date);
 return `<div class="day"><div class="date">${new Date(d.date+'T12:00:00').toLocaleDateString('en-US',{weekday:'short'})}<strong>${d.date.slice(8)}</strong></div><div class="workout"><b>${esc(d.title)}</b><p>${esc(d.desc)}</p></div><div class="planned">${d.miles?d.miles+' mi':'Rest'}<small>${d.miles?esc(d.pace):'Recovery matters'}</small></div>${dr.length?dr.map(activity).join(''):`<div class="no-run">${d.date<today()&&d.miles?'No completed run recorded':d.miles?'Planned workout':'Rest day'} </div>`}</div>`}).join('')}</details>`;
 }).join('');
 $('current').onclick=()=>{if(current){const el=$(`week-${current.week}`);el.open=true;el.scrollIntoView({behavior:'smooth',block:'start'})}};
 }catch(e){$('syncState').textContent=e.message;}finally{$('refresh').disabled=false;}
}
$('refresh').onclick=load;
load();setInterval(()=>{if(!document.hidden)load()},60000);
// Clear legacy Strava caches, keys, and offline service workers on upgrade.
for(const key of ['appKey','runsCache','syncedAt','overrides','extraRuns'])localStorage.removeItem(key);
if('serviceWorker' in navigator)navigator.serviceWorker.getRegistrations().then(rs=>rs.forEach(r=>r.unregister()));
if('caches' in window)caches.keys().then(ks=>ks.forEach(k=>caches.delete(k)));

function renderCoach(coach){
 if(!coach)return;
 $('autoMode').checked=coach.enabled;
 $('coachNote').textContent=coach.note;
 if(!editingCheckin&&coach.checkin){
  for(const key of ['soreness','fatigue','effort'])$(key).value=coach.checkin[key];
  $('pain').checked=coach.checkin.pain;
  $('checkinStatus').textContent='Today’s check-in saved';
 }
 const latest=coach.history[0];
 $('history').innerHTML=coach.history.length?coach.history.map(h=>`<article class="change"><small>${esc(new Date(h.created).toLocaleString())} · ${esc(h.source)}</small><p>${esc(h.reason)}</p><ul>${h.changes.map(c=>`<li>${esc(dateLabel(c.date))}: ${c.from} → ${c.to} mi · ${esc(c.title)}</li>`).join('')}</ul>${h===latest&&h.source!=='undo'?`<button type="button" data-undo="${h.id}">Undo latest change</button>`:''}</article>`).join(''):'<p class="change">No changes yet. Your original plan stays in place until a rule applies.</p>';
 const p=coach.proposal;
 $('proposal').innerHTML=p?`<div class="proposal"><b>For your approval</b><p>${esc(p.reason)}</p><ul>${p.changes.map(c=>`<li>${esc(dateLabel(c.date))}: ${c.from} → ${c.to} mi</li>`).join('')}</ul><button type="button" id="approveChange" data-proposal="${esc(p.id)}">Approve this mileage restoration</button></div>`:'';
}
async function action(path,body){
 const response=await fetch(path,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body),cache:'no-store'});
 if(response.status===401){location.replace('/login');return;}
 const result=await response.json();
 if(!response.ok)throw Error(result.error||'Could not save. Try again.');
}
$('checkinForm').addEventListener('input',()=>{editingCheckin=true});
$('checkinForm').addEventListener('submit',async event=>{
 event.preventDefault();$('saveCheckin').disabled=true;
 try{
  await action('/api/checkin',{soreness:Number($('soreness').value),fatigue:Number($('fatigue').value),effort:Number($('effort').value),pain:$('pain').checked});
  editingCheckin=false;await load();$('checkinStatus').textContent='Saved — upcoming workouts reviewed';
 }catch(e){$('checkinStatus').textContent=e.message}finally{$('saveCheckin').disabled=false}
});
$('autoMode').addEventListener('change',async()=>{
 try{await action('/api/adaptive/mode',{enabled:$('autoMode').checked});await load()}
 catch(e){$('checkinStatus').textContent=e.message;await load()}
});
document.querySelector('.coach-panel').addEventListener('click',async event=>{
 const target=event.target.closest('button[data-undo],button[data-proposal]');if(!target)return;
 target.disabled=true;
 try{
  if(target.dataset.undo)await action('/api/adaptive/undo',{revision:Number(target.dataset.undo)});
  else await action('/api/adaptive/approve',{id:target.dataset.proposal});
  await load();
 }catch(e){$('checkinStatus').textContent=e.message;target.disabled=false}
});

'use strict';
let editingCheckin=false;
let hosted=false;
let lastAction=null;
let trainingView="weeks";
let currentWeekNumber=null;
const $=id=>document.getElementById(id);
const esc=s=>String(s??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const miles=m=>m/1609.344;
const pace=s=>!Number.isFinite(s)||s<=0?'—':`${Math.floor(Math.round(s)/60)}:${String(Math.round(s)%60).padStart(2,'0')}`;
const duration=s=>`${Math.floor(s/3600)}h ${Math.floor(s%3600/60)}m`;
const today=()=>new Intl.DateTimeFormat('en-CA',{timeZone:'America/Chicago',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
const dateLabel=s=>new Date(s+'T12:00:00').toLocaleDateString('en-US',{month:'short',day:'numeric'});
function totals(runs){return {distance:runs.reduce((n,r)=>n+r.distance,0),moving:runs.reduce((n,r)=>n+r.moving,0)}}
function activity(r){return `<div class="actual"><a target="_blank" rel="noopener noreferrer" href="https://connect.garmin.com/modern/activity/${encodeURIComponent(r.id)}">${esc(r.name)} ↗</a><div class="metrics"><span>${miles(r.distance).toFixed(2)}<small>MILES</small></span><span>${pace(r.moving/miles(r.distance))}<small>PACE / MI</small></span><span>${duration(r.moving)}<small>MOVING TIME</small></span><span>${duration(r.elapsed)}<small>ELAPSED TIME</small></span><span>${r.hr?Math.round(r.hr):'—'}<small>AVG HR</small></span></div></div>`}
// Derive the displayed sessions from the CURRENT prescription, including recovery edits.
// No separate cached workout schedule can resurrect strength or speed after a reduction.
function sentences(text){return String(text||'').trim().split(/(?<=[.!?])\s+(?=[A-Z0-9])/u).filter(Boolean)}
function runningSteps(text){return sentences(text).flatMap(line=>line.replace(/^\d+(?:\.\d+)? miles total:\s*/,'').split(/,\s*(?:then\s+|(?=\d+(?:\.\d+)?\s+miles?\s+(?:at|easy)))/u))}
function dailyWorkouts(day,weekNumber,strength={}){
 const text=String(day.desc||''),cards=[];
 const active=Number(day.miles)>0;
 const letters=['A','B'].filter(letter=>(new RegExp(`\\bStrength ${letter}\\b`).test(text)||(letter==='B'&&/optional upper-body\/core|brief upper-body\/core/i.test(text)))&&!new RegExp(`(?:no|skip) Strength ${letter}\\b`,'i').test(text));
 let runText=text;
 const canonical=text.search(/\bStrength [AB](?: after [A-Za-z]+)?:/);
 if(canonical>=0)runText=text.slice(0,canonical).trim();
 // A reference to a defined strength session is expanded on that exact day only.
 const strengthCards=letters.map(letter=>{
  const marker=new RegExp(`Strength ${letter}(?: after [A-Za-z]+)?:`);
  const match=text.match(marker);
  const definition=match?text.slice(match.index):String(strength[letter]||'');
  const colon=definition.indexOf(':');
  const parts=sentences(colon>=0?definition.slice(colon+1):definition);
  const coreOnly=letter==='B'&&(day.type==='quality'||/upper-body\/core|upper-body\/core only|upper-body\/core Strength B|upper-body\/core only/i.test(text));
  const taper=/one light set/i.test(text);
  const sets=taper||weekNumber<=3?1:2;
  let moves=(parts[0]||'').replace(/\.$/,'').split(/;\s*|,\s*/).filter(Boolean);
  // New definition uses core/upper work first and labels extra leg work separately.
  const extra=definition.match(/On easy Thursdays only, add one or two sets of ([^.]+)\./);
  if(letter==='B'&&extra&&!coreOnly)moves.push(...extra[1].split(/,\s*(?:and\s+)?/));
  if(letter==='B'&&coreOnly)moves=moves.filter(v=>!/step-up|walkout|calf|Romanian|split squat|glute bridge/i.test(v));
  const notes=[`${sets} ${sets===1?'set':'sets'} per exercise. Stop with 2–3 good repetitions left.`];
  if(letter==='A'&&!taper)notes.push('Progress with a backpack or dumbbells only when the prescribed repetitions stay smooth.');
  if(coreOnly)notes.push('Upper-body and core only today; skip extra leg lifting.');
  if(taper)notes.push('Light maintenance only; avoid lifting fatigue during the taper.');
  if(!moves.length)return {kind:'strength',title:`Strength ${letter}`,optional:/optional/i.test(text),steps:sentences(definition),notes:[]};
  return {kind:'strength',title:`Strength ${letter}${coreOnly?' · upper body + core':''}`,optional:/Strength [AB] is optional|optional upper-body\/core|brief upper-body\/core.*optional/i.test(text),steps:moves,notes};
 });
 // Keep one strength instruction in its own card, rather than repeating it in the run.
 if(strengthCards.length)runText=sentences(runText).filter(t=>!/\bStrength [AB]\b|optional upper-body\/core|skip lower-body strength/i.test(t)).join(' ');
 if(active){
  const stride=runText.match(/If recovered and pain-free, include [^.]+\.\s*Strides[^.]+\./);
  if(stride)runText=runText.replace(stride[0],'').trim();
  const title=String(day.title||'Run').split(' +')[0];
  cards.push({kind:'run',title:title==='Easy'?'Easy run':title,steps:runningSteps(runText),notes:[],pace:day.pace||'',distance:`${day.miles} mi total`});
  if(stride)cards.push({kind:'strides',title:'Relaxed strides',optional:true,steps:sentences(stride[0]),notes:['Included in today’s running mileage; not extra miles.']});
 }else{
  const all=sentences(runText),walk=all.filter(t=>/optional.*walk/i.test(t));
  cards.push({kind:'recovery',title:day.title||'Rest and recovery',steps:all.filter(t=>!walk.includes(t)),notes:[]});
  if(walk.length)cards.push({kind:'walk',title:'Gentle walk',optional:true,steps:walk,notes:[]});
 }
 return [...cards,...strengthCards];
}
function renderWorkouts(day,weekNumber,strength){
 return `<div class="session-list">${dailyWorkouts(day,weekNumber,strength).map((session,index)=>`<section class="session-card session-${esc(session.kind)}"><div class="session-heading"><span class="session-number">${index+1}</span><h5>${esc(session.title)}</h5>${session.optional?'<span class="session-optional">Optional</span>':''}</div>${session.distance?`<p class="session-meta">${esc(session.distance)} · ${esc(session.pace)}</p>`:''}<ul>${session.steps.map(step=>`<li>${esc(step)}</li>`).join('')}</ul>${session.notes.map(note=>`<p class="session-note">${esc(note)}</p>`).join('')}</section>`).join('')}</div>`;
}
function setTrainingView(view){
 trainingView=view;
 $('weeks').hidden=view!=='weeks';$('calendar').hidden=view!=='calendar';
 $('viewWeeks').setAttribute('aria-pressed',String(view==='weeks'));
 $('viewCalendar').setAttribute('aria-pressed',String(view==='calendar'));
}
function showActionNotice(message){$('actionNotice').textContent=message;$('actionNotice').hidden=false;}
function renderTrainingOverview(plan,runs){
 const now=today(),current=plan.weeks.find(w=>w.start<=now&&now<=w.end);
 const all=plan.weeks.flatMap(w=>w.days),first=plan.weeks[0]?.start;
 const plannedToDate=all.filter(d=>d.date<=now).reduce((n,d)=>n+d.miles,0);
 const actualToDate=miles(totals(runs.filter(r=>r.date>=first&&r.date<=now)).distance);
 const weekly=current?miles(totals(runs.filter(r=>r.date>=current.start&&r.date<=current.end)).distance):0;
 const elapsed=plan.weeks.filter(w=>w.end<now).length;
 for(const [key,value,target,label] of [['Week',weekly,current?.total||0,`${weekly.toFixed(1)} / ${current?.total||0}`],['ToDate',actualToDate,plannedToDate,`${actualToDate.toFixed(0)} / ${plannedToDate.toFixed(0)}`],['Progress',elapsed,plan.weeks.length,`${elapsed} / ${plan.weeks.length}`]]){
  const percent=target>0?Math.max(0,Math.min(100,value/target*100)):0;
  $('gauge'+key).style.setProperty('--progress',percent+'%');$('gauge'+key+'Value').textContent=label;
 }
 const days=Math.ceil((Date.parse(plan.race.date+'T12:00:00Z')-Date.parse(now+'T12:00:00Z'))/86400000);
 $('countdown').textContent=`${plan.race.name} · ${plan.race.goal} goal · ${Math.max(0,days)} days to go`;
 const months=new Map();
 for(const day of all){const month=day.date.slice(0,7);if(!months.has(month))months.set(month,[]);months.get(month).push(day);}
 $('calendar').innerHTML='<p class="calendar-help">Select a day to open its workouts. ✓ indicates a Garmin run; orange indicates planned quality or race day.</p>'+[...months].map(([month,days])=>{
  const offset=(new Date(month+'-01T12:00:00').getDay()+6)%7;
  const count=new Date(Number(month.slice(0,4)),Number(month.slice(5,7)),0).getDate();
  const map=new Map(days.map(d=>[Number(d.date.slice(8)),d]));
  return `<article class="calendar-month"><h3>${new Date(month+'-01T12:00:00').toLocaleDateString('en-US',{month:'long',year:'numeric'})}</h3><div class="calendar-grid">${['M','T','W','T','F','S','S'].map(d=>`<span class="calendar-dow">${d}</span>`).join('')}${'<span></span>'.repeat(offset)}${Array.from({length:count},(_,i)=>{
   const d=map.get(i+1);if(!d)return `<span class="calendar-outside">${i+1}</span>`;
   const actual=runs.filter(r=>r.date===d.date),done=miles(totals(actual).distance);
   return `<button type="button" data-day="${d.date}" class="calendar-day ${d.date===now?'is-today':''} ${d.type==='quality'||d.type==='race'?'is-quality':''} ${actual.length?'is-done':''}" aria-label="${esc(dateLabel(d.date)+': '+d.title+', '+d.miles+' planned miles'+(actual.length?', '+done.toFixed(1)+' completed miles':''))}"><small>${i+1}${actual.length?' ✓':''}</small><b>${d.miles||'—'}</b><span>${actual.length?done.toFixed(1)+' done':d.miles?'mi':'rest'}</span></button>`;
  }).join('')}</div></article>`;
 }).join('');
 setTrainingView(trainingView);
}
async function load(){
 $('refresh').disabled=true;
 try{
 const response=await fetch('/api/dashboard',{cache:'no-store'});
 if(response.status===401){location.replace('/login');return;}
 if(!response.ok){const failure=await response.json();throw Error(failure.error||'Could not load your journal. Try refreshing.');}
 const {plan,runs,sync,syncedAt,coach,hosting,actionResults}=await response.json();
 hosted=!!hosting;
 renderCoach(coach);
 if(hosting){
  const failed=(actionResults||[]).find(r=>r.error);
  $('checkinStatus').textContent=hosting.pending?`${hosting.pending} change(s) saved; awaiting the next hourly review.`:failed?failed.error:'Hosted reviews run hourly. Refresh loads the latest saved review.';
  $('coachNote').textContent+=' Hosted changes apply at the next hourly review. If you have pain, pause running now; do not wait for an app update.';
 }
 renderTrainingOverview(plan,runs);
 const current=plan.weeks.find(w=>w.start<=today()&&today()<=w.end);
 currentWeekNumber=current?.week??null;
 const weekRuns=current?runs.filter(r=>r.date>=current.start&&r.date<=current.end):[];
 const sum=totals(weekRuns);
 $('distance').textContent=miles(sum.distance).toFixed(1);
 $('duration').textContent=duration(sum.moving);
 $('pace').textContent=pace(sum.moving/miles(sum.distance));
 $('count').textContent=weekRuns.length;
 $('syncState').textContent=sync.message;
 $('syncTime').textContent=syncedAt?`Last successful sync ${new Date(syncedAt).toLocaleString()} · checks ${hosting?"hourly (schedule may be delayed)":"every 10 minutes"}${sync.deviceFilter?' · '+sync.deviceFilter:''}`:'Waiting for your first Garmin sync. No sample workouts are shown.';
 $('review').textContent=plan.status;
 const open=new Set([...document.querySelectorAll('details[open]')].map(el=>el.id));
 const first=!$('weeks').children.length;
 $('weeks').innerHTML=plan.weeks.map(w=>{
 const wr=runs.filter(r=>r.date>=w.start&&r.date<=w.end),t=totals(wr),actual=miles(t.distance);
 return `<details class="training-week ${w===current?'current-week':''}" id="week-${w.week}" ${(open.has(`week-${w.week}`)||(first&&w===current))?'open':''}><summary><div><span class="week-label">Week ${w.week} · ${esc(w.phase)}</span><span class="week-date">${dateLabel(w.start)} – ${dateLabel(w.end)}</span></div><div class="week-total">${actual.toFixed(1)} / ${w.total} mi<small>${duration(t.moving)} completed · ${wr.length} runs</small></div></summary><div class="progress"><i style="width:${Math.min(100,100*actual/w.total)||0}%"></i></div>${w.days.map(d=>{
 const dr=wr.filter(r=>r.date===d.date);
 return `<div class="day ${d.date===today()?'today':''}" id="day-${d.date}"><div class="date">${new Date(d.date+'T12:00:00').toLocaleDateString('en-US',{weekday:'short'})}<strong>${d.date.slice(8)}</strong></div><div class="workout"><h4>Scheduled workouts</h4>${renderWorkouts(d,w.week,plan.strength)}</div><div class="planned">${d.miles?d.miles+' mi':'Rest'}<small>${d.miles?esc(d.pace):'Recovery matters'}</small></div>${dr.length?dr.map(activity).join(''):`<div class="no-run">${d.date<today()&&d.miles?'No completed run recorded':d.miles?'Planned workout':'Rest day'} </div>`}</div>`}).join('')}</details>`;
 }).join('');
 $('current').onclick=()=>{setTrainingView('weeks');if(current){const el=$(`week-${current.week}`);el.open=true;el.scrollIntoView({behavior:'smooth',block:'start'})}};
 }catch(e){$('syncState').textContent=e.message;}finally{$('refresh').disabled=false;}
}
$('refresh').onclick=load;
load();setInterval(()=>{if(!document.hidden)load()},300000);
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
 lastAction=result;return result;
}
$('checkinForm').addEventListener('input',()=>{editingCheckin=true});
$('checkinForm').addEventListener('submit',async event=>{
 event.preventDefault();$('saveCheckin').disabled=true;
 try{
  await action('/api/checkin',{soreness:Number($('soreness').value),fatigue:Number($('fatigue').value),effort:Number($('effort').value),pain:$('pain').checked});
  editingCheckin=false;await load();$('checkinStatus').textContent=lastAction?.queued?lastAction.message:'Saved — upcoming workouts reviewed';
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
  showActionNotice(lastAction?.queued?'Saved — waiting for the next hosted sync. Run Garmin sync in GitHub Actions for an earlier review.':'Plan change applied.');
 }catch(e){showActionNotice(e.message);$('checkinStatus').textContent=e.message;target.disabled=false}
});

$('viewWeeks').onclick=()=>setTrainingView('weeks');
$('viewCalendar').onclick=()=>setTrainingView('calendar');
$('calendar').addEventListener('click',event=>{
 const button=event.target.closest('button[data-day]');if(!button)return;
 setTrainingView('weeks');const day=$('day-'+button.dataset.day);if(!day)return;
 day.closest('details').open=true;day.scrollIntoView({behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'auto':'smooth',block:'start'});day.setAttribute('tabindex','-1');day.focus({preventScroll:true});
});

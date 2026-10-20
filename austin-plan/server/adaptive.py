"""Conservative, explainable plan adjustments. No external AI or medical inference."""
import copy
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

MILE = 1609.344

def today_local():
    return datetime.now(ZoneInfo('America/Chicago')).date()

def encoded(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'))

def day_map(plan):
    return {d['date']:d for w in plan['weeks'] for d in w['days']}

def recalc(plan):
    for w in plan['weeks']:
        w['total'] = round(sum(d['miles'] for d in w['days']), 2)

def changes(before, after):
    old=day_map(before)
    return [{'date':d['date'],'from':old[d['date']]['miles'],'to':d['miles'],'title':d['title']}
            for d in day_map(after).values() if d != old[d['date']]]

class Planner:
    def __init__(self, store, baseline_path):
        self.store=store
        self.path=baseline_path
        with store.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS coach_state(id INTEGER PRIMARY KEY CHECK(id=1), baseline TEXT, plan TEXT, enabled INTEGER);
            CREATE TABLE IF NOT EXISTS coach_checkins(date TEXT PRIMARY KEY, body TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS coach_events(key TEXT PRIMARY KEY);
            CREATE TABLE IF NOT EXISTS coach_versions(id INTEGER PRIMARY KEY, created TEXT, reason TEXT, source TEXT, before_plan TEXT, after_plan TEXT, changes TEXT);
            ''')

    def _load(self, db):
        base=json.loads(self.path.read_text())
        stamp=hashlib.sha256(encoded(base).encode()).hexdigest()
        row=db.execute('SELECT baseline,plan,enabled FROM coach_state WHERE id=1').fetchone()
        if row is None or row[0]!=stamp:
            enabled=row[2] if row else 1
            db.execute('INSERT OR REPLACE INTO coach_state VALUES (1,?,?,?)',(stamp,encoded(base),enabled))
            return base,copy.deepcopy(base),bool(enabled),stamp
        return base,json.loads(row[1]),bool(row[2]),stamp

    def _record(self, db, before, after, reason, source):
        edits=changes(before,after)
        if not edits:return
        recalc(after)
        db.execute('INSERT INTO coach_versions(created,reason,source,before_plan,after_plan,changes) VALUES (?,?,?,?,?,?)',
                   (datetime.now(timezone.utc).isoformat(),reason,source,encoded(before),encoded(after),encoded(edits)))
        db.execute('UPDATE coach_state SET plan=? WHERE id=1',(encoded(after),))

    def checkin(self, body, today=None):
        today=today or today_local()
        allowed={'soreness','fatigue','effort','pain'}
        if not isinstance(body,dict) or set(body)!=allowed:raise ValueError('Check-in requires soreness, fatigue, effort and pain.')
        for key,upper in [('soreness',5),('fatigue',5),('effort',10)]:
            if type(body[key]) is not int or not 1<=body[key]<=upper:raise ValueError('Check-in score is out of range.')
        if type(body['pain']) is not bool:raise ValueError('Pain must be true or false.')
        with self.store.db() as db:
            db.execute('INSERT OR REPLACE INTO coach_checkins VALUES (?,?)',(today.isoformat(),encoded(body)))
        self.evaluate(today)

    def set_enabled(self, enabled):
        if type(enabled) is not bool:raise ValueError('Enabled must be true or false.')
        with self.store.db() as db:
            self._load(db)
            db.execute('UPDATE coach_state SET enabled=? WHERE id=1',(int(enabled),))

    @staticmethod
    def _ease(day, target, reason):
        # Only reduce mileage. Replace optional quality and strength text as well.
        target=max(0,min(day['miles'],int(target*10)/10))
        day.update(miles=target, type='easy' if target else 'rest', paceKey='easy' if target else None,
                   title='Easy recovery run' if target else 'Rest and recover',
                   pace='Full-sentence conversation; walk breaks allowed' if target else None,
                   desc=reason+' '+('Keep the whole run easy. Skip strides, faster blocks and leg strength today.' if target else 'No replacement workout or catch-up mileage. If pain changes your stride or persists, seek assessment.'))
        if not target:day['cal']=None

    def evaluate(self, today=None):
        today=today or today_local()
        runs=self.store.runs()
        completed={r['date'] for r in runs}
        actual={}
        for r in runs:actual[r['date']]=actual.get(r['date'],0)+r['distance']/MILE
        synced=self.store.meta('syncedAt')
        fresh=False
        try:fresh=abs((datetime.now(timezone.utc)-datetime.fromisoformat(synced)).total_seconds())<86400 and (self.store.meta('sync') or {}).get('state')=='ready'
        except (TypeError,ValueError):pass
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            base,plan,enabled,stamp=self._load(db)
            if not enabled:return
            before=copy.deepcopy(plan);reasons=[]
            def event(key):
                key=stamp+':'+key
                if db.execute('SELECT 1 FROM coach_events WHERE key=?',(key,)).fetchone():return False
                db.execute('INSERT INTO coach_events VALUES (?)',(key,))
                return True
            def future(days=7):
                end=(today+timedelta(days=days)).isoformat()
                return [d for d in day_map(plan).values() if today.isoformat()<=d['date']<=end and d['date'] not in completed and d['type']!='race' and d['miles']>0]
            row=db.execute('SELECT body FROM coach_checkins WHERE date=?',(today.isoformat(),)).fetchone()
            check=json.loads(row[0]) if row else None
            if check:
                if check['pain'] or max(check['soreness'],check['fatigue'])>=4:
                    if event('recover:'+today.isoformat()):
                        reason='Recovery check-in: '+('you reported pain.' if check['pain'] else 'you reported high soreness or fatigue.')
                        for d in future(2):self._ease(d,0,reason)
                        reasons.append(reason+' Next 48 hours of future running are paused; reassess with another check-in.')
                elif max(check['soreness'],check['fatigue'])>=3 or check['effort']>=8:
                    if event('ease:'+today.isoformat()):
                        reason='Recovery check-in suggests extra fatigue.'
                        for d in future(2):self._ease(d,d['miles']*.75,reason)
                        reasons.append(reason+' Next 48 hours reduced by about 25% and kept easy.')
            if fresh:
                # Allow 36 hours after Sunday for delayed uploads before calling a week incomplete.
                prev_start=today-timedelta(days=today.weekday()+7)
                previous=next((w for w in plan['weeks'] if w['start']==prev_start.isoformat()),None)
                grace=today.weekday()>1 or (today.weekday()==1 and datetime.now(ZoneInfo('America/Chicago')).hour>=12)
                if previous and grace:
                    done=sum(v for k,v in actual.items() if previous['start']<=k<=previous['end'])
                    expected=previous['total']
                    if expected>0 and done<expected*.75 and event('consistency:'+previous['start']):
                        remaining=future(6-today.weekday())
                        upcoming=next((w for w in plan['weeks'] if w['start']<=today.isoformat()<=w['end']),None)
                        if upcoming:
                            already=sum(v for k,v in actual.items() if upcoming['start']<=k<=today.isoformat())
                            allowance=max(0,min(upcoming['total'],done+3)-already)
                            total=sum(d['miles'] for d in remaining)
                            if total>allowance:
                                factor=allowance/total if total else 0
                                for d in remaining:self._ease(d,d['miles']*factor,'Last week was below 75% of planned mileage. Rebuild consistency first.')
                                reasons.append('Low completion last week: remaining current-week mileage reduced; no missed runs moved or stacked.')
                # A much longer-than-planned run earns recovery, not more future work.
                originals=day_map(base)
                for r in runs:
                    age=(today-date.fromisoformat(r['date'])).days
                    planned=originals.get(r['date'],{}).get('miles',0)
                    extra=r['distance']/MILE-max(planned,0)
                    if 0<=age<=1 and (r['moving']>9900 or (planned>0 and extra>=2 and r['distance']/MILE>planned*1.25)):
                        if event('long-recovery:'+str(r['id'])):
                            for d in future(2):self._ease(d,d['miles']*.75,'A recent run was unusually long relative to the plan.')
                            reasons.append('Extra recovery after a substantially longer run: next 48 hours eased.')
                # Don't let the next long run jump far beyond demonstrated recent distance.
                history=[r['distance']/MILE for r in runs if 0<=(today-date.fromisoformat(r['date'])).days<=28]
                if history:
                    cap=max(history)+1
                    for d in future(7):
                        if ('long' in d['title'].lower() or d['type']=='long') and d['miles']>cap+.1 and event('long-cap:'+d['date']):
                            self._ease(d,cap,'Long run capped at one mile beyond your longest completed run in the past 28 days.')
                            reasons.append('Upcoming long run capped to recent completed distance + 1 mile.')
            self._record(db,before,plan,' '.join(reasons),'automatic')

    def _proposal(self, db, base, plan, today, runs):
        checkrow=db.execute('SELECT body FROM coach_checkins WHERE date>=? ORDER BY date DESC LIMIT 1',((today-timedelta(days=2)).isoformat(),)).fetchone()
        if not checkrow:return None
        check=json.loads(checkrow[0])
        if check['pain'] or max(check['soreness'],check['fatigue'])>2:return None
        prior=[w for w in plan['weeks'] if w['end']<today.isoformat() and not any(d['type']=='race' for d in w['days'])][-2:]
        if len(prior)<2:return None
        for week in prior:
            done=sum(r['distance']/MILE for r in runs if week['start']<=r['date']<=week['end'])
            if not week['total'] or done<week['total']*.9:return None
        race=date.fromisoformat(base['race']['date'])
        # Never restore mileage in the final three weeks; never change race goal or intensity.
        after=copy.deepcopy(plan);bmap=day_map(base);completed={r['date'] for r in runs}
        for week in after['weeks']:
            if not today.isoformat()<week['start']<=(today+timedelta(days=7)).isoformat():continue
            if date.fromisoformat(week['start'])>=race-timedelta(days=21):continue
            budget=round(week['total']*.05,1)
            for day in week['days']:
                original=bmap[day['date']]
                if day['date'] in completed or not day['miles'] or original['miles']<=day['miles']:continue
                add=min(budget,round(original['miles']-day['miles'],1))
                if add<.1:continue
                day['miles']=round(day['miles']+add,1)
                day['desc']='Approved small mileage restoration toward the original plan. Keep this run easy; no added speed or leg-strength work.'
                budget=round(budget-add,1)
                if budget<.1:break
        recalc(after)
        edits=changes(plan,after)
        if not edits:return None
        ident=hashlib.sha256((encoded(plan)+encoded(after)).encode()).hexdigest()
        return {'id':ident,'reason':'Two consistent weeks and a low-fatigue check-in support restoring up to 5% of a reduced week, within the original plan.','changes':edits,'plan':after}

    def snapshot(self, today=None):
        today=today or today_local();runs=self.store.runs()
        with self.store.db() as db:
            base,plan,enabled,_=self._load(db)
            history=[dict(id=r[0],created=r[1],reason=r[2],source=r[3],changes=json.loads(r[4])) for r in db.execute('SELECT id,created,reason,source,changes FROM coach_versions ORDER BY id DESC LIMIT 12')]
            row=db.execute('SELECT body FROM coach_checkins WHERE date=?',(today.isoformat(),)).fetchone()
            proposal=self._proposal(db,base,plan,today,runs) if enabled else None
        if proposal:proposal={k:v for k,v in proposal.items() if k!='plan'}
        return {'plan':plan,'enabled':enabled,'history':history,'proposal':proposal,'checkin':json.loads(row[0]) if row else None,
                'note':'Automatic changes only reduce upcoming work. Heart rate and pace alone do not diagnose recovery. Race day and completed workouts are protected.'}

    def approve(self, ident, today=None):
        today=today or today_local()
        fresh=self.store.meta('syncedAt')
        try:valid=(datetime.now(timezone.utc)-datetime.fromisoformat(fresh)).total_seconds()<86400
        except (TypeError,ValueError):valid=False
        if not valid or (self.store.meta('sync') or {}).get('state')!='ready':raise ValueError('A recent successful Garmin sync is required before restoring mileage.')
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            base,plan,enabled,_=self._load(db)
            p=self._proposal(db,base,plan,today,self.store.runs()) if enabled else None
            if not p or p['id']!=ident:raise ValueError('This suggestion has changed. Refresh and review it again.')
            self._record(db,plan,p['plan'],p['reason'],'approved')

    def undo(self, revision, today=None):
        today=today or today_local();completed={r['date'] for r in self.store.runs()}
        with self.store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            base,plan,_,_=self._load(db)
            row=db.execute('SELECT id,before_plan,after_plan,source FROM coach_versions ORDER BY id DESC LIMIT 1').fetchone()
            if not row or row[0]!=revision or row[3]=='undo':raise ValueError('Only the most recent change can be undone.')
            # Reject revisions from an older baseline after a manual plan replacement.
            if encoded(plan)!=row[2]:raise ValueError('The plan has changed since that revision.')
            restored=json.loads(row[1]);old=day_map(plan)
            for w in restored['weeks']:
                for i,d in enumerate(w['days']):
                    if d['date']<today.isoformat() or d['date'] in completed or d['type']=='race':w['days'][i]=copy.deepcopy(old[d['date']])
            self._record(db,plan,restored,'Undid the latest adjustment for future, uncompleted workouts only.','undo')

import copy
import io
import json
import os
import tempfile
import unittest
from datetime import date,datetime,timezone
from pathlib import Path
from unittest.mock import patch
os.environ['BACKGROUND_ENABLED']='0'
os.environ['SYNC_ENABLED']='0'
_import_tmp=tempfile.TemporaryDirectory()
os.environ['DATA_DIR']=_import_tmp.name
from server.core import Store,Sync,compact,password_hash
from server.adaptive import Planner,day_map,encoded
from server.app import App
from server.core import ROOT

class Tests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.store=Store(Path(self.tmp.name)/'data')
  self.file=Path(self.tmp.name)/'plan.json';self.file.write_bytes((ROOT/'public/plan.json').read_bytes())
  self.planner=Planner(self.store,self.file);self.base=json.loads(self.file.read_text())
  self.today=date(2026,11,4)
 def tearDown(self):self.tmp.cleanup()
 def add_run(self,id,day,miles=3,moving=1800):
  self.store.upsert([{'id':str(id),'date':day,'start':day+' 12:00:00','distance':miles*1609.344,'moving':moving,'elapsed':moving,'hr':145}])
 def fresh(self):
  self.store.meta('syncedAt',datetime.now(timezone.utc).isoformat());self.store.meta('sync',{'state':'ready'})
 def check(self,**overrides):return dict(soreness=1,fatigue=1,effort=3,pain=False,**overrides)
 def savecheck(self,sore=1,fatigue=1,effort=3,pain=False,today=None):self.planner.checkin(dict(soreness=sore,fatigue=fatigue,effort=effort,pain=pain),today or self.today)
 def test_default_does_not_change_without_evidence(self):
  self.planner.evaluate(self.today);self.assertEqual(self.planner.snapshot(self.today)['plan'],self.base)
 def test_soreness_reduces_and_removes_quality(self):
  self.savecheck(sore=3)
  d=day_map(self.planner.snapshot(self.today)['plan'])['2026-11-05'];self.assertEqual(d['miles'],3);self.assertEqual(d['type'],'easy');self.assertNotIn('Strength B:',d['desc'])
 def test_pain_pauses_next_48_hours(self):
  self.savecheck(pain=True)
  self.assertEqual(day_map(self.planner.snapshot(self.today)['plan'])['2026-11-05']['miles'],0)
 def test_repeated_evaluation_does_not_compound(self):
  self.savecheck(sore=3);before=self.planner.snapshot(self.today)
  self.planner.evaluate(self.today);self.savecheck(sore=3)
  after=self.planner.snapshot(self.today)
  self.assertEqual(before['plan'],after['plan']);self.assertEqual(len(before['history']),len(after['history']))
 def test_past_and_completed_workouts_protected(self):
  self.add_run(1,'2026-11-05',4);self.savecheck(pain=True)
  p=day_map(self.planner.snapshot(self.today)['plan']);b=day_map(self.base)
  self.assertEqual(p['2026-11-05'],b['2026-11-05']);self.assertEqual(p['2026-11-03'],b['2026-11-03'])
 def test_race_and_goal_protected(self):
  self.savecheck(pain=True,today=date(2027,2,13))
  p=self.planner.snapshot(date(2027,2,13))['plan'];self.assertEqual(p['race'],self.base['race']);self.assertEqual(day_map(p)['2027-02-14'],day_map(self.base)['2027-02-14'])
 def test_pause_mode(self):
  self.planner.set_enabled(False);self.savecheck(pain=True)
  self.assertEqual(self.planner.snapshot(self.today)['plan'],self.base)
 def test_undo_restores_future_without_reapplying_event(self):
  self.savecheck(sore=3);snap=self.planner.snapshot(self.today);self.planner.undo(snap['history'][0]['id'],self.today)
  self.planner.evaluate(self.today);self.assertEqual(self.planner.snapshot(self.today)['plan'],self.base)
 def test_undo_rejects_stale_revision(self):
  with self.assertRaises(ValueError):self.planner.undo(999,self.today)
 def test_invalid_checkin_is_rejected(self):
  for value in [True,0,6,'3',None]:
   with self.assertRaises(ValueError):self.planner.checkin(dict(soreness=value,fatigue=1,effort=3,pain=False),self.today)
 def test_no_automatic_increases(self):
  self.fresh();self.add_run(1,'2026-11-03',10,moving=11000);self.planner.evaluate(self.today)
  for key,d in day_map(self.planner.snapshot(self.today)['plan']).items():self.assertLessEqual(d['miles'],day_map(self.base)[key]['miles'])
 def test_stale_sync_does_not_treat_missing_runs_as_missed(self):
  self.store.meta('syncedAt','2020-01-01T00:00:00+00:00');self.store.meta('sync',{'state':'ready'});self.planner.evaluate(self.today)
  self.assertEqual(self.planner.snapshot(self.today)['plan'],self.base)
 def test_low_completion_limits_current_week(self):
  self.add_run(1,'2026-10-31',5);self.fresh();self.planner.evaluate(self.today)
  snap=self.planner.snapshot(self.today)
  self.assertTrue(any('Low completion' in h['reason'] for h in snap['history']))
  self.assertLess(next(w['total'] for w in snap['plan']['weeks'] if w['start']=='2026-11-02'),18)
 def test_excessively_long_run_adds_recovery(self):
  self.add_run(1,'2026-11-03',10,11000);self.fresh();self.planner.evaluate(self.today)
  self.assertTrue(any('Extra recovery' in h['reason'] for h in self.planner.snapshot(self.today)['history']))
 def test_long_run_capped_to_recent_history(self):
  self.add_run(1,'2026-10-30',3);self.fresh();self.planner.evaluate(self.today)
  self.assertLessEqual(day_map(self.planner.snapshot(self.today)['plan'])['2026-11-07']['miles'],4)
 def test_week_totals_are_recomputed(self):
  self.savecheck(sore=3)
  for w in self.planner.snapshot(self.today)['plan']['weeks']:self.assertAlmostEqual(w['total'],sum(d['miles'] for d in w['days']))
 def test_persistence_across_restart(self):
  self.savecheck(pain=True)
  self.assertEqual(Planner(Store(Path(self.tmp.name)/'data'),self.file).snapshot(self.today)['plan'],self.planner.snapshot(self.today)['plan'])
 def test_manual_baseline_replacement_resets_only_active_plan(self):
  self.savecheck(sore=3);b=copy.deepcopy(self.base);b['status']='Updated baseline';self.file.write_text(json.dumps(b))
  self.assertEqual(self.planner.snapshot(self.today)['plan'],b)
  self.assertTrue(self.planner.snapshot(self.today)['history'])
 def make_proposal(self):
  self.planner.snapshot(self.today)
  for w in self.base['weeks']:
   if w['start'] in ['2026-10-19','2026-10-26']:
    for d in w['days']:
     if d['miles']:self.add_run(d['date'],d['date'],d['miles'])
  self.savecheck()
  plan=copy.deepcopy(self.base)
  for d in next(w for w in plan['weeks'] if w['start']=='2026-11-09')['days']:
   if d['miles']:d['miles']=round(d['miles']*.8,1)
  from server.adaptive import recalc
  recalc(plan)
  with self.store.db() as db:db.execute('UPDATE coach_state SET plan=? WHERE id=1',(encoded(plan),))
  self.fresh();return self.planner.snapshot(self.today)
 def test_restoration_requires_approval_and_stays_within_ceiling(self):
  snap=self.make_proposal();p=snap['proposal'];self.assertIsNotNone(p)
  self.assertEqual(next(w['total'] for w in snap['plan']['weeks'] if w['start']=='2026-11-09'),16)
  self.planner.approve(p['id'],self.today)
  after=self.planner.snapshot(self.today)['plan']
  self.assertLessEqual(next(w['total'] for w in after['weeks'] if w['start']=='2026-11-09'),16.8)
  for key,d in day_map(after).items():self.assertLessEqual(d['miles'],day_map(self.base)[key]['miles'])
 def test_approval_rejects_stale_identifier(self):
  self.make_proposal()
  with self.assertRaises(ValueError):self.planner.approve('bad-id',self.today)
 def test_no_restoration_in_taper(self):
  snap=self.make_proposal();self.assertIsNone(self.planner.snapshot(date(2027,2,2))['proposal'])
 def request(self,path,method='GET',body=None,token='',origin='http://127.0.0.1:8765'):
  app=App(self.store);app.planner=self.planner
  data=json.dumps(body or {}).encode();capture={}
  env={'PATH_INFO':path,'REQUEST_METHOD':method,'HTTP_ORIGIN':origin,'HTTP_COOKIE':'session='+token,'CONTENT_LENGTH':str(len(data)),'wsgi.input':io.BytesIO(data)}
  def respond(status,headers):capture.update(status=status,headers=dict(headers))
  capture['body']=b''.join(app(env,respond));return capture
 def test_checkin_requires_authentication(self):self.assertEqual(self.request('/api/checkin','POST')['status'],'401 Unauthorized')
 def test_csrf_null_and_external_rejected(self):
  for origin in ['null','https://other.example','']:
   self.assertEqual(self.request('/api/checkin','POST',token=self.store.session(),origin=origin)['status'],'403 Forbidden')
 def test_referrer_header_fixed(self):self.assertEqual(self.request('/login')['headers']['Referrer-Policy'],'same-origin')
 def test_authenticated_checkin_and_dashboard(self):
  token=self.store.session();r=self.request('/api/checkin','POST',dict(soreness=2,fatigue=2,effort=3,pain=False),token)
  self.assertEqual(r['status'],'200 OK')
  body=json.loads(self.request('/api/dashboard',token=token)['body']);self.assertIn('coach',body);self.assertEqual(body['plan']['race']['goal'],'3:40:00')
 def test_private_source_not_served(self):self.assertEqual(self.request('/../server/core.py',token=self.store.session())['status'],'404 Not Found')
 def test_sync_deduplicates_and_preserves_original_fields(self):
  raw={'activityId':1,'startTimeLocal':'2026-10-20 10:00:00','activityType':{'typeKey':'running'},'distance':5000,'duration':1800,'averageHR':140}
  class Client:
   def get_activities(self,*args):return [raw]
  sync=Sync(self.store,Client);sync.once();sync.once();self.assertEqual(len(self.store.runs()),1);self.assertEqual(self.store.runs()[0]['hr'],140)

if __name__=='__main__':unittest.main()

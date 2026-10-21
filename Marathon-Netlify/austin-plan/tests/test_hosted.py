import base64
import copy
import os
from pathlib import Path
import tempfile
import unittest
from datetime import timedelta
from server.core import ROOT, Store
from server.adaptive import Planner, today_local, day_map
from server.hosted_worker import seal, unseal, pack, restore, process
from cryptography.exceptions import InvalidTag

class HostedTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.store=Store(Path(self.temp.name)/'source');self.key=base64.b64encode(os.urandom(32)).decode()
    def command(self,ident='a',pain=False,date=None):
        return {'id':ident,'path':'/api/checkin','body':{'soreness':2,'fatigue':2,'effort':3,'pain':pain},'date':date or today_local().isoformat(),'created':'2026-10-21T12:00:00Z'}
    def test_encryption_roundtrip_and_tamper(self):
        payload={'secret':'not public'};sealed=seal(payload,self.key)
        self.assertNotIn('not public',sealed);self.assertEqual(payload,unseal(sealed,self.key))
        raw=bytearray(base64.b64decode(sealed));raw[-1]^=1
        with self.assertRaises(InvalidTag):unseal(base64.b64encode(raw).decode(),self.key)
    def test_restore_keeps_activity_and_token_and_rejects_traversal(self):
        self.store.upsert([{'id':'1','start':'2026-10-20','date':'2026-10-20','distance':1}])
        tokens=self.store.directory/'garmin';tokens.mkdir();(tokens/'oauth.json').write_text('{"test":"secret"}')
        payload=unseal(seal(pack(self.store),self.key),self.key)
        target=restore(payload,Path(self.temp.name)/'restored')
        self.assertEqual(target.runs(),self.store.runs());self.assertEqual((target.directory/'garmin/oauth.json').read_text(),'{"test":"secret"}')
        payload['tokens']['../bad.json']='e30='
        with self.assertRaises(ValueError):restore(payload,Path(self.temp.name)/'bad')
    def test_commands_replay_safe(self):
        commands=[self.command(pain=True)]
        first=process(self.store,commands,sync=False)
        second=process(self.store,commands,sync=False)
        self.assertEqual(first['plan'],second['plan']);self.assertEqual(first['coach']['history'],second['coach']['history'])
        self.assertEqual(len(second['actionResults']),1)
    def test_yesterday_checkin_does_not_modify_past(self):
        planner=Planner(self.store,ROOT/'public/plan.json');before=copy.deepcopy(planner.snapshot()['plan'])
        yesterday=(today_local()-timedelta(days=1)).isoformat()
        result=process(self.store,[self.command(pain=True,date=yesterday)],sync=False)
        for date,day in day_map(before).items():
            if date<today_local().isoformat():self.assertEqual(day,day_map(result['plan'])[date])
        self.assertEqual(before,result['plan'])
    def test_invalid_proposal_records_safe_failure_without_losing_other_actions(self):
        invalid={'id':'invalid','path':'/api/adaptive/approve','body':{'id':'f'*64},'date':today_local().isoformat(),'created':'x'}
        result=process(self.store,[invalid,self.command()],sync=False)
        self.assertTrue(result['actionResults'][0]['error']);self.assertIsNone(result['actionResults'][1]['error'])
        self.assertIsNotNone(result['coach']['checkin'])

if __name__=='__main__':unittest.main()

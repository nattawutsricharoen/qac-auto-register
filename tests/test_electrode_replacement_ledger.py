import tempfile
import unittest
from pathlib import Path
from app.electrode_replacement import ReplacementStore,ReplacementError

class TestReplacementLedger(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.db=Path(self.tmp.name)/'electrode.sqlite'
        self.store=ReplacementStore(self.db)
        self.slot=next(r for r in self.store.slots() if r['machine']=='Gas Filling' and r['station']=='Station 2' and r['diameter']=='25' and r['position']=='SealHead')
    def tearDown(self):self.tmp.cleanup()
    def test_seed_and_common(self):
        self.assertEqual(len(self.store.slots()),46)
        self.assertEqual(len([r for r in self.store.slots() if r['machine']=='Gas Filling']),24)
        self.assertEqual(len([r for r in self.store.slots() if r['diameter']=='Common']),2)
    def test_install_replace_reopen_and_exports(self):
        self.store.first_install(self.slot['id'],'GF-001',0,'12338')
        self.store.replace(self.slot['id'],'GF-001',1234,'GF-002',15,'12338','worn')
        reopened=ReplacementStore(self.db)
        cur=next(r for r in reopened.current() if r['id']==self.slot['id'])
        self.assertEqual((cur['electrode_no'],cur['start_counter']),('GF-002',15))
        hist=reopened.history()[0]
        self.assertEqual((hist['old_no'],hist['final_counter'],hist['usage_count']),('GF-001',1234,1234))
        reopened.export_csv(Path(self.tmp.name)/'out.csv')
        reopened.export_xlsx(Path(self.tmp.name)/'out.xlsx')
        self.assertTrue((Path(self.tmp.name)/'out.xlsx').stat().st_size>100)
    def test_atomic_validation_and_stale_update(self):
        self.store.first_install(self.slot['id'],'GF-001',100,'12338')
        for args in [('GF-001',99,'GF-002',0),('BAD',150,'GF-002',0),('GF-001',150,'GF-001',0)]:
            with self.assertRaises(ReplacementError):self.store.replace(self.slot['id'],*args,actor='12338')
        self.assertEqual(len(self.store.history()),0)
        self.assertEqual(next(r for r in self.store.current() if r['id']==self.slot['id'])['electrode_no'],'GF-001')
    def test_toggle_and_add(self):
        self.store.set_slot(self.slot['id'],False,True)
        with self.assertRaises(ReplacementError):self.store.first_install(self.slot['id'],'GF-001',0,'12338')
        self.store.add_slot('New Machine','','Upper','Common')
        self.assertEqual(len(self.store.slots()),47)

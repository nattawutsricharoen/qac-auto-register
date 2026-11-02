import tempfile
import unittest
from pathlib import Path
from app.daily_scan_checkpoint import DailyScanCheckpoint


def doc(line='TS1-Sub', model='S91', name='TS1-Sub_S91_Daily'):
    return dict(line=line, model=model, document_name=name, document_no='FOPI-001')


class IndependentCheckpointTests(unittest.TestCase):
    def test_target_survives_reference_failure_and_restart(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=Path(tmp)/'ckpt.sqlite3'
            a=DailyScanCheckpoint(db)
            a.save('TARGET',doc(),'2026-10-21','1330240',[{'item':'1','slots':[{'number':1,'status':'EMPTY'}]}])
            b=DailyScanCheckpoint(db)
            self.assertIsNotNone(b.load('TARGET',doc(),'2026-10-21','1330240'))
            self.assertIsNone(b.load('REFERENCE',doc(),'2026-10-20','1329322'))
            b.save('REFERENCE',doc(),'2026-10-20','1329322',[{'item':'1','slots':[{'number':1,'status':'SAVED','value':'-0.01'}]}])
            self.assertEqual(b.load('REFERENCE',doc(),'2026-10-20','1329322')['items'][0]['slots'][0]['value'],'-0.01')
            self.assertEqual(b.load('TARGET',doc(),'2026-10-21','1330240')['items'][0]['slots'][0]['status'],'EMPTY')

    def test_line_model_date_task_isolation(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=DailyScanCheckpoint(Path(tmp)/'ckpt.db')
            db.save('TARGET',doc(),'2026-10-21','100',[{'item':'1'}])
            for d,date,task in [(doc('TS2-Sub'),'2026-10-21','100'), (doc(model='S92'),'2026-10-21','100'),(doc(),'2026-10-22','100'),(doc(),'2026-10-21','101')]:
                self.assertIsNone(db.load('TARGET',d,date,task))

    def test_all_model_same_line_only(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=DailyScanCheckpoint(Path(tmp)/'ckpt.db')
            db.save('REFERENCE',doc(model='S91',name='TS1-Sub_All Model_Cleaning'),'2026-10-20','42',[{'item':'1'}])
            self.assertIsNotNone(db.load('REFERENCE',doc(model='S92',name='TS1-Sub_All Model_Cleaning'),'2026-10-20','42'))
            self.assertIsNone(db.load('REFERENCE',doc(line='TS2-Sub',model='S92',name='TS1-Sub_All Model_Cleaning'),'2026-10-20','42'))

    def test_no_unknown_model_or_empty_data(self):
        with tempfile.TemporaryDirectory() as tmp:
            db=DailyScanCheckpoint(Path(tmp)/'ckpt.db')
            with self.assertRaises(ValueError): db.save('TARGET',doc(model=''),'2026-10-21','1',[{'item':'1'}])
            with self.assertRaises(ValueError): db.save('TARGET',doc(),'2026-10-21','1',[])
            with self.assertRaises(ValueError): db.save('TARGET',doc(),'2026-10-21','',[{'item':'1'}])

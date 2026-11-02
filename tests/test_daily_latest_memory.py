import tempfile
import unittest
from pathlib import Path
from app.daily_latest_memory import DailyLatestMemory, memory_identity

class LatestMemoryTests(unittest.TestCase):
    def base(self, name='TS1-Sub_S91_Check', model='S91'):
        return {'line':'TS1-Sub','document_no':'D001','document_name':name,'model':model}
    def test_model_isolated(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DailyLatestMemory(Path(tmp)/'latest.db')
            s91=self.base();s92=self.base(model='S92')
            store.confirmed(s91,1,1,'0.52','R1')
            self.assertFalse(store.read(s92))
    def test_all_model_shared(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DailyLatestMemory(Path(tmp)/'latest.db')
            a=self.base('TS1-Sub_All Model_Cleaning','S91')
            b=self.base('TS1-Sub_All Model_Cleaning','S92')
            store.confirmed(a,'123',1,'OK','R1')
            self.assertEqual(store.read(b)[('123',1)]['value'],'OK')
    def test_replace_only_latest(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DailyLatestMemory(Path(tmp)/'latest.db');d=self.base()
            store.confirmed(d,1,1,'0.52','R1')
            store.confirmed(d,1,1,'0.54','R2')
            result=store.read(d)
            self.assertEqual(len(result),1)
            self.assertEqual(result[('1',1)]['result_id'],'R2')
    def test_unconfirmed_never_saved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=DailyLatestMemory(Path(tmp)/'latest.db');d=self.base()
            with self.assertRaises(ValueError): store.confirmed(d,1,1,'NG','')
            self.assertFalse(store.read(d))
    def test_unknown_model_never_crosses(self):
        with self.assertRaises(ValueError): memory_identity(self.base(model=''))

if __name__=='__main__': unittest.main()

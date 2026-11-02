import tempfile
import unittest
from pathlib import Path
from app.electrode_replacement import ReplacementStore, ReplacementError

class ShotTests(unittest.TestCase):
    def test_shot_persist_and_new_electrode_reset(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'db.sqlite'
            store=ReplacementStore(path)
            slot=next(x for x in store.slots() if x['machine']=='Gas Filling' and x['station']=='Station 3' and x['diameter']=='20')
            sid=slot['id']
            store.first_install(sid,'OLD',0,'OP01')
            store.record_shot(sid,'OLD',100,'OP01')
            self.assertEqual(next(x for x in ReplacementStore(path).current() if x['id']==sid)['current_shot'],100)
            with self.assertRaises(ReplacementError):store.record_shot(sid,'OLD',99,'OP01')
            store.replace(sid,'OLD',120,'NEW',0,'OP01')
            current=next(x for x in ReplacementStore(path).current() if x['id']==sid)
            self.assertEqual((current['electrode_no'],current['current_shot']),('NEW',0))
            self.assertEqual(len(store.shot_history()),3)
            store.export_xlsx(Path(td)/'history.xlsx')
            self.assertTrue((Path(td)/'history.xlsx').exists())

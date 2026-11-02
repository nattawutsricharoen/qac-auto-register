import unittest
from app.core.local_connection import LocalConnection
from app.core.reference_date import ReferenceDateHub
from app.modules.auto_register import AutoRegisterState

class TestRefactorContracts(unittest.TestCase):
    def test_local_ready_does_not_launch_or_scan(self):
        calls=[]
        manager=LocalConnection(ready=lambda endpoint: True, launch=lambda cfg,url: calls.append('launch'))
        self.assertTrue(manager.ensure({'cdp_url':'http://127.0.0.1:9222'}, 'http://qac').ok)
        self.assertEqual(calls, [])

    def test_local_missing_launches_once(self):
        states=iter([False, True]); launches=[]
        manager=LocalConnection(ready=lambda ep: next(states), launch=lambda cfg,url: (launches.append(url) or True,'started'))
        r=manager.ensure({'cdp_url':'http://127.0.0.1:9222'}, 'http://qac')
        self.assertTrue(r.ok); self.assertTrue(r.started); self.assertEqual(launches,['http://qac'])

    def test_ref_date_independent_override(self):
        hub=ReferenceDateHub();hub.subscribe('daily');hub.subscribe('sample')
        hub.publish('2026-10-20');hub.set_module_date('sample','2026-10-19');hub.publish('2026-10-21')
        self.assertEqual(hub.date_for('sample'),'2026-10-19')
        self.assertEqual(hub.date_for('daily'),'2026-10-21')

    def test_register_never_scans(self):
        state=AutoRegisterState();state.accept_explicit_scan(['doc1']);state.start_registration()
        with self.assertRaises(RuntimeError): state.accept_explicit_scan(['doc2'])
        self.assertEqual(state.documents,('doc1',))
        state.finish_registration()

if __name__=='__main__': unittest.main()

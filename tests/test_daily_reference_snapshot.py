import tempfile
import unittest
from pathlib import Path
from app.daily_reference_snapshot import DailyReferenceSnapshot

class TestReferenceSnapshot(unittest.TestCase):
    def test_snapshot_persists_full_html_and_values_before_close(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'ref.sqlite3'
            store = DailyReferenceSnapshot(path)
            rid = store.save(target_task='1327891',reference_task='1325693',requested_date='2026-10-15',
                document_name='Cleaning',expected_document_no='x',identity_verified=False,
                page_url='about:blank',rendered_html='<table><tr><td>OK</td></tr></table>',
                visible_values=[{'cells':['OK']}],results=[])
            with store._connect() as db:
                row = db.execute('SELECT identity_verified,rendered_html,visible_values_json FROM daily_reference_snapshots WHERE id=?',(rid,)).fetchone()
            self.assertEqual(row[0],0)
            self.assertIn('<td>OK</td>',row[1])
            self.assertIn('OK',row[2])

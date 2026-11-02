"""Offline architecture contracts for the Sample/Register phase-2 migration."""
from pathlib import Path
import unittest
from app.core.reference_date import ReferenceDateHub

MAIN = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')

class SampleIsolationTests(unittest.TestCase):
    def test_sample_line_is_owned_by_sample_tab(self):
        start=MAIN.index('    def sample_prepare(self):')
        stop=MAIN.index('    def _sample_prepare_completed(', start)
        self.assertNotIn('self._auto_register_line()', MAIN[start:stop])
        self.assertIn('line=self._sample_line()', MAIN[start:stop])

    def test_auto_document_change_never_changes_sample_selection(self):
        start=MAIN.index('    def document_changed(self, index):')
        stop=MAIN.index('    def ', start+8)
        self.assertNotIn('self._refresh_sample_document_options()', MAIN[start:stop])

    def test_register_actions_have_no_full_scan(self):
        for name in ('run_register', 'sample_register_execute', 'sample_prepare'):
            start=MAIN.index('    def '+name+'(self):')
            stop=MAIN.index('    def ',start+8)
            body=MAIN[start:stop]
            self.assertNotIn('self.scan_tabs(',body)
            self.assertNotIn('self._start_scan_tabs_worker(',body)
            self.assertIn('self._ensure_local_action(',body)

    def test_date_override_survives_new_document(self):
        hub=ReferenceDateHub()
        hub.subscribe('sample_register');hub.subscribe('daily_document')
        hub.publish('2026-10-20')
        hub.set_module_date('sample_register','2026-10-18')
        hub.publish('2026-10-21')
        self.assertEqual(hub.date_for('sample_register'),'2026-10-18')
        self.assertEqual(hub.date_for('daily_document'),'2026-10-21')

if __name__=='__main__':unittest.main()

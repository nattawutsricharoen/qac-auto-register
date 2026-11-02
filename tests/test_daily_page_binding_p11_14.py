import unittest
from app.qac_session import is_trusted_qac_url
from app.daily_slot_memory import DailySlotMemory
from pathlib import Path
from tempfile import TemporaryDirectory

class QACDailySafetyTests(unittest.TestCase):
    def test_allow_actual_qac_origin(self):
        self.assertTrue(is_trusted_qac_url('http://159.228.251.234:8077/app/view/measure.html'))
    def test_no_external_tab_adoption(self):
        for url in ('https://example.org/', 'http://159.228.251.234:8080/',
                    'https://159.228.251.234:8077/', 'http://159.228.251.234:8077.evil.test/', ''):
            with self.subTest(url=url):
                self.assertFalse(is_trusted_qac_url(url))
    def test_numeric_slot_presets_are_exact_and_isolated(self):
        with TemporaryDirectory() as tmp:
            store=DailySlotMemory(Path(tmp)/'test.sqlite3')
            d={'document_name':'TS1 Day','line':'TS1','model':'All'}
            store.save(d,{'411398':{'1':'VALUE:8.00','2':'VALUE:10.00','3':'VALUE:12.10'},'411400':{'1':'OK'}})
            self.assertEqual(store.load(d)['411398'],{'1':'VALUE:8.00','2':'VALUE:10.00','3':'VALUE:12.10'})
            self.assertEqual(store.load({**d,'document_name':'TS1 Night'}),{})
if __name__=='__main__': unittest.main()

import unittest
from app.daily_slot_schema import validate_daily_slot_plan, validate_qac_numeric_choice
from app.qac_task_scan import scan_qac_documents_async
from app.daily_document import open_daily_measure_async

class NumericStrict(unittest.TestCase):
    def setUp(self):
        self.schema=[{'item':'7','format':'1','options':['VALUE'],'slots':[{'number':1,'saved':False,'status':'EMPTY'},{'number':2,'saved':False,'status':'EMPTY'}]}]
    def test_finite_decimals_keep_exact_precision(self):
        for v in ['-0.01','0.533','0','8.00','-0.0001','0.000','1.234567','+12.0','.5','-.01']:
            with self.subTest(value=v):
                self.assertEqual(validate_qac_numeric_choice('VALUE:'+v),v)
                validate_daily_slot_plan(self.schema,{'7':{'2':'VALUE:'+v}})
    def test_invalids_block_preflight(self):
        for v in ['abc','NaN','Infinity','-Infinity','1e309','1,00','1 0','', ' 2', '2 ', '1..1']:
            with self.subTest(value=v):
                with self.assertRaises(ValueError):
                    validate_daily_slot_plan(self.schema,{'7':{'1':'VALUE:'+v}})
    def test_not_shift_selected_slots(self):
        validate_daily_slot_plan(self.schema,{'7':{'2':'VALUE:-0.01'}})

class SearchAndEditStructure(unittest.TestCase):
    def test_scan_includes_adjacent_monitor_windows_but_exact_lot(self):
        import inspect
        source=inspect.getsource(scan_qac_documents_async)
        self.assertIn('(selected_day - timedelta(days=1)).isoformat()',source)
        self.assertIn('(selected_day + timedelta(days=1)).isoformat()',source)
        self.assertIn("r.get('lot')",source)
        self.assertIn('if index in found_by_doc:',source)
    def test_edit_opens_dropdown_and_checks_date(self):
        import inspect
        source=inspect.getsource(open_daily_measure_async)
        self.assertIn('_click_measure_action(page, task_id',source)
        self.assertIn('verify_daily_measure_identity(page',source)
        self.assertIn("r.get('lot')",source)
if __name__=='__main__':unittest.main()

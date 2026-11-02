"""P08 daily-only logic regressions: never inherit sample number/slot rules."""
import tempfile
import unittest
from pathlib import Path
from app.daily_slot_schema import validate_daily_slot_plan
from app.daily_slot_memory import DailySlotMemory


class DailySlotSeparationTests(unittest.TestCase):
    def setUp(self):
        self.html_fields = [
            {'item':'196949','format':'3','options':['Initial','Middle','Final'],
             'slots':[{'number':n,'saved':False} for n in range(1,7)]},
            {'item':'196950','format':'4','options':['OK','NG'],
             'slots':[{'number':n,'saved':False} for n in range(1,7)]},
        ]

    def test_different_counts_per_item(self):
        validate_daily_slot_plan(self.html_fields,{
            '196949':{'1':'Initial','2':'Middle','3':'Final'},
            '196950':{'1':'OK'},
        })

    def test_no_autofill_others(self):
        validate_daily_slot_plan(self.html_fields,{'196949':{'1':'Initial'}})

    def test_reject_wrong_choices(self):
        with self.assertRaises(ValueError):
            validate_daily_slot_plan(self.html_fields,{'196950':{'1':'Final'}})

    def test_reject_missing_qac_slot(self):
        with self.assertRaises(ValueError):
            validate_daily_slot_plan(self.html_fields,{'196949':{'7':'Final'}})

    def test_absolute_slot_selection_is_retained(self):
        # Template may select explicit Slot 2; writer must never shift it to another slot.
        validate_daily_slot_plan(self.html_fields,{'196949':{'2':'Middle'}})

    def test_existing_saved_slot_can_skip_to_next(self):
        self.html_fields[0]['slots'][0]['saved']=True
        validate_daily_slot_plan(self.html_fields,{'196949':{'2':'Middle'}})

    def test_no_result_data_saved_to_preset(self):
        with tempfile.TemporaryDirectory() as td:
            memory=DailySlotMemory(Path(td)/'templates.sqlite3')
            doc={'document_name':'TS1-Sub Day Tablet','line':'TS1-Sub','period':'Daily','model':'All'}
            memory.save(doc,{'196949':{'1':'Initial'},'196950':{'1':'OK','2':'NG'},'196951':{'1':'VALUE:0.51'}})
            self.assertEqual(memory.load(doc),{'196949':{'1':'Initial'},'196950':{'1':'OK','2':'NG'},'196951':{'1':'VALUE:0.51'}})
            night={**doc,'document_name':'TS1-Sub Night Tablet'}
            self.assertEqual(memory.load(night),{})
            memory.reset(doc)
            self.assertEqual(memory.load(doc),{})

    def test_legacy_sample_code_does_not_depend_on_daily_register(self):
        import inspect
        import app.sample_register as sample
        source=inspect.getsource(sample)
        self.assertNotIn('from .daily_document_register import',source)


if __name__=='__main__':unittest.main()

import unittest
from app.daily_document_register import numeric_html_constraint

class NativeQacNumericConstraintTests(unittest.TestCase):
    def test_actual_log_1210_step_mismatch(self):
        self.assertEqual(numeric_html_constraint('12.10','1',None,None),'STEP_MISMATCH')
    def test_integer_allowed(self):
        self.assertIsNone(numeric_html_constraint('12','1',None,None))
    def test_explicit_decimal_step(self):
        self.assertIsNone(numeric_html_constraint('12.10','1',None,'0.01'))
    def test_any_step_preserves_decimal(self):
        self.assertIsNone(numeric_html_constraint('12.10','1',None,'any'))
    def test_range_check(self):
        self.assertEqual(numeric_html_constraint('0.55','1',None,'any'),'RANGE_UNDERFLOW')
    def test_unconstrained_decimal_default_step(self):
        self.assertEqual(numeric_html_constraint('0.5530',None,None,None),'STEP_MISMATCH')
    def test_negative_decimal_explicit_step(self):
        self.assertIsNone(numeric_html_constraint('-36.8',None,None,'0.1'))

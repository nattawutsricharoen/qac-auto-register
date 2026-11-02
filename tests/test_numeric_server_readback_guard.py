"""Regression guards for post-Confirm readback; no production QAC calls."""
import inspect
import unittest
from app import daily_document_register as reg


class NumericServerReadbackTests(unittest.TestCase):
    def test_decimal_display_normalization(self):
        self.assertTrue(reg.qac_numeric_values_equal('.51', '0.5100'))
        self.assertFalse(reg.qac_numeric_values_equal('.51', '0.52'))

    def test_fresh_readback_is_read_only_and_identity_verified(self):
        source = inspect.getsource(reg._fresh_qac_numeric_readback)
        self.assertIn('verify_daily_measure_identity', source)
        self.assertIn('_return_to_check_sheet', source)
        self.assertIn('_click_measure_action', source)
        self.assertIn('extract_daily_item_schema', source)
        self.assertNotIn('_click_save(', source)
        self.assertNotIn('acknowledge_visible_modal(', source)

    def test_refresh_is_fallback_only_on_unverified_numeric_result(self):
        source = inspect.getsource(reg._register_ok_on_measure_page)
        self.assertIn("field['format'] != '1' or 'DAILY SAVE UNVERIFIED' not in str(exc)", source)
        self.assertIn('_fresh_qac_numeric_readback(', source)

if __name__ == '__main__':
    unittest.main()

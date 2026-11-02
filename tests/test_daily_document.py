import unittest

from app.daily_document import classify_document_kind


class DailyDocumentClassificationTests(unittest.TestCase):
    def test_document_groups(self):
        cases = {
            "TS2-Sub_SC1_Housing disc-Production Sample Initial-Final": "AUTO_CSV",
            "TS2-Sub_SC1_Stud bolt ST#1 Initial-Final": "AUTO_CSV",
            "TS2-Sub_All Model_Day_Cleaning before break": "MANUAL_OK_NG",
            "TS2-Sub_SC1_Interlock & master check": "MANUAL_OK_NG",
            "TS2-Sub_All Model_Linear gauge present value": "MANUAL_VALUE",
            "TS2-Sub_All Model_Tablet control No1": "MANUAL_VALUE",
        }
        for name, expected in cases.items():
            with self.subTest(name=name):
                self.assertEqual(
                    classify_document_kind({"document_name": name, "period": "Daily"}),
                    expected,
                )


if __name__ == "__main__":
    unittest.main()


def test_gas_filling_initial_final_is_sample_auto_csv():
    from app.daily_document import classify_document_kind
    row = {
        'document_name': 'TS1-Sub_S92_Seal pin & Gas filling ST#1 Initial-Final',
        'period': 'Daily',
    }
    assert classify_document_kind(row) == 'AUTO_CSV'

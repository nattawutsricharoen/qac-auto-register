import tempfile
import unittest
from pathlib import Path

from app.alarm_learning import AlarmLearningStore


class AlarmLearningStoreTests(unittest.TestCase):
    def test_prefers_exact_line_then_falls_back_to_all_pages(self):
        with tempfile.TemporaryDirectory() as directory:
            store = AlarmLearningStore(Path(directory) / "learning.db")
            store.record_success(
                "TS1-Sub", "Servo alarm",
                machine_value="M1", machine_name="Machine 1",
                ng_value="N1", ng_name="NG 1",
                process_value="P1", process_name="Process 1",
            )
            exact = store.best("TS1-Sub", "Servo alarm")
            fallback = store.best("TS2-Sub", "Servo alarm")
            self.assertEqual(exact.machine_value, "M1")
            self.assertEqual(exact.match_scope, "LINE")
            self.assertEqual(fallback.machine_value, "M1")
            self.assertEqual(fallback.match_scope, "ALL_PAGES")


if __name__ == "__main__":
    unittest.main()

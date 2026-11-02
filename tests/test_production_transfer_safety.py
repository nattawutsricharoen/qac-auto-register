import unittest
from app.production_transfer import extract_lot, judges_all_pass, _judge_values_from_rows


class TransferSafety(unittest.TestCase):
    def test_lot_from_actual_line_file_names(self):
        self.assertEqual(extract_lot('20261016-SC22-3CR(Night).xlsx'), '20261016-SC22-3')
        self.assertEqual(extract_lot('20261016-3C14-6CR(Night).xlsx'), '20261016-3C14-6')

    def test_bad_lot_fails_closed(self):
        with self.assertRaises(ValueError):
            extract_lot('wrong_file.xlsx')

    def test_judges_must_all_pass(self):
        self.assertTrue(judges_all_pass(['PASS', 'PASS', 'PASS']))
        for values in ([], ['PASS', 'NG'], ['PASS', ''], ['PASS', '-']):
            self.assertFalse(judges_all_pass(values))

    def test_extract_all_judges_from_row(self):
        rows = [dict(label='Spec', values=['10', '20']), dict(label='Judge', values=['PASS', 'PASS'])]
        self.assertEqual(_judge_values_from_rows(rows), ['PASS', 'PASS'])
        with self.assertRaises(RuntimeError):
            _judge_values_from_rows([dict(label='Judge', values=['PASS', 'NG'])])
        with self.assertRaises(RuntimeError):
            _judge_values_from_rows([dict(label='Spec', values=['20'])])
        with self.assertRaises(RuntimeError):
            _judge_values_from_rows([dict(label='Judge', values=['PASS']), dict(label='Judge', values=['PASS'])])

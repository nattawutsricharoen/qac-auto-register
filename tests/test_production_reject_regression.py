import tempfile
import unittest
from pathlib import Path
from openpyxl import Workbook
from datetime import datetime
from app.production_output import load_production_line_file, is_reject_marker

class RejectByHourTests(unittest.TestCase):
    def test_marker(self):
        self.assertTrue(is_reject_marker('Reject: Bottle damage'))
        self.assertTrue(is_reject_marker('REJECT'))
        self.assertFalse(is_reject_marker('OK'))
        self.assertFalse(is_reject_marker(3.14))
    def test_hourly_gross_reject_net(self):
        with tempfile.TemporaryDirectory() as td:
            fn=Path(td)/'20261016-SC22-3CR(Day).xlsx'
            wb=Workbook();ws=wb.active
            ws.append(['Date/Time','Kanban','Serial(Temporary)','Leak Rate','Remark'])
            ws.append([datetime(2026,10,16,8,5),'S921','SC22001',1.2,None])
            ws.append([datetime(2026,10,16,8,15),'S921','SC22002',1.2,'Reject: Bottle damage'])
            ws.append([datetime(2026,10,16,9,10),'S921','SC22003',1.2,None])
            wb.save(fn)
            data=load_production_line_file(str(fn))
            self.assertEqual(data.counted_total,2)
            self.assertEqual(data.reject_total,1)
            self.assertEqual(sum(h.gross for h in data.hourly),3)
            self.assertEqual(sum(h.qty for h in data.hourly),2)
            h8=next(h for h in data.hourly if h.interval_start=='08:00')
            self.assertEqual((h8.gross,h8.rejected,h8.qty),(2,1,1))
if __name__=='__main__': unittest.main()

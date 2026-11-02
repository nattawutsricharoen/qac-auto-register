import tempfile,unittest
from pathlib import Path
from app.access_csv_editor import read_access_csv,save_access_csv

class AccessCsvEditorTests(unittest.TestCase):
    def test_save_and_read(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'access.csv'
            p.write_text('ip,name,status,tab1_enable,settings_show\n10.0.0.1,pc,active,1,1\n',encoding='utf-8')
            fields,rows=read_access_csv(p)
            rows[0]['tab1_enable']='0'
            save_access_csv(p,fields,rows)
            self.assertEqual(read_access_csv(p)[1][0]['tab1_enable'],'0')
            self.assertFalse(Path(str(p)+'.lock').exists())
    def test_invalid_flags_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'access.csv'
            p.write_text('ip,name,status,tab1_enable\n10.0.0.1,pc,active,1\n')
            fields,rows=read_access_csv(p)
            rows[0]['tab1_enable']='maybe'
            with self.assertRaises(ValueError):save_access_csv(p,fields,rows)
            self.assertIn('active,1',p.read_text())
if __name__=='__main__':unittest.main()

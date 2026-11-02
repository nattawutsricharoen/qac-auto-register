import unittest
from pathlib import Path
from bs4 import BeautifulSoup
from unittest.mock import AsyncMock, patch
from app.daily_slot_schema import refresh_daily_results_by_activation

HTML = Path('/mnt/data/Pasted text(20261021-033632).txt')

class _Locator:
    def __init__(self):
        self.first=self
        self.click=AsyncMock()
        self.wait_for=AsyncMock()
        self.get_attribute=AsyncMock(return_value="0")
class _Page:
    def __init__(self):self.calls=[]
    def locator(self,query):
        self.calls.append(query)
        return _Locator()

class ActiveDOMTests(unittest.IsolatedAsyncioTestCase):
    async def test_activation_before_read_for_each_item(self):
        page=_Page()
        saved={'item':'335009','slots':[{'number':1,'status':'SAVED','value':'INITIAL'}, {'number':2,'status':'SAVED','value':'MIDDLE'}, {'number':3,'status':'SAVED','value':'FINAL'}, {'number':4,'status':'EMPTY'}, {'number':5,'status':'EMPTY'}, {'number':6,'status':'EMPTY'}]}
        with patch('app.daily_slot_schema.extract_daily_item_schema', new=AsyncMock(return_value=saved)), patch('app.daily_slot_schema._wait_qac_complete', new=AsyncMock()):
            result=await refresh_daily_results_by_activation(page,[{'item':'335009','slots':[{}]*6,'label':'IMF','frequency':6}])
        self.assertEqual([s['status'] for s in result[0]['slots']][:3],['SAVED']*3)
        self.assertTrue(any('f1-step' in s for s in page.calls))
    async def test_malformed_result_fails_closed(self):
        with patch('app.daily_slot_schema.extract_daily_item_schema', new=AsyncMock(return_value={'slots':[]})),patch('app.daily_slot_schema._wait_qac_complete',new=AsyncMock()):
            with self.assertRaisesRegex(RuntimeError,'UNREADY'):
                await refresh_daily_results_by_activation(_Page(),[{'item':'335009','slots':[{}]*6}])

class ActualHTMLTests(unittest.TestCase):
    def test_saved_without_id_and_absolute_slots(self):
        soup=BeautifulSoup(HTML.read_text(encoding='utf-8'), 'html.parser')
        field=soup.select_one('.fieldset[data-item="335009"]')
        self.assertIsNotNone(field)
        rows=field.select('tr[data-result-no]')
        self.assertEqual(len(rows),6)
        self.assertEqual([row.get('data-empty') for row in rows], ['false']*3+['true']*3)
        self.assertIsNone(rows[2].get('data-result'))
        self.assertIn('Final',rows[2].get_text(' ',strip=True))
    def test_all_36_items_present(self):
        soup=BeautifulSoup(HTML.read_text(encoding='utf-8'),'html.parser')
        self.assertEqual(len(soup.select('.fieldset[data-item]')),36)

if __name__=='__main__': unittest.main()

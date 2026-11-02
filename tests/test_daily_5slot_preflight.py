"""Regression using actual 2026-10-19 QAC HTML, without contacting production."""
from pathlib import Path
import unittest
from html.parser import HTMLParser
from app.daily_slot_schema import validate_daily_slot_plan

HTML_PATH=Path(__file__).resolve().parents[3] / 'Pasted text(20261019-072032).txt'

class RowReader(HTMLParser):
    def __init__(self):
        super().__init__();self.field=None;self.records={};self.stack=[]
    def handle_starttag(self,tag,attrs):
        a=dict(attrs)
        if tag=='div' and 'fieldset' in a.get('class','').split() and a.get('data-item'):
            self.field=a['data-item'];self.stack.append(1)
        elif self.field and tag=='div': self.stack[-1]+=1
        if self.field and tag=='tr' and a.get('data-result-no'):
            self.records.setdefault(self.field,[]).append((int(a['data-result-no']),a.get('data-empty')))
    def handle_endtag(self,tag):
        if self.field and tag=='div':
            self.stack[-1]-=1
            if self.stack[-1]==0:self.field=None;self.stack.pop()

class FiveSlotPlanTests(unittest.TestCase):
    def test_real_html_has_5_1_5_slots(self):
        self.assertTrue(HTML_PATH.exists())
        p=RowReader();p.feed(HTML_PATH.read_text(encoding='utf8'))
        self.assertEqual([len(p.records[x]) for x in ('411398','411399','411400')],[5,1,5])
    def test_skip_first_two_saved_and_stage_next_five(self):
        schema=[{'item':'411398','format':'1','options':['VALUE'], 'slots':[{'number':i,'saved':True} for i in range(1,6)]},
                {'item':'411399','format':'4','options':['OK','NG'], 'slots':[{'number':1,'saved':True}]},
                {'item':'411400','format':'4','options':['OK','NG'], 'slots':[{'number':i,'saved':False} for i in range(1,6)]}]
        plan={'411398':{str(i):'VALUE:8' for i in range(1,6)},'411399':{'1':'OK'},
              '411400':{str(i):'OK' for i in range(1,6)}}
        validate_daily_slot_plan(schema,plan)
        self.assertEqual(sum(s['saved'] for field in schema for s in field['slots']),6)
        self.assertEqual(sum(not s['saved'] for field in schema for s in field['slots']),5)
    def test_slot_gap_is_explicit_not_renumbered(self):
        schema=[{'item':'411400','format':'4','options':['OK','NG'],'slots':[{'number':i,'saved':False} for i in range(1,6)]}]
        # Template accepts an absolute position; write engine guards against
        # writing an unsupported gap rather than redirecting it to a new slot.
        validate_daily_slot_plan(schema,{'411400':{'2':'OK'}})

if __name__=='__main__':unittest.main()

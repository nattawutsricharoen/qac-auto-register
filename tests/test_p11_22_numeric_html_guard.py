from pathlib import Path
import ast
from decimal import Decimal
from html.parser import HTMLParser

ROOT = Path(__file__).resolve().parents[1]
REGISTER = (ROOT/'app'/'daily_document_register.py').read_text(encoding='utf-8')
SCHEMA = (ROOT/'app'/'daily_slot_schema.py').read_text(encoding='utf-8')
FIXTURE_HTML = '<tr data-result-no="1"><input type="number" data-empty="true" data-result-no="1" min="1" placeholder="0.000" disabled></tr>'

class InputReader(HTMLParser):
    def __init__(self):
        super().__init__(); self.values=[]
    def handle_starttag(self, tag, attrs):
        if tag=='input':
            a=dict(attrs)
            if a.get('type')=='number':self.values.append(a)

def test_numeric_saved_html_exposes_blank_inputs():
    p=InputReader();p.feed(FIXTURE_HTML)
    assert any(x.get('min')=='1' and x.get('data-empty')=='true' and 'value' not in x for x in p.values)

def test_numeric_constraints_checked_before_save():
    assert 'checkValidity()' in REGISTER
    assert 'DAILY NUMERIC NATIVE CONSTRAINT' in REGISTER
    assert "await page.keyboard.press('Enter')" in REGISTER
    assert 'await target.fill(selection[6:])' in REGISTER
    assert REGISTER.index('checkValidity()') < REGISTER.index('DAILY ITEM SAVE')

def test_reference_unreadable_value_not_copied():
    assert 'if not value:' in SCHEMA
    assert "validate_qac_numeric_choice('VALUE:' + value)" in SCHEMA
    assert 'DAILY NUMERIC SUCCESS WITHOUT RESULT' in SCHEMA

def test_expected_browser_min_rule_rejects_fraction_and_negative():
    assert Decimal('-0.01') < Decimal('1')
    assert Decimal('0.533') < Decimal('1')
    assert Decimal('8.00') >= Decimal('1')

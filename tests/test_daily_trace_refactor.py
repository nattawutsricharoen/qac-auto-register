"""Regression evidence from operator's 2026-10-19 QAC manual trace."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
TRACE = Path(__file__).resolve().parent / 'fixtures' / 'qac_saved_five_no_id.json'


def test_trace_contains_saved_rows_without_result_id():
    data = json.loads(TRACE.read_text(encoding='utf-8'))
    assert data['item_id'] == '411400'
    assert data['frequency'] == '5'
    slots = data['slots']
    assert len(slots) == 5
    assert all(s.get('empty_attribute') == 'false' and
               re.search(r'\bOK\b', s.get('row_text', '')) and
               not s.get('result_attributes') for s in slots)



def test_reader_uses_recorded_row_text_not_just_ids():
    s = (ROOT / 'app' / 'daily_slot_schema.py').read_text(encoding='utf-8')
    assert "emptyFlag==='false'" in s
    assert 'displayedValue' in s
    assert "status:saved?'SAVED':unknown?'UNKNOWN':'EMPTY'" in s
    assert "return {number:n, saved:!!saved" in s


def test_save_complete_does_not_bypass_persisted_result_verification():
    s = (ROOT / 'app' / 'qac_measure_actions.py').read_text(encoding='utf-8')
    register = (ROOT / 'app' / 'daily_document_register.py').read_text(encoding='utf-8')
    assert "'complete' in message" in s
    assert 'await _wait_daily_slot_persisted(' in register
    assert 'if result_id:' in register
    assert 'DOM_CONFIRMED' not in register


def test_never_insert_result_or_force_click():
    register = (ROOT / 'app' / 'daily_document_register.py').read_text(encoding='utf-8')
    assert 'btn-insert-result' not in register
    assert 'force=True' not in register

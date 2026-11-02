from pathlib import Path
from html.parser import HTMLParser
from app.daily_document_register import numeric_html_constraint

CODE = (Path(__file__).parents[1] / 'app' / 'daily_document_register.py').read_text(encoding='utf-8')

def test_numeric_order_must_fill_focused_enter_check_then_save():
    fill=CODE.index('await target.fill(selection[6:])')
    blur=CODE.index("await page.keyboard.press('Enter')",fill)
    check=CODE.index("browser_check = await target.evaluate",blur)
    save=CODE.index('DAILY ITEM SAVE',check)
    assert fill < blur < check < save

def test_no_native_constraint_block_prior_qac_save():
    assert 'DAILY NUMERIC PREFLIGHT REJECTED' not in CODE
    assert 'DAILY NUMERIC QAC CONSTRAINT' not in CODE
    assert 'DAILY NUMERIC NATIVE CONSTRAINT' in CODE
    assert 'browser_check[\'badInput\']' in CODE

def test_html_rule_disagreement_is_detected_not_overwritten():
    assert numeric_html_constraint('0.51','1',None,None)=='RANGE_UNDERFLOW'
    assert numeric_html_constraint('3.60','1',None,None)=='STEP_MISMATCH'
    assert 'setAttribute(\'min\'' not in CODE
    assert 'setAttribute(\'step\'' not in CODE

def test_original_html_numeric_controls():
    sample=Path('/mnt/data/Pasted text(20261022-070410).txt')
    if not sample.exists():
        return
    content=sample.read_text(encoding='utf-8')
    assert 'data-item="438202"' in content
    assert 'min="1" placeholder="0.000"' in content
    assert 'btn-save' in content
    assert 'Do you want to save it ?' in content or 'sweetalert2' in content

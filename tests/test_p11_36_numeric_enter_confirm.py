"""Guard Enter-triggered QAC numeric confirmation and prevent double-save."""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / 'app' / 'daily_document_register.py').read_text(encoding='utf-8')


def test_numeric_enter_after_fill_before_inspection():
    start = SOURCE.index('await target.fill(selection[6:])')
    enter = SOURCE.index("await page.keyboard.press('Enter')", start)
    inspect = SOURCE.index('browser_check = await target.evaluate', enter)
    assert start < enter < inspect


def test_enter_confirmation_path_does_not_click_save_again():
    assert 'numeric_enter_confirmed = True' in SOURCE
    assert 'if not numeric_enter_confirmed:' in SOURCE
    assert "await acknowledge_visible_modal(page, progress" in SOURCE


def test_direct_confirmation_restricts_to_expected_save_dialog():
    assert "if 'save' not in label and 'บันทึก' not in label:" in SOURCE
    assert 'DAILY NUMERIC EARLY CONFIRM' in SOURCE
    assert 'DAILY NUMERIC UNEXPECTED CONFIRM' in SOURCE

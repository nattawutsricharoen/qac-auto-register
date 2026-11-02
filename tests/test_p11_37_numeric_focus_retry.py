"""Regression: trusted focused Enter and explicit same-session retry plan."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REGISTER = (ROOT / 'app' / 'daily_document_register.py').read_text(encoding='utf-8')
MAIN = (ROOT / 'main.py').read_text(encoding='utf-8')


def test_numeric_focus_and_keyboard_enter_before_readback():
    start = REGISTER.index('await target.fill(selection[6:])')
    focus = REGISTER.index('await target.focus()', start)
    verify = REGISTER.index('document.activeElement === el', focus)
    enter = REGISTER.index("await page.keyboard.press('Enter')", verify)
    modal = REGISTER.index('modal_after_enter = await inspect_visible_qac_modal(page)', enter)
    check = REGISTER.index('browser_check = await target.evaluate', modal)
    assert start < focus < verify < enter < modal < check
    assert 'await target.blur()' not in REGISTER[start:check]


def test_retry_ui_preserves_confirmed_plan_and_fresh_verify():
    assert 'Retry Incomplete (No Rescan)' in MAIN
    start = MAIN.index('def retry_daily_register_incomplete(self):')
    end = MAIN.index('def pause_daily_register(self):', start)
    retry = MAIN[start:end]
    assert "d.get('_daily_slot_plan')" in retry
    assert 'self._pending_daily_register_payload' in retry
    assert 'self.daily_date.date().toString' in retry
    assert 'self.daily_scan_selected()' not in retry
    assert 'current = await extract_daily_item_schema(page, str(item_id))' in REGISTER
    assert "if slots[n]['saved']" in REGISTER


def test_explicit_new_scan_invalidates_retry_plan():
    start = MAIN.index('def daily_scan_selected(self):')
    end = MAIN.index('def daily_refresh_qac_status(self):', start)
    assert 'self._daily_retry_payload = None' in MAIN[start:end]

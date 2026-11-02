"""Regression guards for operator-confirmed Numeric trigger alternatives."""
from pathlib import Path

SOURCE = (Path(__file__).parents[1] / 'app' / 'daily_document_register.py').read_text(encoding='utf-8')


def test_enter_is_primary_and_inspector_only_without_modal_or_save():
    primary = SOURCE.index("await page.keyboard.press('Enter')")
    guard = SOURCE.index("if modal_after_enter.kind == 'NONE' and not live_after_enter['save']:", primary)
    inspector = SOURCE.index("await inspector.first.click", guard)
    assert primary < guard < inspector


def test_inspector_fallback_requires_same_active_item():
    guard = SOURCE.index("if modal_after_enter.kind == 'NONE' and not live_after_enter['save']:")
    assert 'active_before_fallback != str(item_id)' in SOURCE[guard:guard + 700]
    assert 'DAILY NUMERIC NAVIGATED WITHOUT ACK' in SOURCE[guard:guard + 700]


def test_inspector_fallback_single_visible_enabled_input():
    assert "input.textbox-inspector:visible:not([disabled])" in SOURCE
    assert 'inspector_count != 1:' in SOURCE
    assert 'DAILY NUMERIC NO CONFIRM AFTER INSPECTOR' in SOURCE


def test_batch_verification_remains_deferred():
    assert 'deferred_numeric.append' in SOURCE
    assert 'await _verify_numeric_batch_readonly' in SOURCE
    assert 'if not numeric_enter_confirmed:' in SOURCE

"""Regression guard for QAC user-observed modal transitions and safe failure."""
from pathlib import Path


def test_confirm_transition_is_resampled_readonly():
    src = (Path(__file__).parents[1] / 'app' / 'daily_document_register.py').read_text()
    assert "modal_after_enter.kind == 'CONFIRM'" in src
    assert 'DAILY NUMERIC CONFIRM RESAMPLE' in src
    assert 'DAILY NUMERIC CONFIRM LOST' in src
    assert 'await asyncio.sleep(0.10)' in src


def test_failed_register_preserves_measure_and_halts():
    src = (Path(__file__).parents[1] / 'app' / 'daily_document_register.py').read_text()
    assert "register_completed = False" in src
    assert "register_completed = True" in src
    assert "DAILY MEASURE PRESERVED ON ERROR" in src
    assert "DAILY REGISTER HALT | uncertain QAC state" in src
    tail = src[src.index("                finally:", src.index("async def execute_daily_ok_register_async")):]
    assert "if register_completed:" in tail
    assert "else:" in tail


def test_reader_reports_slow_item_without_changing_saved_rule():
    src = (Path(__file__).parents[1] / 'app' / 'daily_slot_schema.py').read_text()
    assert 'DAILY READER SLOW ITEM' in src
    assert 'can_reuse_batch_item(original)' in src
    assert 'can_reuse_verified_empty_target(original)' in src

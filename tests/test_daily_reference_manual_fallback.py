"""Regression contract: optional reference failures must not block manual selection."""
from pathlib import Path


def test_reference_failure_keeps_manual_plan_accessible():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'daily_slot_schema.py').read_text(encoding='utf-8')
    fallback = source.split('if reference_error:', 1)[-1].split('# Fast path:', 1)[0]
    assert 'DAILY MANUAL PLAN READY' in fallback
    assert 'slot.pop(key, None)' in fallback
    assert 'raise RuntimeError(f\'DAILY REFERENCE STOP' not in fallback


def test_reference_identity_still_required_before_loading_values():
    source = (Path(__file__).resolve().parents[1] / 'app' / 'daily_slot_schema.py').read_text(encoding='utf-8')
    assert 'if identity_verified:' in source
    assert "reference_error = f'Reference identity mismatch" in source
    assert 'await verify_daily_measure_identity(ref_page, reference_document, log)' in source
    assert "slot['previous_value'] = value" in source

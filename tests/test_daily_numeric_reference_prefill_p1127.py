from pathlib import Path
import pytest
from app.daily_numeric_prefill import resolve_numeric_prefill


@pytest.mark.parametrize('reference', ['-0.01', '0.533', '0', '8.00', '-36.8', '0.5530', '5.30'])
def test_missing_preset_preserves_measure_reference(reference):
    assert resolve_numeric_prefill(reference, '') == (reference, False)


def test_explicit_numeric_preset_overrides_reference():
    assert resolve_numeric_prefill('0.51', 'VALUE:0.533') == ('0.533', True)


def test_no_reference_and_no_preset_stays_empty():
    assert resolve_numeric_prefill('', '') == ('', False)


def test_invalid_old_preset_does_not_override_reference():
    assert resolve_numeric_prefill('-0.01', 'invalid') == ('-0.01', False)


def test_ui_calls_resolver_in_template_load():
    main = (Path(__file__).resolve().parents[1] / 'main.py').read_text(encoding='utf-8')
    section = main.split('def load_template():',1)[1].split('def reset_template():',1)[0]
    assert 'resolve_numeric_prefill(prior, value)' in section
    assert "widget.setText(value[6:] if value.startswith('VALUE:') else '')" not in section

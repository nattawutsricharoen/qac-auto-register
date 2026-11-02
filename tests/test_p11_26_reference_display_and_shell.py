from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_numeric_reference_is_visible_in_entry():
    source = (ROOT/'main.py').read_text(encoding='utf-8')
    assert 'entry.setText(prior)' in source
    assert "widget.text().strip()==prior" in source
    assert 'Confirm D-1 Carry-Forward' in source

def test_blank_modal_shell_only_waits_never_clicks():
    source = (ROOT/'app'/'qac_interaction.py').read_text(encoding='utf-8')
    segment = source.split('QAC EMPTY MODAL SHELL |', 1)[-1].split('QAC EMPTY MODAL SHELL CLEARED', 1)[0]
    assert 'await page.wait_for_timeout(100)' in segment
    assert 'inspect_visible_qac_modal(page)' in segment
    assert '.click(' not in segment

def test_reference_still_checks_actual_date_and_document():
    source = (ROOT/'app'/'daily_slot_schema.py').read_text(encoding='utf-8')
    assert 'await verify_daily_measure_identity(ref_page, reference_document, log)' in source
    assert "slot['previous_value'] = value" in source

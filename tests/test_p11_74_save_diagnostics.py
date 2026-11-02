"""P11.74: Text Save DOM diagnostic is durable and excludes input values."""
import json
import inspect
from app import sample_register


def test_text_save_reads_both_classes_in_item_panel():
    src = inspect.getsource(sample_register._sample_save_until_complete)
    assert 'button.btn-save, button.btn-save-text' in src
    assert 'activeItem' in src
    assert 'focusSlot' in src
    assert 'CLICK_ATTEMPT' in src
    assert 'SAMPLE SAVE COMPLETE ACK' in src


def test_diagnostic_persists_jsonl_without_sensitive_values(tmp_path, monkeypatch):
    monkeypatch.setattr(sample_register, 'program_dir', lambda: tmp_path)
    events = []
    sample_register._sample_save_diagnostic('460918', 10, 'NOT_READY',
        {'buttons': [{'cls':'btn-save','ready':False}], 'focusSlot':'10'}, events.append)
    paths = list((tmp_path/'logs').glob('sample_save_dom_*.jsonl'))
    assert len(paths) == 1
    record = json.loads(paths[0].read_text(encoding='utf-8').splitlines()[0])
    assert (record['item'],record['slot'],record['phase']) == ('460918',10,'NOT_READY')
    assert 'value' not in record['dom']
    assert any('SAMPLE SAVE DIAGNOSTIC' in event for event in events)

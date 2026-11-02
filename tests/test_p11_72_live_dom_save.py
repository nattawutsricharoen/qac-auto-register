"""Regression against real QAC DOM capture recorded at item 460918."""
import inspect
import json
from pathlib import Path
from app import sample_register


def test_live_enter_shows_only_btn_save():
    source = Path(__file__).parent / "fixtures" / "qac_save_state_item460918.json"
    data = json.loads(source.read_text())
    assert data["activeItem"] == "460918"
    assert [b["className"] for b in data["buttons"] if b["ready"]] == [
        "btn-process form-control btn-save pull-right"
    ]
    assert any("btn-save-text" in b["className"] and not b["ready"] for b in data["buttons"])

def test_save_reacquires_active_item_and_reports_dom():
    src = inspect.getsource(sample_register._sample_save_until_complete)
    assert "page.evaluate" in src
    assert "activeItem" in src and "panelVisible" in src
    assert "SAMPLE SAVE DOM WAIT" in src
    assert "save_candidates = page.locator" in src
    assert "SAMPLE SAVE COMPLETE ACK" in src

def test_no_synthetic_input_change_blur_after_enter():
    src = inspect.getsource(sample_register._fill_field_at_master_slot)
    assert 'await target.press("Enter")' in src
    assert "await target.dispatch_event(" not in src

from app.register_engine import _parse_qac_time, _qac_save_clock_candidates
from app.qac_interaction import classify_qac_modal_kind


def test_human_clock_keeps_meridiem():
    assert _parse_qac_time("21:59:17") == "9:59 PM"
    assert _parse_qac_time("05:46:41") == "5:46 AM"


def test_qac_save_candidates_include_24h_workaround_for_pm():
    candidates = _qac_save_clock_candidates("21:59:17")
    assert "09:59 PM" in candidates
    assert "21:59 PM" in candidates
    assert "21:59" in candidates


def test_complete_bang_is_success_info_when_ok_exists():
    assert classify_qac_modal_kind(
        "Complete ! บันทึกสำเร็จ OK",
        has_loader=False,
        has_confirm=True,
        has_cancel=False,
    ) == "INFO"

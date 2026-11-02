from pathlib import Path

SOURCE = (Path(__file__).resolve().parents[1] / "app" / "daily_document_register.py").read_text(encoding="utf-8")

def test_batch_verification_does_not_leave_measure():
    body = SOURCE.split("async def _verify_numeric_batch_readonly(", 1)[1].split("\n\nasync def _activate_daily_item(", 1)[0]
    assert "_return_to_check_sheet(" not in body
    assert "_click_measure_action(" not in body
    assert "_activate_daily_item(" in body
    assert "verify_daily_measure_identity(" in body
    assert "same Measure readback state=" in body
    assert "await asyncio.sleep(0.2)" in body

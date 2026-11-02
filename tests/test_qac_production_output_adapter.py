from app.qac_production_output_adapter import (
    is_production_confirmation,
    is_production_success,
)


def test_real_production_success_english_thai():
    assert is_production_success("Complete ! บันทึกสำเร็จ OK")


def test_completed_is_success():
    assert is_production_success("Completed !")


def test_save_question_is_confirmation():
    assert is_production_confirmation("Do you want to save it ? Yes, comfirm ! Cancel")


def test_random_popup_is_not_success_or_confirmation():
    text = "Unknown message"
    assert not is_production_success(text)
    assert not is_production_confirmation(text)

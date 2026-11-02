from app.qac_alarm_adapter import is_alarm_save_confirmation, is_alarm_success


def test_alarm_save_confirmation_real_qac_english():
    assert is_alarm_save_confirmation(
        "Do you want to save it ? Yes, comfirm ! Cancel",
        has_confirm=True,
        has_cancel=True,
    )


def test_alarm_save_confirmation_thai():
    assert is_alarm_save_confirmation(
        "คุณต้องการบันทึกหรือไม่ !",
        has_confirm=True,
        has_cancel=False,
    )


def test_alarm_busy_is_not_confirmation():
    assert not is_alarm_save_confirmation(
        "Saving data, please wait...",
        has_confirm=False,
        has_cancel=False,
    )


def test_alarm_info_without_save_question_is_not_first_confirmation():
    assert not is_alarm_save_confirmation(
        "Completed ! บันทึกสำเร็จ",
        has_confirm=True,
        has_cancel=False,
    )


def test_alarm_complete_bang_is_success():
    assert is_alarm_success("Complete !")


def test_alarm_completed_thai_is_success():
    assert is_alarm_success("Completed ! บันทึกสำเร็จ OK")


def test_alarm_save_confirmation_remains_identifiable_as_transition_state():
    # Real QAC can leave this exact popup visible briefly *after* Yes was clicked.
    # The adapter must wait for state transition rather than double-click or fail immediately.
    assert is_alarm_save_confirmation(
        "Do you want to save it ?",
        has_confirm=True,
        has_cancel=True,
    )

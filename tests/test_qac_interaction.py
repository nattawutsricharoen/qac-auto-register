from app.qac_interaction import classify_qac_modal_kind, decide_native_dialog_action


def test_real_qac_loading_wins_over_stale_ok_button():
    text = "Loading data, please wait . . . กำลังโหลดข้อมูล, กรุณารอสักครู่ . . . OK"
    assert classify_qac_modal_kind(
        text, has_loader=True, has_confirm=False, has_cancel=False
    ) == "BUSY"


def test_real_qac_saving_is_busy():
    text = "Saving data, please wait... กำลังบันทึกข้อมูล, กรุณารอสักครู่..."
    assert classify_qac_modal_kind(
        text, has_loader=True, has_confirm=False, has_cancel=False
    ) == "BUSY"


def test_real_qac_save_confirmation_requires_confirm():
    text = "Do you want to save it ? คุณต้องการบันทึกหรือไม่ !"
    assert classify_qac_modal_kind(
        text, has_loader=False, has_confirm=True, has_cancel=True
    ) == "CONFIRM"


def test_completed_is_information_acknowledgement():
    assert classify_qac_modal_kind(
        "Completed ! บันทึกสำเร็จ",
        has_loader=False, has_confirm=True, has_cancel=False
    ) == "INFO"


def test_error_stops_even_if_ok_exists():
    assert classify_qac_modal_kind(
        "Error ไม่สามารถบันทึกข้อมูล",
        has_loader=False, has_confirm=True, has_cancel=False
    ) == "ERROR"


def test_complete_wins_over_stale_cancel_button():
    assert classify_qac_modal_kind(
        "Complete ! บันทึกสำเร็จ OK",
        has_loader=False, has_confirm=True, has_cancel=True
    ) == "INFO"


def test_native_alert_is_acknowledged():
    assert decide_native_dialog_action("alert", "Saved") == "ACCEPT"


def test_native_known_save_confirm_is_accepted():
    assert decide_native_dialog_action("confirm", "Do you want to save it ?") == "ACCEPT"


def test_native_unknown_confirm_is_fail_safe_dismissed():
    assert decide_native_dialog_action("confirm", "Delete all records?") == "DISMISS"


def test_native_prompt_is_never_auto_filled_or_accepted():
    assert decide_native_dialog_action("prompt", "Enter value") == "DISMISS"


def test_complete_is_info_even_when_legacy_ok_is_outside_popup_subtree():
    assert classify_qac_modal_kind(
        "Complete !",
        has_loader=False, has_confirm=False, has_cancel=False
    ) == "INFO"


def test_numeric_complete_without_button_auto_disappears(monkeypatch):
    import asyncio
    from app import qac_interaction as q

    class Page:
        async def wait_for_timeout(self, ms):
            return None

    states = iter([
        q.QACModalState('INFO', title='Complete !'),
        q.QACModalState('INFO', title='Complete !'),
        q.QACModalState('NONE'),
        q.QACModalState('NONE'),
    ])

    async def inspect(page):
        return next(states, q.QACModalState('NONE'))

    async def no_button(state, page=None):
        return None

    async def no_guard(page, progress=None):
        return None

    monkeypatch.setattr(q, 'inspect_visible_qac_modal', inspect)
    monkeypatch.setattr(q, '_find_affirmative_button', no_button)
    monkeypatch.setattr(q, 'install_native_dialog_guard', no_guard)
    messages = []
    assert asyncio.run(q.acknowledge_visible_modal(Page(), messages.append, wait_ms=100)) == 0
    assert any('QAC COMPLETE AUTO DISMISSED' in msg for msg in messages)


def test_unknown_info_without_button_must_not_auto_accept(monkeypatch):
    import asyncio
    import pytest
    from app import qac_interaction as q

    class Page:
        async def wait_for_timeout(self, ms):
            return None

    async def inspect(page):
        return q.QACModalState('INFO', title='Unexpected info')

    async def no_button(state, page=None):
        return None

    async def no_guard(page, progress=None):
        return None

    monkeypatch.setattr(q, 'inspect_visible_qac_modal', inspect)
    monkeypatch.setattr(q, '_find_affirmative_button', no_button)
    monkeypatch.setattr(q, 'install_native_dialog_guard', no_guard)
    with pytest.raises(RuntimeError, match='ไม่พบปุ่มยืนยัน'):
        asyncio.run(q.acknowledge_visible_modal(Page(), wait_ms=100))

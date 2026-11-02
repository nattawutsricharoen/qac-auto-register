from app.qac_interaction import navigation_modal_policy
from app.qac_session import navigation_was_dispatched


def test_navigation_acknowledges_passive_info_only():
    assert navigation_modal_policy("INFO") == "ACK"
    assert navigation_modal_policy("BUSY") == "WAIT"
    assert navigation_modal_policy("NONE") == "CONTINUE"


def test_navigation_never_guesses_confirmation_or_error():
    for kind in ("CONFIRM", "WARNING", "ERROR", "UNKNOWN"):
        assert navigation_modal_policy(kind) == "STOP"


def test_click_timeout_is_recovered_when_url_already_changed():
    assert navigation_was_dispatched(
        "http://host/", "http://host/app/view/measure.html"
    )


def test_click_timeout_is_recovered_when_new_tab_opened():
    assert navigation_was_dispatched(
        "http://host/", "http://host/", new_page_seen=True
    )


def test_click_timeout_is_not_recovered_on_same_menu_state():
    assert not navigation_was_dispatched(
        "http://host/", "http://host/"
    )

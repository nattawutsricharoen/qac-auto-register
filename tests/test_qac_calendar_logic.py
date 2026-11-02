from datetime import date

from app.qac_html_collector import _parse_monitor_date_text


def test_parse_real_qac_monitor_date():
    assert _parse_monitor_date_text("30 Sep 2026") == date(2026, 9, 30)


def test_parse_monitor_date_with_nbsp_and_spacing():
    assert _parse_monitor_date_text("29\xa0 Sep   2026") == date(2026, 9, 29)


def test_parse_monitor_date_invalid_returns_none():
    assert _parse_monitor_date_text("-") is None

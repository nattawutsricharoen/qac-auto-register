from pathlib import Path


def test_calendar_navigation_waits_for_dom_acknowledgement():
    source = (Path(__file__).parents[1] / 'app' / 'qac_html_collector.py').read_text(encoding='utf-8')
    assert 'async def _wait_visible_monitor_date' in source
    assert 'page.wait_for_function(' in source
    assert 'waited_for_DOM=' in source
    assert 'timeout_ms=5000)' not in source
    assert source.count('timeout_ms=90000)') >= 3
    assert 'DATE MONITOR VERIFIED' in source


def test_calendar_does_not_retry_click_when_ack_missing():
    source = (Path(__file__).parents[1] / 'app' / 'qac_html_collector.py').read_text(encoding='utf-8')
    start = source.index('await visible_day.click(timeout=10000)')
    end = source.index('await _close_calendar_popup', start)
    assert source[start:end].count('visible_day.click(') == 1

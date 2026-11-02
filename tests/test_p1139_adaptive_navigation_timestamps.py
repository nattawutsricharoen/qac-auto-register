from unittest.mock import AsyncMock, MagicMock
import pytest
from app.daily_document_register import decide_daily_navigation, _activate_daily_item

@pytest.mark.parametrize('observed,expected,mode', [
    ('438203','438203','AUTO_NEXT'), ('438202','438203','MANUAL_NEXT'),
    (None,'438203','UNKNOWN'),
])
def test_navigation_decision(observed, expected, mode):
    assert decide_daily_navigation(observed, expected) == mode

@pytest.mark.asyncio
async def test_auto_next_does_not_click_sidebar():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value='438203')
    page.locator.return_value.first.click = AsyncMock()
    field = MagicMock()
    field.wait_for = AsyncMock()
    logs = []
    await _activate_daily_item(page, field, '438203', logs.append)
    page.locator.return_value.first.click.assert_not_awaited()
    assert any('mode=AUTO_NEXT click=0' in x for x in logs)

@pytest.mark.asyncio
async def test_manual_next_clicks_target_once():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value='438202')
    page.locator.return_value.first.click = AsyncMock()
    field = MagicMock()
    field.wait_for = AsyncMock()
    logs = []
    await _activate_daily_item(page, field, '438203', logs.append)
    page.locator.return_value.first.click.assert_awaited_once()
    assert any('mode=MANUAL_NEXT click=1' in x for x in logs)

def test_timestamp_format_in_worker_source():
    from pathlib import Path
    src = (Path(__file__).parents[1] / 'app' / 'worker.py').read_text()
    assert '%Y-%m-%d %H:%M:%S.%f' in src

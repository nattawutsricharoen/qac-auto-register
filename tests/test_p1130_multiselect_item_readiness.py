import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.daily_document_register import _activate_daily_item


@pytest.mark.asyncio
async def test_item_waits_until_action_is_visible():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=None)  # no auto-next in this fixture
    page.locator.return_value.first.click = AsyncMock()
    field = MagicMock()
    field.wait_for = AsyncMock()
    field.evaluate = AsyncMock(side_effect=[
        {'item': '196958', 'visible': True, 'actionCount': 0},
        {'item': '196958', 'visible': True, 'actionCount': 1},
    ])
    logs = []
    await _activate_daily_item(page, field, '196958', logs.append,
                               expected_action='.btn-ok, .btn-ok-pd')
    assert field.evaluate.await_count == 2
    assert logs[-1].endswith('action controls ready')


@pytest.mark.asyncio
async def test_item_rejects_wrong_field_identity():
    page = MagicMock()
    page.evaluate = AsyncMock(return_value=None)  # no auto-next in this fixture
    page.locator.return_value.first.click = AsyncMock()
    field = MagicMock()
    field.wait_for = AsyncMock()
    field.evaluate = AsyncMock(return_value={
        'item': '196957', 'visible': True, 'actionCount': 1,
    })
    with pytest.raises(RuntimeError, match='DAILY ITEM IDENTITY CHANGED'):
        await _activate_daily_item(page, field, '196958', None,
                                   expected_action='.btn-ok, .btn-ok-pd')

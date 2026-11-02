import asyncio
from copy import deepcopy
from unittest.mock import AsyncMock

import pytest
from playwright.async_api import async_playwright

from app.sample_result_snapshot import merge_results
from app.sample_register import _read_sample_snapshot


def field(item='10', kind='7', fmt='1'):
    return {'item': item, 'type': kind, 'input_format': fmt,
            'frequency': 2, 'fieldset_found': True,
            'slots': [{'index': i, 'empty': True, 'disabled': False, 'editable': True}
                      for i in (1, 2)]}


def row(**values):
    return {'task_id': '123', 'item_type': '7', 'result_id': 99,
            'result_no': 1, 'result_text': '00123', **values}


def test_preserves_saved_serial_and_absolute_slot_without_mutating_dom_snapshot():
    original = field()
    result = merge_results(original, [row()], '123')
    assert result['slots'][0]['value'] == '00123'
    assert result['slots'][0]['persisted'] and result['slots'][0]['disabled']
    assert result['slots'][1]['empty']
    assert original['slots'][0]['empty']


@pytest.mark.parametrize('bad', [row(task_id='wrong'), row(result_no=3),
                                row(result_id=0), row(result_text=None)])
def test_ambiguous_server_results_do_not_free_occupied_slots(bad):
    with pytest.raises((ValueError, TypeError)):
        merge_results(field(), [bad], '123')


def test_sample_type_and_zero_numeric_are_not_lost():
    master = merge_results(field(kind='1', fmt='3'),
                           [row(item_type='1', result_okng='2')], '123')
    assert master['slots'][0]['value'] == 'Initial'
    numeric = merge_results(field(kind='2'), [row(item_type='2', result_input=0)], '123')
    assert numeric['slots'][0]['value'] == '0'
    with pytest.raises(ValueError):
        merge_results(field(), [row(), row()], '123')


def test_server_empty_cannot_erase_persisted_dom_result():
    f = field()
    f['slots'][0].update(persisted=True, empty=False)
    with pytest.raises(ValueError):
        merge_results(f, [], '123')


def test_bulk_reader_uses_three_read_requests_at_most_and_never_opens_items(monkeypatch):
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(executable_path='/usr/bin/chromium',
                                               headless=True, args=['--no-sandbox'])
            try:
                page = await browser.new_page()
                active = peak = requests = 0

                async def route(request_route):
                    nonlocal active, peak, requests
                    request = request_route.request
                    if request.method == 'POST':
                        assert request.url.endswith('/controller/measurementController.asmx/getItemContent')
                        payload = request.post_data_json
                        assert payload['task_id'] == '123'
                        active += 1
                        peak = max(peak, active)
                        requests += 1
                        await asyncio.sleep(.03)
                        await request_route.fulfill(json={'d': [row(item_id=payload['item_id'])]})
                        active -= 1
                    else:
                        await request_route.fulfill(content_type='text/html', body='<html><body>Sample</body></html>')

                await page.route('**/*', route)
                await page.goto('http://qac.test/app/view/measure.html')
                await page.evaluate("sessionStorage.setItem('qac-task','123')")
                fallback = AsyncMock(side_effect=AssertionError('must not activate items'))
                monkeypatch.setattr('app.sample_register._read_each_sample_item', fallback)
                fields = [field(str(i)) for i in range(5)]
                result = await _read_sample_snapshot(page, fields, '123', lambda _: None)
                assert len(result) == 5 and all(f['slots'][0]['persisted'] for f in result)
                assert requests == 5 and 1 < peak <= 3
                fallback.assert_not_awaited()
                await page.evaluate("sessionStorage.setItem('qac-task','999')")
                with pytest.raises(Exception, match='TASK CHANGED'):
                    await _read_sample_snapshot(page, fields, '123', lambda _: None)
            finally:
                await browser.close()

    asyncio.run(run())


def test_only_unavailable_item_falls_back_to_live_panel(monkeypatch):
    import app.sample_result_snapshot as bulk
    async def run():
        planned = [field('10'), field('11')]
        monkeypatch.setattr(bulk, 'read_sample_results', AsyncMock(return_value={
            '10': {'rows': [row()]}, '11': {'error': 'HTTP 500'}}))
        fallback = AsyncMock(return_value=[deepcopy(planned[1])])
        monkeypatch.setattr('app.sample_register._read_each_sample_item', fallback)
        result = await _read_sample_snapshot(object(), planned, '123', lambda _: None)
        assert result[0]['slots'][0]['persisted']
        assert len(result) == 2
        assert fallback.await_count == 1
        assert fallback.await_args.args[1] == [planned[1]]
    asyncio.run(run())

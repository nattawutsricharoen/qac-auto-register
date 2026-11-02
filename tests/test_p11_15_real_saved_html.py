"""Regression based on user-provided QAC Measure HTML: hidden item 335009.

Uses the REAL DOM evaluation code, no fake results or live server writes.
"""
import asyncio
from pathlib import Path
from playwright.async_api import async_playwright
from app.daily_slot_schema import extract_daily_slot_schema, extract_daily_item_schema, _read_daily_existing_values

HTML = Path(__file__).resolve().parent / 'fixtures' / 'qac_measure_335009_saved.html'

async def _check():
    assert HTML.exists(), 'QAC snapshot fixture missing'
    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
        try:
            page = await browser.new_page()
            await page.set_content(HTML.read_text(encoding='utf-8'), wait_until='domcontentloaded')
            # Raw captured HTML includes a hidden fieldset for this item.
            item = await extract_daily_item_schema(page, '335009')
            assert item['frequency'] == 6
            assert [s['status'] for s in item['slots']] == ['SAVED']*3 + ['EMPTY']*3, item['slots']
            assert [s['value'] for s in item['slots'][:3]] == ['INITIAL','MIDDLE','FINAL'], item['slots']
            assert item['slots'][2]['result_id'] == '', 'Slot 3 must be recognized even without result ID'
            values = await _read_daily_existing_values(page)
            existing = {(v['item'],v['number']):v for v in values}
            assert [existing[('335009',i)]['value'] for i in (1,2,3)] == ['Initial','Middle','Final']
            # full-document schema requires readiness code that waits for live QAC;
            # bypass only the wait, by testing the exact JS from function via source.
            import inspect, re
            src=inspect.getsource(extract_daily_slot_schema)
            js=re.search(r'page\.evaluate\("""(.*?)"""\)', src, re.S).group(1)
            schema=await page.evaluate(js)
            assert len(schema)==36, len(schema)
            target=next(x for x in schema if x['item']=='335009')
            assert [s['status'] for s in target['slots']] == ['SAVED']*3 + ['EMPTY']*3
            # Selected 1-3 must skip all, never roll over to 4-6.
            from app.daily_slot_schema import validate_daily_slot_plan
            validate_daily_slot_plan(schema, {'335009':{'1':'Initial','2':'Middle','3':'Final'}})
            assert sum(s['saved'] for s in target['slots'])==3
        finally:
            await browser.close()

def test_real_qac_hidden_item_has_three_existing_and_three_empty_slots():
    asyncio.run(_check())

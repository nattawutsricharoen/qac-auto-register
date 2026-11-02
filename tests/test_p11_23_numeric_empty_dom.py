import asyncio
from playwright.async_api import async_playwright
from app.daily_slot_schema import extract_daily_item_schema

HTML = '''<div class="f1-step" data-item="438202" data-input="1" data-success="0"><div class="f1-step-p">Pressure</div></div>
<div class="fieldset" data-item="438202" data-input-format="1"><table><tr data-result-no="1" data-empty="true"><td><input type="number" data-result-no="1" data-empty="true" min="1" placeholder="0.000"></td></tr></table></div>
<div class="f1-step" data-item="438203" data-input="1" data-success="1"><div class="f1-step-p">Saved</div></div>
<div class="fieldset" data-item="438203" data-input-format="1"><table><tr data-result-no="1" data-empty="true"><td><input type="number" data-result-no="1" data-empty="true"></td></tr></table></div>
<div class="f1-step" data-item="335009" data-input="3" data-success="1"><div class="f1-step-p">Multi slot</div></div>
<div class="fieldset" data-item="335009" data-input-format="3"><table><tr data-result-no="1" data-empty="false"><td>Initial</td></tr><tr data-result-no="2" data-empty="true"><td>No Result</td></tr></table></div>'''

def test_numeric_empty_and_saved_without_value_and_categorical_slots():
    async def run():
        async with async_playwright() as pw:
            browser=await pw.chromium.launch(headless=True, executable_path='/usr/bin/chromium', args=['--no-sandbox'])
            try:
                page=await browser.new_page()
                await page.set_content(HTML)
                empty=await extract_daily_item_schema(page,'438202')
                uncertain=await extract_daily_item_schema(page,'438203')
                mix=await extract_daily_item_schema(page,'335009')
                assert empty['slots'][0]['status']=='EMPTY'
                assert uncertain['slots'][0]['status']=='UNKNOWN'
                assert [s['status'] for s in mix['slots']]==['SAVED','EMPTY']
            finally:
                await browser.close()
    asyncio.run(run())

"""Offline browser regression for QAC Text Enter/focusout button replacement.

The captured Sample input_enter handler hides footer buttons on both Enter
and focusout, then fades Save back in. These fixtures model that event order;
they do not contact QAC or claim to reproduce its server implementation.
"""
import asyncio
from unittest.mock import AsyncMock, patch

import pytest
from playwright.async_api import async_playwright

from app import sample_register as sample
from app.qac_interaction import QACModalState


@pytest.mark.parametrize("item", ["461999", "462000"])
@pytest.mark.parametrize("last_slot", [False, True])
def test_text_save_commits_once_and_waits_for_complete(item, last_slot):
    async def run():
        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                executable_path="/usr/bin/chromium", headless=True,
                args=["--no-sandbox"],
            )
            try:
                page = await browser.new_page()
                await page.set_content(f'''
                <div class="f1-step active" data-item="{item}"></div>
                <div class="fieldsets"><div class="fieldset" data-item="{item}">
                  <input type="text" data-empty="true" data-result-no="1">
                  <button class="btn-save" style="display:none">Save</button>
                  <button class="btn-save-text" style="display:none">Hidden Save</button>
                </div></div>
                <button id="confirm" style="display:none">Confirm</button>
                <button id="ack" style="display:none">OK</button>
                <script>
                window.phase='NONE'; window.events=[];
                const input=document.querySelector('input');
                const save=document.querySelector('.btn-save');
                const confirm=document.querySelector('#confirm');
                const ack=document.querySelector('#ack');
                function openConfirm() {{
                    events.push('SAVE');phase='CONFIRM';confirm.style.display='block';
                }}
                function commit(e) {{
                    if(e.keyCode!==13 && e.type!=='focusout') return;
                    events.push('COMMIT');input.dataset.empty='false';
                    save.style.display='none';
                    if ({str(last_slot).lower()}) openConfirm();
                    else setTimeout(()=>save.style.display='block',180);
                }}
                input.addEventListener('keypress',commit);
                input.addEventListener('focusout',commit);
                save.addEventListener('click',openConfirm);
                confirm.onclick=()=>{{
                    events.push('CONFIRM');phase='BUSY';confirm.style.display='none';
                    setTimeout(()=>{{events.push('COMPLETE');phase='INFO';ack.style.display='block';}},400);
                }};
                ack.onclick=()=>{{events.push('DISMISS');phase='NONE';ack.style.display='none';}};
                </script>''')

                async def inspect(_page):
                    kind = await page.evaluate('phase')
                    return QACModalState(kind=kind, title='Complete !' if kind == 'INFO' else '')

                async def affirmative(state, _page):
                    return page.locator('#confirm' if state.kind == 'CONFIRM' else '#ack')

                logs = []
                with patch.object(sample, 'assert_sample_item_context', new=AsyncMock()), \
                     patch.object(sample, 'install_native_dialog_guard', new=AsyncMock()), \
                     patch.object(sample, 'inspect_visible_qac_modal', new=inspect), \
                     patch.object(sample, '_find_affirmative_button', new=affirmative), \
                     patch.object(sample, '_sample_save_diagnostic'):
                    await sample._fill_field_at_master_slot(
                        page, page.locator('.fieldset'),
                        {'item': item, 'input_format': '1', 'value': '09:07',
                         'section': '1', 'label': 'Text'}, 1, logs.append,
                    )
                assert await page.evaluate('events') == [
                    'COMMIT', 'SAVE', 'CONFIRM', 'COMPLETE', 'DISMISS',
                ]
                assert any('SAMPLE SAVE COMPLETE ACK' in line for line in logs)
            finally:
                await browser.close()

    asyncio.run(run())

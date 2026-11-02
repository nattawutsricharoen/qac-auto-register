"""Sample-only navigation and stable QAC item context verification.

Sample Measure can return to Task Information on Save, and may asynchronously
switch the active panel while a field is being read. Never infer the selected
item from a successful click or focus() alone.
"""
from __future__ import annotations


async def sample_item_context(page, item: str) -> dict:
    """Inspect selected item and visible panel in one synchronous DOM snapshot."""
    item = str(item)
    return await page.evaluate("""item => {
        const step = document.querySelector('.f1-step[data-item="' + item + '"]');
        const panel = document.querySelector('.fieldset[data-item="' + item + '"]');
        const visible = el => !!el && !!(el.getClientRects().length) &&
            getComputedStyle(el).visibility !== 'hidden' &&
            getComputedStyle(el).display !== 'none';
        const selected = [...document.querySelectorAll('.f1-step[data-item].active')]
            .filter(visible).map(el => el.getAttribute('data-item'));
        const displayed = [...document.querySelectorAll('.fieldset[data-item]')]
            .filter(visible).map(el => el.getAttribute('data-item'));
        return {step: visible(step), panel: visible(panel), selected, displayed,
            taskInfo: visible(document.querySelector('.task-infomation.fieldset')),
            focusItem: document.activeElement?.closest?.('.fieldset[data-item]')?.getAttribute('data-item') || ''};
    }""", item)


def _stable_item(state: dict, item: str) -> bool:
    # QAC sometimes retains 'activated' on previously visited navigation
    # entries; only 'active' is the current selection.
    return (bool(state.get('panel')) and state.get('displayed') == [item]
            and state.get('selected') == [item] and not state.get('taskInfo'))


async def select_sample_item(page, item: str, log, *, force: bool = False):
    item = str(item or '').strip()
    if not item.isdigit():
        raise RuntimeError(f'SAMPLE ITEM ID invalid: {item!r}')
    panel = page.locator(f'.fieldset[data-item="{item}"]').first
    step = page.locator(f'.f1-step[data-item="{item}"]').first
    if await panel.count() != 1 or await step.count() != 1:
        raise RuntimeError(f'SAMPLE ITEM missing unique panel/navigation: {item}')
    # Older offline fakes do not implement evaluate; real QAC always does.
    dom_supported = hasattr(page, 'evaluate')
    for attempt in range(1, 4):
        state = await sample_item_context(page, item) if dom_supported else None
        if state is not None and _stable_item(state, item) and not force:
            log(f'SAMPLE ITEM CONTEXT VERIFIED | item={item} | attempt={attempt}')
            return panel
        if state is None and await panel.is_visible() and not force:
            return panel
        log(f'SAMPLE ITEM ACTIVATE | item={item} | attempt={attempt} | force={int(force)}')
        await step.click()
        await panel.wait_for(state='visible', timeout=5000)
        if dom_supported:
            # Verify transition finished, rather than assuming click gave focus.
            for _ in range(12):
                state = await sample_item_context(page, item)
                if _stable_item(state, item):
                    log(f'SAMPLE ITEM CONTEXT VERIFIED | item={item} | attempt={attempt}')
                    return panel
                await page.wait_for_timeout(100)
            log(f'SAMPLE ITEM FOCUS DRIFT | item={item} | state={state}')
        elif await panel.is_visible():
            return panel
        force = False
    raise RuntimeError(f'SAMPLE ITEM CONTEXT LOST | item={item}; QAC focus/navigation changed, no write performed')


async def assert_sample_item_context(page, item: str, log):
    """Fail closed before writing if QAC changed the selected panel."""
    if not hasattr(page, 'evaluate'):
        return
    state = await sample_item_context(page, item)
    if not _stable_item(state, str(item)):
        log(f'SAMPLE ITEM FOCUS DRIFT | item={item} | state={state}')
        await select_sample_item(page, item, log, force=True)
        state = await sample_item_context(page, item)
    if not _stable_item(state, str(item)):
        raise RuntimeError(f'SAMPLE ITEM CONTEXT LOST | item={item}; refusing to write')


async def reselect_after_sample_save(page, item: str, log):
    """Re-open the intended item after Save; no duplicate Save on uncertainty."""
    info = page.locator('.task-infomation.fieldset').first
    for _ in range(12):
        if await info.count() and await info.is_visible():
            log(f'SAMPLE SAVE RETURNED TASK INFO | item={item}')
            break
        await page.wait_for_timeout(100)
    return await select_sample_item(page, item, log, force=True)

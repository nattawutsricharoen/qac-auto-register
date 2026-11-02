"""Shared low-level QAC Measure actions. No Daily/Sample business rules."""
from __future__ import annotations
import asyncio
from typing import Callable
from .qac_interaction import interaction_checkpoint, acknowledge_visible_modal, install_native_dialog_guard
from .register_engine import _is_navigation_context_error

async def _click_if_visible(locator, timeout_ms: int = 5000) -> bool:
    try:
        await locator.wait_for(state="visible", timeout=timeout_ms)
        await locator.scroll_into_view_if_needed()
        await locator.click(timeout=timeout_ms)
        return True
    except Exception as exc:
        if _is_navigation_context_error(exc):
            return True
        return False


async def _click_save(page, fieldset, progress: Callable[[str], None] | None = None) -> bool:
    """Save one QAC field exactly as an operator would: visible Save -> visible modal confirm."""
    await install_native_dialog_guard(page, progress)
    await interaction_checkpoint(page, progress, name="before Save", wait_ms=200)
    save = fieldset.locator(
        ".btn-save:visible:not([disabled]), "
        ".btn-save-text:visible:not([disabled])"
    ).first
    if not await _click_if_visible(save, timeout_ms=7000):
        return False

    if progress:
        progress("QAC SAVE CLICK")
    # QAC normally opens a confirmation modal.  Detect and acknowledge it if it
    # appears; if this field saves without a modal, continue to state verification.
    try:
        count = await acknowledge_visible_modal(page, progress, wait_ms=350, max_rounds=4)
        if progress and count:
            progress(f"QAC SAVE CONFIRMED | modal_count={count}")
    except RuntimeError as exc:
        # QAC can display Complete! while replacing the OK button in its DOM.
        # Do not mistake the acknowledgement failure for a server-side Save
        # failure; the caller MUST still verify that a result was persisted.
        message=str(exc).casefold()
        if ('complete' in message or 'บันทึกสำเร็จ' in message) and ('ไม่พบปุ่มยืนยัน' in message or 'not visible' in message):
            if progress:
                progress('QAC COMPLETE ACK UNCERTAIN | verify persisted result, do not repeat Save')
        else:
            raise

    try:
        await page.wait_for_timeout(700)
    except Exception:
        pass
    return True


async def _empty_row_count(fieldset) -> int:
    try:
        return int(await fieldset.evaluate("""root => {
            const rows = Array.from(root.querySelectorAll('tbody tr'));
            return rows.filter(row => {
                if (row.getAttribute('data-empty') === 'true') return true;
                return Boolean(row.querySelector('[data-empty="true"]'));
            }).length;
        }"""))
    except Exception:
        return 0


async def _result_state(fieldset) -> dict:
    try:
        return await fieldset.evaluate("""root => ({
            result: String(root.getAttribute('data-result') || ''),
            empty: Array.from(root.querySelectorAll('[data-empty="true"]')).length,
            nonEmpty: Array.from(root.querySelectorAll('[data-empty="false"]')).length,
            values: Array.from(root.querySelectorAll('input[data-result-no], textarea[data-result-no]'))
                .map(el => String(el.value || '').trim()).filter(Boolean)
        })""")
    except Exception:
        return {"result": "", "empty": 0, "nonEmpty": 0, "values": []}


async def _wait_saved_state(page, fieldset, before: dict, timeout_ms: int = 9000) -> bool:
    """Verify that Save changed QAC state instead of trusting click success alone."""
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0
    before_result = str(before.get("result") or "")
    while asyncio.get_running_loop().time() < deadline:
        try:
            state = await _result_state(fieldset)
            result_id = str(state.get("result") or "")
            if result_id and result_id != "0" and result_id != before_result:
                return True
            if int(state.get("empty") or 0) == 0 and int(state.get("nonEmpty") or 0) > 0:
                return True
        except Exception as exc:
            if _is_navigation_context_error(exc):
                return True
        await page.wait_for_timeout(250)
    # Some QAC builds redraw the entire form without preserving the original locator.
    # A visible success step is an acceptable post-save state.
    try:
        item = await fieldset.get_attribute("data-item")
        step = page.locator(f'.f1-step[data-item="{item}"]')
        classes = str(await step.first.get_attribute("class") or "")
        return "success" in classes.split()
    except Exception:
        return False



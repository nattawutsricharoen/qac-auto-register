from __future__ import annotations

import asyncio
from typing import Callable

from .qac_interaction import inspect_visible_qac_modal, install_native_dialog_guard

PRODUCTION_POPUP_WAIT_MS = 15000
PRODUCTION_STATE_TIMEOUT_MS = 90000


def _compact(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _low(value: str) -> str:
    return _compact(value).casefold()


def is_production_success(text: str) -> bool:
    low = _low(text)
    return any(
        token in low
        for token in (
            "complete !",
            "complete!",
            "completed",
            "success",
            "บันทึกสำเร็จ",
            "สำเร็จ",
        )
    )


def is_production_confirmation(text: str) -> bool:
    low = _low(text)
    return any(
        token in low
        for token in (
            "do you want to save",
            "ต้องการบันทึก",
            "yes, comfirm",
            "yes, confirm",
        )
    )


async def _visible_action_button(page):
    """Return a visible SweetAlert affirmative button across old/new QAC DOMs.

    Production Output sometimes renders the button outside the popup node that
    supplies the readable text, so this deliberately searches the page rather
    than only descendants of .swal2-popup/.swal2-modal.
    """
    selectors = (
        "button.swal2-confirm:visible:not([disabled])",
        ".swal2-confirm:visible:not([disabled])",
        "button.confirm:visible:not([disabled])",
    )
    for selector in selectors:
        try:
            loc = page.locator(selector)
            for idx in range(min(await loc.count(), 8)):
                item = loc.nth(idx)
                if await item.is_visible() and await item.is_enabled():
                    return item
        except Exception:
            continue

    # Last safe fallback: only literal positive labels used by QAC.
    for label in ("OK", "Yes, comfirm !", "Yes, confirm !"):
        try:
            loc = page.get_by_role("button", name=label, exact=True)
            for idx in range(min(await loc.count(), 4)):
                item = loc.nth(idx)
                if await item.is_visible() and await item.is_enabled():
                    return item
        except Exception:
            continue
    return None


async def _visible_popup_text(page) -> str:
    selectors = (
        ".swal2-container:visible .swal2-modal:visible",
        ".swal2-modal:visible",
        ".swal2-container:visible .swal2-popup:visible",
        ".swal2-popup:visible",
    )
    for selector in selectors:
        try:
            loc = page.locator(selector).first
            if await loc.count() and await loc.is_visible():
                text = _compact(await loc.inner_text(timeout=800))
                if text:
                    return text
        except Exception:
            continue
    return ""


async def handle_production_output_commit(
    page,
    progress: Callable[[str], None] | None = None,
    *,
    step_timeout_ms: int = 10000,
    initial_wait_ms: int = PRODUCTION_POPUP_WAIT_MS,
) -> None:
    """Handle Production Output Save/Update transient QAC states.

    The Time & Event page differs from Production Check Sheet. It may show a
    save confirmation, a busy state, then a legacy SweetAlert2 success popup
    such as "Complete ! / บันทึกสำเร็จ / OK". The success button can be
    visible globally even when the popup-local selector cannot see it.
    """
    await install_native_dialog_guard(page, progress)

    start = asyncio.get_running_loop().time()
    first_deadline = start + initial_wait_ms / 1000.0
    hard_deadline = start + PRODUCTION_STATE_TIMEOUT_MS / 1000.0
    saw_state = False
    last_text = ""

    while asyncio.get_running_loop().time() < hard_deadline:
        state = await inspect_visible_qac_modal(page)
        popup_text = await _visible_popup_text(page)
        label = _compact(
            state.title or state.content or state.text or popup_text or last_text
        )
        if label:
            last_text = label

        button = await _visible_action_button(page)

        # No popup/state. For Production Output this is acceptable after an
        # acknowledgement because the caller verifies the saved result/qty.
        if state.kind == "NONE" and not popup_text:
            if saw_state:
                if progress:
                    progress("PRODUCTION QAC POPUP COMPLETE")
                return
            if asyncio.get_running_loop().time() >= first_deadline:
                if progress:
                    progress("PRODUCTION QAC POPUP | none; continue to result verification")
                return
            await page.wait_for_timeout(100)
            continue

        saw_state = True
        low = _low(label or popup_text)

        if state.kind in ("ERROR", "WARNING"):
            raise RuntimeError(f"QAC {state.kind}: {(label or popup_text)[:500]}")

        # Loading/Saving: never click.
        if state.kind == "BUSY" or any(
            token in low
            for token in (
                "loading data",
                "saving data",
                "please wait",
                "กำลังโหลดข้อมูล",
                "กำลังบันทึกข้อมูล",
                "กรุณารอสักครู่",
            )
        ):
            if progress:
                progress(f"PRODUCTION QAC BUSY | {(label or popup_text)[:220]}")
            await page.wait_for_timeout(160)
            continue

        # Save confirmation, if this action uses one.
        if state.kind == "CONFIRM" or is_production_confirmation(label or popup_text):
            if button is None:
                await page.wait_for_timeout(100)
                continue
            try:
                button_label = _compact(await button.inner_text(timeout=800))
            except Exception:
                button_label = ""
            if progress:
                progress(f"PRODUCTION QAC CONFIRM | click={button_label or 'confirm'}")
            await button.click(timeout=step_timeout_ms)
            await page.wait_for_timeout(120)
            continue

        # Legacy QAC success may be classified UNKNOWN because popup-local
        # has_confirm is false even though a global visible OK exists.
        if state.kind == "INFO" or is_production_success(label or popup_text):
            if button is None:
                # Allow a short render delay for the visible OK button.
                await page.wait_for_timeout(100)
                continue
            try:
                button_label = _compact(await button.inner_text(timeout=800))
            except Exception:
                button_label = ""
            # Never click Cancel by accident.
            if _low(button_label) in ("cancel", "ยกเลิก"):
                raise RuntimeError(
                    f"QAC success popup พบเฉพาะปุ่ม Cancel: {(label or popup_text)[:350]}"
                )
            if progress:
                progress(f"PRODUCTION QAC ACK | click={button_label or 'OK'}")
            await button.click(timeout=step_timeout_ms)
            await page.wait_for_timeout(120)
            continue

        raise RuntimeError(
            "พบ QAC Production Output popup ที่ยังไม่รู้จัก จึงไม่คลิกแทนผู้ใช้: "
            + (label or popup_text)[:400]
        )

    raise RuntimeError(
        "QAC Production Output popup ยังไม่จบภายใน 90 วินาที"
        + (f" | last={last_text[:260]}" if last_text else "")
    )

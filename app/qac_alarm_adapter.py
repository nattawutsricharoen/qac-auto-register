from __future__ import annotations

import asyncio
from typing import Callable

from .qac_interaction import inspect_visible_qac_modal, install_native_dialog_guard

ALARM_SAVE_CONFIRM_TIMEOUT_MS = 12000
ALARM_SAVE_STATE_TIMEOUT_MS = 90000


def _compact(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _low(value: str) -> str:
    return _compact(value).casefold()




def is_alarm_success(text: str) -> bool:
    low = _low(text)
    return any(token in low for token in (
        "complete !",
        "complete!",
        "completed",
        "บันทึกสำเร็จ",
        "success",
        "สำเร็จ",
    ))

def is_alarm_save_confirmation(text: str, *, has_confirm: bool, has_cancel: bool) -> bool:
    """Alarm/Production Output page save-confirm policy.

    This deliberately follows the real operator flow on the Time & Event page,
    not the Production Check Sheet policy. A save confirmation must expose a
    visible affirmative control and either a Cancel control or the actual save
    question text used by QAC.
    """
    if not has_confirm:
        return False
    low = _low(text)
    return bool(
        has_cancel
        or "do you want to save" in low
        or "ต้องการบันทึก" in low
        or "yes, comfirm" in low
        or "yes, confirm" in low
    )


async def _visible_confirm_button(page):
    selectors = (
        "button.swal2-confirm:visible:not([disabled])",
        ".swal2-confirm:visible:not([disabled])",
    )
    for selector in selectors:
        try:
            loc = page.locator(selector)
            count = await loc.count()
        except Exception:
            # QAC may redraw/navigate between selector creation and count().
            # Treat that as a transient no-button state and let the state loop
            # re-inspect the new DOM instead of failing the whole register.
            continue
        for idx in range(min(count, 8)):
            item = loc.nth(idx)
            try:
                if await item.is_visible() and await item.is_enabled():
                    return item
            except Exception:
                continue
    return None


async def _click_alarm_control(page, button, *, timeout_ms: int, progress=None, label: str = "") -> bool:
    """Click an Alarm-page SweetAlert control without treating navigation as failure.

    Some QAC Alarm deployments navigate back to measure.html immediately after
    acknowledging the success popup. Playwright can keep locator.click() open
    while that navigation settles and eventually raise TimeoutError even though
    the click was accepted and QAC already navigated. For Alarm we therefore
    suppress navigation waiting and verify the post-click state ourselves.
    Returns True when a navigation was observed.
    """
    before_url = str(getattr(page, "url", "") or "")
    try:
        # Human-like DOM click, but do not make the click itself own the page
        # navigation lifecycle. The adapter verifies the resulting state below.
        await button.click(timeout=timeout_ms, no_wait_after=True)
    except Exception as exc:
        # A QAC navigation can invalidate/detach the SweetAlert during click.
        # Treat it as success only when there is objective evidence that the
        # page actually navigated or the popup disappeared. Never swallow an
        # arbitrary click failure.
        after_url = str(getattr(page, "url", "") or "")
        try:
            current = await inspect_visible_qac_modal(page)
        except Exception:
            current = None
        navigated = bool(after_url and before_url and after_url != before_url)
        closed = current is not None and current.kind == "NONE"
        if not (navigated or closed):
            raise
        if progress:
            progress(
                f"ALARM SAVE CLICK ACCEPTED | {label or 'control'} | "
                f"navigation={int(navigated)} | popup_closed={int(closed)}"
            )
        return navigated

    await page.wait_for_timeout(100)
    after_url = str(getattr(page, "url", "") or "")
    navigated = bool(after_url and before_url and after_url != before_url)
    if navigated and progress:
        progress(f"ALARM SAVE NAVIGATED | {before_url} -> {after_url}")
    return navigated


async def save_alarm_event(
    page,
    form,
    progress: Callable[[str], None] | None = None,
    *,
    step_timeout_ms: int = 10000,
) -> None:
    """Save one Alarm Import event using the real Alarm-page operator flow.

    Alarm/Production Output uses a SweetAlert save confirmation whose behavior
    is different from Production Check Sheet Measure. Keep this page-specific
    adapter so future QAC changes do not affect Daily/Sample Register.
    """
    await install_native_dialog_guard(page, progress)

    save = form.locator("button.btn-save:visible:not([disabled])").first
    if await save.count() < 1:
        raise RuntimeError("ไม่พบปุ่ม Save / บันทึก ที่พร้อมใช้งานในหน้า Alarm")

    await save.scroll_into_view_if_needed()
    await save.click(timeout=step_timeout_ms)
    if progress:
        progress("ALARM SAVE | clicked visible Save")

    # Production-proven Alarm flow from v1.7.36: the Alarm page uses an older
    # SweetAlert2 variant on some deployments. Its visible confirm button is
    # reliable even when the popup wrapper is .swal2-modal rather than
    # .swal2-popup. Therefore detect the visible confirm button directly first,
    # then use semantic modal inspection as a safety check/fallback.
    deadline = asyncio.get_running_loop().time() + ALARM_SAVE_CONFIRM_TIMEOUT_MS / 1000.0
    confirmed = False
    last_text = ""
    while asyncio.get_running_loop().time() < deadline:
        button = await _visible_confirm_button(page)
        if button is not None:
            try:
                label = _compact(await button.inner_text(timeout=800))
            except Exception:
                label = ""

            # Read the actual visible SweetAlert text when possible. Both old
            # (.swal2-modal) and new (.swal2-popup) wrappers are supported.
            popup_text = ""
            for selector in (
                ".swal2-container:visible .swal2-modal:visible",
                ".swal2-modal:visible",
                ".swal2-container:visible .swal2-popup:visible",
                ".swal2-popup:visible",
            ):
                try:
                    loc = page.locator(selector).first
                    if await loc.count() and await loc.is_visible():
                        popup_text = _compact(await loc.inner_text(timeout=800))
                        if popup_text:
                            break
                except Exception:
                    pass

            last_text = popup_text or label
            low = _low(last_text)
            # Do not click a visible button belonging to an unrelated/result
            # popup. Accept only the real Alarm save question/Yes label.
            if (
                "do you want to save" in low
                or "ต้องการบันทึก" in low
                or "yes, comfirm" in _low(label)
                or "yes, confirm" in _low(label)
            ):
                if progress:
                    progress(f"ALARM SAVE CONFIRM | click={label or 'confirm'}")
                await _click_alarm_control(
                    page,
                    button,
                    timeout_ms=step_timeout_ms,
                    progress=progress,
                    label=label or "Yes/Confirm",
                )
                confirmed = True
                break

        state = await inspect_visible_qac_modal(page)
        if state.kind != "NONE":
            last_text = state.title or state.content or state.text or last_text
            if state.kind in ("ERROR", "WARNING"):
                raise RuntimeError(f"QAC {state.kind}: {last_text[:500]}")
        await page.wait_for_timeout(100)

    if not confirmed:
        raise RuntimeError(
            "ไม่พบ QAC Save confirmation ของหน้า Alarm ภายใน "
            f"{int(ALARM_SAVE_CONFIRM_TIMEOUT_MS/1000)} วินาที"
            + (f" | last={last_text[:240]}" if last_text else "")
        )

    # After Yes/Confirm, follow the Alarm page's Saving -> Completed states.
    # Never click a loader. If Completed/Success appears, acknowledge it.
    deadline = asyncio.get_running_loop().time() + ALARM_SAVE_STATE_TIMEOUT_MS / 1000.0
    # Some old SweetAlert2 builds leave the original save-confirm popup visible
    # for a short moment after the Yes button is accepted.  That is a transition
    # state, not a second operator confirmation.  Never double-click it; wait for
    # Saving/Complete/popup-close to appear.
    confirm_transition_deadline = asyncio.get_running_loop().time() + 6.0
    transition_logged = False
    while asyncio.get_running_loop().time() < deadline:
        state = await inspect_visible_qac_modal(page)
        if state.kind == "NONE":
            if progress:
                progress("ALARM SAVE | popup closed; wait for QAC result")
            return

        label = state.title or state.content or state.text or ""
        if state.kind == "BUSY":
            # Old SweetAlert2 can keep the previous save-question text while
            # showLoading() is already active. Report the semantic state, not
            # the stale question text.
            busy_label = label
            if "do you want to save" in _low(label) or "ต้องการบันทึก" in _low(label):
                busy_label = "Saving data, please wait..."
            if progress:
                progress(f"ALARM SAVE BUSY | {busy_label[:220]}")
            await page.wait_for_timeout(180)
            continue

        if state.kind in ("ERROR", "WARNING"):
            raise RuntimeError(f"QAC {state.kind}: {label[:500]}")

        # After the first confirmed click, an old QAC SweetAlert can keep the
        # exact save question visible while its preConfirm/AJAX handler is still
        # starting.  Treat this as a transient state and DO NOT click Yes again.
        if state.kind == "CONFIRM" and is_alarm_save_confirmation(
            label, has_confirm=state.has_confirm, has_cancel=state.has_cancel
        ):
            if asyncio.get_running_loop().time() <= confirm_transition_deadline:
                if progress and not transition_logged:
                    progress("ALARM SAVE TRANSITION | save question still visible after confirm; waiting QAC state change")
                    transition_logged = True
                await page.wait_for_timeout(150)
                continue
            raise RuntimeError(
                "QAC Save confirmation ไม่เปลี่ยนสถานะหลังยืนยันภายใน 6 วินาที; "
                "หยุดเพื่อป้องกันการกดซ้ำ/สร้างข้อมูลซ้ำ"
            )

        # Alarm deployments are inconsistent after Save: some old SweetAlert2
        # builds keep a hidden Cancel in the DOM, causing a completed result
        # popup to look structurally like CONFIRM.  Treat semantic success text
        # as success regardless of the generic classifier result.
        if is_alarm_success(label):
            button = await _visible_confirm_button(page)
            if button is not None:
                try:
                    button_label = _compact(await button.inner_text(timeout=800))
                except Exception:
                    button_label = ""
                if progress:
                    progress(f"ALARM SAVE ACK | click={button_label or 'OK'}")
                navigated = await _click_alarm_control(
                    page,
                    button,
                    timeout_ms=step_timeout_ms,
                    progress=progress,
                    label=button_label or "OK",
                )
                if navigated:
                    if progress:
                        progress("ALARM SAVE | success acknowledged; QAC navigated")
                    return
                await page.wait_for_timeout(120)
                continue
            # Success text may render a fraction before the OK button.  Wait
            # for it instead of treating Complete! as UNKNOWN/CONFIRM.
            await page.wait_for_timeout(120)
            continue

        # Success/info acknowledgement on Alarm page.
        if state.kind == "INFO":
            button = await _visible_confirm_button(page)
            if button is not None:
                try:
                    button_label = _compact(await button.inner_text(timeout=800))
                except Exception:
                    button_label = ""
                if progress:
                    progress(f"ALARM SAVE ACK | click={button_label or 'OK'}")
                navigated = await _click_alarm_control(
                    page,
                    button,
                    timeout_ms=step_timeout_ms,
                    progress=progress,
                    label=button_label or "OK",
                )
                # QAC Alarm success acknowledgement often navigates back to
                # measure.html. That navigation itself proves the popup was
                # accepted; the caller will verify the new result ID next.
                if navigated:
                    if progress:
                        progress("ALARM SAVE | success acknowledged; QAC navigated")
                    return
                await page.wait_for_timeout(120)
                continue
            # If the result popup self-closes, let the normal result detector
            # prove commit success instead of guessing.
            await page.wait_for_timeout(120)
            continue

        # A second save confirmation after the first click is not expected.
        # Fail safely rather than clicking an unknown modal.
        raise RuntimeError(
            f"พบ QAC popup ที่ไม่คาดไว้หลังยืนยัน Alarm Save: type={state.kind} | {label[:350]}"
        )

    raise RuntimeError("QAC Alarm Save ยังไม่จบสถานะ Saving/Completed ภายใน 90 วินาที")

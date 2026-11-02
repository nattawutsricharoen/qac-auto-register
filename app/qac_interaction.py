from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from logging.handlers import RotatingFileHandler
from pathlib import Path
from dataclasses import dataclass
from typing import Callable, Literal


QACModalKind = Literal[
    "NONE",
    "BUSY",
    "CONFIRM",
    "INFO",
    "WARNING",
    "ERROR",
    "UNKNOWN",
]


@dataclass
class QACModalState:
    kind: QACModalKind
    text: str = ""
    title: str = ""
    content: str = ""
    has_loader: bool = False
    has_confirm: bool = False
    has_cancel: bool = False
    popup = None


_technical_logger = None


def technical_log_path() -> Path:
    """Optional external log location, otherwise project/logs (not the QAC site)."""
    configured = os.environ.get("QAC_DIAGNOSTIC_LOG_DIR", "").strip()
    return (Path(configured) if configured else Path(__file__).resolve().parents[1] / "logs") / "qac_interaction.log"


def _sanitize_log(value: str) -> str:
    text = str(value)
    text = re.sub(r"(?i)(password|passwd|token|authorization|cookie|security.key)\s*[:=]\s*[^\s|,;]+", r"\1=[REDACTED]", text)
    return text[:1200]


def _log(progress: Callable[[str], None] | None, message: str) -> None:
    """Persist even when no UI progress callback is supplied."""
    global _technical_logger
    safe = _sanitize_log(message)
    try:
        if _technical_logger is None:
            path = technical_log_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            logger = logging.getLogger("qac.interaction")
            logger.setLevel(logging.INFO)
            logger.propagate = False
            if not logger.handlers:
                handler = RotatingFileHandler(path, maxBytes=5_000_000, backupCount=5, encoding="utf-8")
                handler.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
                logger.addHandler(handler)
            _technical_logger = logger
        _technical_logger.info(safe)
    except (OSError, PermissionError):
        # Diagnostic logging must never prevent production work.
        pass
    if progress:
        progress(safe)


def describe_modal_transition(before: str, after: str) -> str:
    return f"QAC MODAL TRANSITION | {before} -> {after}"


def _compact(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split())


def _low(value: str) -> str:
    return _compact(value).casefold()


_BUSY_TOKENS = (
    "loading data",
    "please wait",
    "saving data",
    "กำลังโหลดข้อมูล",
    "กรุณารอสักครู่",
    "กำลังบันทึกข้อมูล",
)
_ERROR_TOKENS = (
    "error",
    "failed",
    "failure",
    "ไม่สามารถ",
    "ผิดพลาด",
    "ไม่ถูกต้อง",
)
_WARNING_TOKENS = (
    "warning",
    "คำเตือน",
)
_CONFIRM_TOKENS = (
    "do you want",
    "confirm",
    "ยืนยัน",
    "ต้องการบันทึก",
)
_SUCCESS_TOKENS = (
    "completed",
    "complete",
    "success",
    "บันทึกสำเร็จ",
    "สำเร็จ",
)



def decide_native_dialog_action(dialog_type: str, message: str) -> str:
    """Return ACCEPT or DISMISS for a native browser dialog.

    Native JavaScript dialogs are not DOM modals.  Normal QAC save flows use
    SweetAlert/Bootbox and are handled semantically elsewhere.  Therefore a
    native confirm/prompt must be treated fail-safe: accept only a clearly
    recognised positive QAC confirmation; dismiss unknown questions/prompts.
    Plain alert dialogs are acknowledgements and may be accepted safely.
    """
    dtype = _low(dialog_type)
    text = _low(message)
    if dtype in ("alert", "beforeunload"):
        return "ACCEPT"
    if dtype == "confirm":
        positive_tokens = (
            "do you want to save",
            "do you want to continue",
            "are you sure",
            "confirm",
            "ต้องการบันทึก",
            "ดำเนินการต่อ",
            "ยืนยัน",
        )
        return "ACCEPT" if any(token in text for token in positive_tokens) else "DISMISS"
    # Never invent text for prompt() and never approve an unknown dialog type.
    return "DISMISS"

def navigation_modal_policy(kind: QACModalKind) -> str:
    """Pure policy used before top-level QAC navigation.

    Passive states may be resolved automatically; confirmations and all
    abnormal/unknown states must stop rather than guess.
    """
    if kind == "NONE":
        return "CONTINUE"
    if kind == "BUSY":
        return "WAIT"
    if kind == "INFO":
        return "ACK"
    return "STOP"


def classify_qac_modal_kind(
    combined_text: str,
    *,
    has_loader: bool,
    has_confirm: bool,
    has_cancel: bool,
) -> QACModalKind:
    """Pure classifier for regression testing against real QAC popup behavior."""
    combined = _low(combined_text)
    if has_loader or any(token in combined for token in _BUSY_TOKENS):
        return "BUSY"
    if any(token in combined for token in _ERROR_TOKENS):
        return "ERROR"
    if any(token in combined for token in _WARNING_TOKENS):
        return "WARNING"
    # QAC old SweetAlert2 can leave a hidden/stale Cancel button in the DOM
    # even after the save has already completed.  Therefore semantic success
    # text must win over the structural has_cancel+has_confirm heuristic.
    if any(token in combined for token in _SUCCESS_TOKENS):
        # A real QAC legacy SweetAlert may render the visible OK button outside
        # the popup subtree, so popup-local has_confirm can be False even for a
        # genuine Complete!/Saved result. Semantic success is sufficient to
        # classify the state as informational; the click path still requires a
        # real visible enabled affirmative button before acknowledging it.
        return "INFO"
    if has_cancel and has_confirm:
        return "CONFIRM"
    if any(token in combined for token in _CONFIRM_TOKENS) and has_confirm:
        return "CONFIRM"
    if has_confirm and not has_cancel:
        return "INFO"
    return "UNKNOWN"


async def install_native_dialog_guard(page, progress: Callable[[str], None] | None = None) -> None:
    """Install one native browser-dialog handler per page.

    Production Check Sheet uses SweetAlert2 for its normal operator flow, but a
    native alert/confirm would block Playwright completely. Keep one guard only
    as a last-resort browser-level acknowledgement and log what happened.
    """
    if bool(getattr(page, "_qac_native_dialog_guard_installed", False)):
        return

    async def _handle(dialog) -> None:
        try:
            msg = _compact(str(dialog.message or ""))
            dtype = str(dialog.type or "")
            action = decide_native_dialog_action(dtype, msg)
            _log(
                progress,
                f"QAC NATIVE DIALOG | type={dtype} | action={action} | message={msg[:240]}",
            )
            if action == "ACCEPT":
                await dialog.accept()
                _log(progress, "QAC NATIVE DIALOG ACCEPTED")
            else:
                await dialog.dismiss()
                _log(progress, "QAC NATIVE DIALOG DISMISSED (fail-safe)")
        except Exception as exc:
            _log(progress, f"QAC NATIVE DIALOG ERROR | {exc}")

    def _on_dialog(dialog) -> None:
        asyncio.create_task(_handle(dialog))

    page.on("dialog", _on_dialog)
    try:
        setattr(page, "_qac_native_dialog_guard_installed", True)
    except Exception:
        pass


async def _visible_swal_popup(page):
    """Return the visible SweetAlert2 popup only.

    IMPORTANT: Bootstrap #modal-view-task is the actual QAC working/Measure
    window. It must NEVER be treated as a popup to auto-acknowledge.
    """
    candidates = (
        # Newer SweetAlert2 uses .swal2-popup. Older QAC pages (notably
        # Alarm / Production Output) use .swal2-modal instead. Support both.
        ".swal2-container:visible .swal2-popup:visible",
        ".swal2-popup:visible",
        ".swal2-container:visible .swal2-modal:visible",
        ".swal2-modal:visible",
    )
    for selector in candidates:
        try:
            loc = page.locator(selector)
            count = await loc.count()
            for idx in range(min(count, 6)):
                popup = loc.nth(idx)
                if await popup.is_visible():
                    return popup
        except Exception:
            continue
    return None


async def _visible_bootbox(page):
    # Kept for compatibility if a Production Check Sheet action invokes Bootbox.
    try:
        loc = page.locator(".bootbox.modal:visible")
        for idx in range(min(await loc.count(), 4)):
            popup = loc.nth(idx)
            if await popup.is_visible():
                return popup
    except Exception:
        pass
    return None


async def inspect_visible_qac_modal(page) -> QACModalState:
    """Classify only transient QAC popups, not the working Measure modal."""
    popup = await _visible_swal_popup(page)
    source = "swal"
    if popup is None:
        popup = await _visible_bootbox(page)
        source = "bootbox"
    if popup is None:
        return QACModalState(kind="NONE")

    try:
        text = _compact(await popup.inner_text(timeout=1200))
    except Exception:
        text = ""

    title = ""
    content = ""
    if source == "swal":
        for selector, attr in (
            (".swal2-title", "title"),
            (".swal2-html-container", "content"),
            (".swal2-content", "content"),
        ):
            try:
                loc = popup.locator(selector).first
                if await loc.count() and await loc.is_visible():
                    value = _compact(await loc.inner_text(timeout=800))
                    if attr == "title":
                        title = value
                    else:
                        content = value
            except Exception:
                pass

    async def _any_visible(selector: str) -> bool:
        try:
            loc = popup.locator(selector)
            for i in range(min(await loc.count(), 12)):
                item = loc.nth(i)
                if await item.is_visible():
                    return True
        except Exception:
            pass
        return False

    # SweetAlert2 versions differ slightly. showLoading() either exposes a
    # loader element or changes the confirm button into a loading state.
    has_loader = await _any_visible(
        ".swal2-loader, .swal2-loading, button.swal2-confirm.swal2-loading, "
        ".swal2-confirm[disabled] .swal2-loader"
    )
    has_confirm = await _any_visible(
        "button.swal2-confirm:not([disabled]), .swal2-confirm:not([disabled]), "
        "button[data-bb-handler='confirm'], button[data-bb-handler='ok']"
    )
    has_cancel = await _any_visible(
        "button.swal2-cancel, .swal2-cancel, button[data-bb-handler='cancel']"
    )

    combined = _low(" ".join(v for v in (title, content, text) if v))

    # Busy must win over the presence of stale/template OK text. The real QAC
    # source explicitly calls swal.showLoading() for Loading/Saving states.
    kind = classify_qac_modal_kind(
        combined,
        has_loader=has_loader,
        has_confirm=has_confirm,
        has_cancel=has_cancel,
    )

    state = QACModalState(
        kind=kind,
        text=text,
        title=title,
        content=content,
        has_loader=has_loader,
        has_confirm=has_confirm,
        has_cancel=has_cancel,
    )
    state.popup = popup
    return state


async def _wait_busy_clear(
    page,
    progress: Callable[[str], None] | None,
    state: QACModalState,
    *,
    timeout_ms: int = 90000,
) -> None:
    label = state.title or state.content or state.text or "QAC busy"
    _log(progress, f"QAC BUSY | {label[:260]}")
    deadline = asyncio.get_running_loop().time() + timeout_ms / 1000.0

    # We intentionally do not click anything. Like a human operator, wait for
    # QAC AJAX/SweetAlert to finish, disappear, or transition into a result.
    while asyncio.get_running_loop().time() < deadline:
        await page.wait_for_timeout(150)
        current = await inspect_visible_qac_modal(page)
        if current.kind == "NONE":
            _log(progress, "QAC BUSY COMPLETE")
            return
        if current.kind != "BUSY":
            _log(progress, f"QAC BUSY TRANSITION | next={current.kind}")
            return

    raise RuntimeError(
        f"QAC ยังอยู่ในสถานะ Loading/Saving เกิน {int(timeout_ms/1000)} วินาที: {label[:220]}"
    )


async def _find_affirmative_button(state: QACModalState, page=None):
    popup = state.popup
    if popup is None:
        return None
    selectors = (
        "button.swal2-confirm:visible:not([disabled])",
        ".swal2-confirm:visible:not([disabled])",
        "button[data-bb-handler='confirm']:visible:not([disabled])",
        "button[data-bb-handler='ok']:visible:not([disabled])",
    )
    for selector in selectors:
        try:
            loc = popup.locator(selector)
            for idx in range(min(await loc.count(), 8)):
                candidate = loc.nth(idx)
                if await candidate.is_visible() and await candidate.is_enabled():
                    return candidate
        except Exception:
            continue

    # Older QAC SweetAlert2 can render the visible OK/confirm button outside
    # the popup subtree used for reading the message.  Alarm and Production
    # Output already handle this layout; the generic register flow must do the
    # same or a real "Complete !" result is misclassified as UNKNOWN.
    if page is not None:
        for selector in selectors:
            try:
                loc = page.locator(selector)
                for idx in range(min(await loc.count(), 12)):
                    candidate = loc.nth(idx)
                    if await candidate.is_visible() and await candidate.is_enabled():
                        return candidate
            except Exception:
                continue
    return None


async def acknowledge_visible_modal(
    page,
    progress: Callable[[str], None] | None = None,
    *,
    wait_ms: int = 1200,
    max_rounds: int = 8,
    busy_timeout_ms: int = 90000,
) -> int:
    """Handle Production Check Sheet transient popups like an operator.

    - BUSY (Loading/Saving): never click; wait for QAC to finish.
    - CONFIRM: click the visible SweetAlert confirm button.
    - INFO/SUCCESS: click a visible acknowledgement, or wait for an explicitly
      recognized buttonless "Complete !" popup to disappear on its own.
    - WARNING/ERROR: stop and surface the exact message.
    - UNKNOWN: stop; never guess-click.

    Returns the number of buttons actually clicked. Waiting for BUSY does not
    increment the count.
    """
    await install_native_dialog_guard(page, progress)

    clicked = 0
    acknowledged_success = False
    for round_no in range(max_rounds):
        deadline = asyncio.get_running_loop().time() + max(0, wait_ms) / 1000.0
        state = QACModalState(kind="NONE")
        while asyncio.get_running_loop().time() <= deadline:
            state = await inspect_visible_qac_modal(page)
            if state.kind != "NONE":
                break
            await page.wait_for_timeout(80)

        if state.kind == "NONE":
            break

        label = state.title or state.content or state.text or "(no text)"
        _log(
            progress,
            f"QAC MODAL | type={state.kind} | loader={int(state.has_loader)} | "
            f"confirm={int(state.has_confirm)} | cancel={int(state.has_cancel)} | {label[:280]}",
        )

        if state.kind == "BUSY":
            await _wait_busy_clear(
                page, progress, state, timeout_ms=busy_timeout_ms
            )
            # Immediately inspect the transition (e.g. BUSY -> Completed).
            continue

        if state.kind in ("ERROR", "WARNING"):
            raise RuntimeError(f"QAC {state.kind}: {label[:500]}")

        if state.kind == "UNKNOWN":
            # Read-only Measure -> Back navigation can leave a blank, fading
            # SweetAlert shell even without a preceding SUCCESS acknowledgement.
            # Never click it. Wait for its actual disappearance; fail closed if
            # the shell persists or acquires any actionable content.
            if (not acknowledged_success and not (state.text or state.title or state.content)
                    and not state.has_loader and not state.has_confirm and not state.has_cancel):
                _log(progress, "QAC EMPTY MODAL SHELL | waiting for teardown; no click")
                cleared = False
                for _ in range(25):
                    await page.wait_for_timeout(100)
                    current = await inspect_visible_qac_modal(page)
                    if current.kind == "NONE":
                        cleared = True
                        break
                    if (current.kind != "UNKNOWN" or current.text or current.title or
                            current.content or current.has_loader or current.has_confirm or
                            current.has_cancel):
                        break
                if cleared:
                    _log(progress, "QAC EMPTY MODAL SHELL CLEARED")
                    continue
            # SweetAlert2 teardown on the QAC site briefly leaves a visible,
            # textless popup shell after the operator clicks Complete! -> OK.
            # Wait for that shell to disappear; never click unknown popups.
            if (acknowledged_success and not (state.text or state.title or state.content)
                    and not state.has_loader and not state.has_confirm and not state.has_cancel):
                _log(progress, "QAC ACK EMPTY SHELL | waiting for SweetAlert teardown")
                disappeared = False
                for _ in range(12):
                    await page.wait_for_timeout(100)
                    current = await inspect_visible_qac_modal(page)
                    if current.kind == "NONE":
                        disappeared = True
                        break
                    if (current.kind != "UNKNOWN" or current.text or current.title or
                            current.content or current.has_loader or current.has_confirm or
                            current.has_cancel):
                        break
                if disappeared:
                    _log(progress, "QAC ACK EMPTY SHELL CLEARED")
                    break
            raise RuntimeError(
                "พบ QAC popup ที่ยังไม่รู้จัก จึงไม่คลิกแทนผู้ใช้: " + label[:400]
            )

        button = await _find_affirmative_button(state, page)
        if button is None:
            # Machine-condition Numeric QAC completes automatically after the
            # operator confirms Save. Its informational "Complete !" popup
            # has no actionable button and disappears as QAC moves next.
            # Never try a second Save or a phantom OK click. Only recognize
            # an explicit successful completion message; unknown INFO fails closed.
            completion_text = _low(" ".join((state.title or "", state.content or ""))).strip()
            is_auto_complete = (state.kind == "INFO" and
                                ("complete !" in completion_text or
                                 "complete!" in completion_text))
            if is_auto_complete:
                _log(progress, "QAC COMPLETE AUTO DISMISS | no button, waiting for popup to disappear")
                deadline = asyncio.get_running_loop().time() + 15.0
                disappeared = False
                while asyncio.get_running_loop().time() < deadline:
                    await page.wait_for_timeout(100)
                    current = await inspect_visible_qac_modal(page)
                    if current.kind == "NONE":
                        disappeared = True
                        break
                    if current.kind in ("ERROR", "WARNING", "CONFIRM"):
                        raise RuntimeError(
                            f"QAC COMPLETE TRANSITION UNEXPECTED | type={current.kind} "
                            f"title={(current.title or '')[:100]}"
                        )
                if not disappeared:
                    raise RuntimeError("QAC COMPLETE AUTO DISMISS TIMEOUT | popup did not disappear; no retry write")
                _log(progress, "QAC COMPLETE AUTO DISMISSED | QAC workflow may advance; saved result pending readback")
                acknowledged_success = True
                continue
            raise RuntimeError(
                f"QAC {state.kind} แสดงอยู่ แต่ไม่พบปุ่มยืนยันที่มองเห็นและกดได้จริง: "
                + label[:300]
            )

        try:
            button_label = _compact(await button.inner_text(timeout=800))
        except Exception:
            button_label = _compact(str(await button.get_attribute("value") or ""))

        action = "CONFIRM" if state.kind == "CONFIRM" else "ACK"
        _log(progress, f"QAC {action} CLICK START | round={round_no+1} | button={button_label or '(button)'}")
        started = time.monotonic()
        try:
            await button.scroll_into_view_if_needed(timeout=10000)
            await button.click(timeout=10000, no_wait_after=True)
        except Exception as exc:
            _log(progress, f"QAC {action} CLICK UNCERTAIN | elapsed_ms={int((time.monotonic()-started)*1000)} | error={type(exc).__name__}: {str(exc)[:350]}")
            try:
                after = await inspect_visible_qac_modal(page)
                _log(progress, describe_modal_transition(state.kind, after.kind))
            except Exception as diagnostic_error:
                _log(progress, f"QAC MODAL RECHECK ERROR | {type(diagnostic_error).__name__}: {str(diagnostic_error)[:180]}")
            # Complete! can auto-dismiss and detach its OK button mid-scroll.
            # This is not a failed Save: the confirmation was already sent.
            # Do not click again; the caller must verify persisted result.
            if state.kind == "INFO" and any(t in _low(label) for t in _SUCCESS_TOKENS):
                after = await inspect_visible_qac_modal(page)
                if after.kind == "NONE":
                    _log(progress, "QAC COMPLETE AUTO DETACHED | no second click; verify persisted result")
                    acknowledged_success = True
                    continue
            raise
        _log(progress, f"QAC {action} CLICK RETURNED | elapsed_ms={int((time.monotonic()-started)*1000)}")
        clicked += 1
        if state.kind == "INFO" and any(token in _low(label) for token in _SUCCESS_TOKENS):
            acknowledged_success = True

        # A confirm commonly transitions to Saving... in the same SweetAlert.
        # Do not require the popup to hide before continuing the state loop.
        await page.wait_for_timeout(120)

    return clicked


async def prepare_for_navigation_action(
    page,
    progress: Callable[[str], None] | None = None,
    *,
    wait_ms: int = 800,
    busy_timeout_ms: int = 90000,
) -> int:
    """Clear only *passive* QAC blockers before a navigation click.

    This is intentionally stricter than :func:`acknowledge_visible_modal`:
    BUSY is waited out and INFO/SUCCESS is acknowledged, but an outstanding
    CONFIRM is never guessed/accepted because it may belong to a previous user
    action.  This is the safe policy for top-level navigation such as VIEW MORE.

    Returns the number of acknowledgement buttons clicked.
    """
    await install_native_dialog_guard(page, progress)
    clicked = 0
    for _ in range(8):
        deadline = asyncio.get_running_loop().time() + max(0, wait_ms) / 1000.0
        state = QACModalState(kind="NONE")
        while asyncio.get_running_loop().time() <= deadline:
            state = await inspect_visible_qac_modal(page)
            if state.kind != "NONE":
                break
            await page.wait_for_timeout(80)

        if state.kind == "NONE":
            return clicked

        label = state.title or state.content or state.text or "(no text)"
        _log(progress, f"QAC NAV BLOCKER | type={state.kind} | {label[:280]}")

        policy = navigation_modal_policy(state.kind)
        if policy == "WAIT":
            await _wait_busy_clear(page, progress, state, timeout_ms=busy_timeout_ms)
            continue

        if policy == "ACK":
            button = await _find_affirmative_button(state, page)
            if button is None:
                raise RuntimeError(
                    "QAC INFO popup ขวางการ Navigation แต่ไม่พบปุ่ม OK ที่กดได้: "
                    + label[:300]
                )
            try:
                button_label = _compact(await button.inner_text(timeout=800))
            except Exception:
                button_label = ""
            _log(progress, f"QAC NAV ACK CLICK START | button={button_label or '(button)'}")
            try:
                await button.scroll_into_view_if_needed(timeout=10000)
                await button.click(timeout=10000, no_wait_after=True)
            except Exception as exc:
                _log(progress, f"QAC NAV ACK UNCERTAIN | {type(exc).__name__}: {str(exc)[:350]}")
                raise
            _log(progress, "QAC NAV ACK CLICK RETURNED")
            clicked += 1
            await page.wait_for_timeout(120)
            continue

        if state.kind == "CONFIRM":
            raise RuntimeError(
                "พบ QAC confirmation ค้างก่อนเปิด Module จึงไม่กดยืนยันแทนผู้ใช้: "
                + label[:400]
            )
        if state.kind in ("WARNING", "ERROR"):
            raise RuntimeError(f"QAC {state.kind}: {label[:500]}")
        raise RuntimeError(
            "พบ QAC popup ที่ยังไม่รู้จักและกำลังขวางการ Navigation: " + label[:400]
        )

    return clicked


async def interaction_checkpoint(
    page,
    progress: Callable[[str], None] | None = None,
    *,
    name: str = "",
    wait_ms: int = 400,
) -> int:
    """Resolve transient QAC state before the next human-like action."""
    count = await acknowledge_visible_modal(page, progress, wait_ms=wait_ms)
    if name:
        _log(progress, f"QAC ACTION READY | {name} | clicked={count}")
    return count

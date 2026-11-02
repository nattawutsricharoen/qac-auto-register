from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Optional

from playwright.async_api import async_playwright, Page, BrowserContext

from .qac_interaction import prepare_for_navigation_action


QAC_HOME_URL = "http://159.228.251.234:8077/"


@dataclass(frozen=True)
class QACModule:
    key: str
    process: str
    product_type: str
    process_name: str
    window_tag: str

    @property
    def menu_selector(self) -> str:
        return (
            'a.btn.btn-sm.btn-primary'
            '[data-factory-process="2"]'
            f'[data-process="{self.process}"]'
            f'[data-product-type="{self.product_type}"]'
            '[data-factory-name="Inflator"]'
        )


QAC_MODULES = {
    "auto_register": QACModule(
        key="auto_register",
        process="18",
        product_type="11",
        process_name="Production Control Board",
        window_tag="QAC_AUTO_REGISTER_MODULE",
    ),
    "sample_register": QACModule(
        key="sample_register",
        process="25",
        product_type="17",
        process_name="Production Check Sheet (Sample Register)",
        window_tag="QAC_SAMPLE_REGISTER_MODULE",
    ),
    "daily_document": QACModule(
        key="daily_document",
        process="25",
        product_type="17",
        process_name="Production Check Sheet",
        window_tag="QAC_DAILY_DOCUMENT_MODULE",
    ),
}


def navigation_was_dispatched(
    before_url: str,
    current_url: str,
    *,
    new_page_seen: bool = False,
    module_detected: bool = False,
) -> bool:
    """Pure recovery rule for successful QAC clicks that timed out locally."""
    if new_page_seen or module_detected:
        return True
    before = str(before_url or "").strip()
    current = str(current_url or "").strip()
    return bool(current and current != before)


async def _safe_url(page: Page) -> str:
    try:
        return str(page.url or "")
    except Exception:
        return ""




def is_trusted_qac_url(url: str) -> bool:
    """Exact QAC server origin; no substring matching or external-site adoption."""
    from urllib.parse import urlsplit
    try:
        candidate = urlsplit(str(url or ''))
        expected = urlsplit(QAC_HOME_URL)
        return (candidate.scheme, candidate.hostname, candidate.port or 80) == (expected.scheme, expected.hostname, expected.port or 80)
    except (ValueError, TypeError):
        return False


async def require_owned_qac_page(page: Page, *, tag: str, ready_selector: str = '') -> None:
    """Fail closed if QAC's module tab was navigated to another website."""
    if page.is_closed() or not is_trusted_qac_url(await _safe_url(page)):
        raise RuntimeError('QAC PAGE LOST | module tab was closed or navigated outside QAC; paused safely')
    if (await _window_name(page)) != tag:
        raise RuntimeError('QAC PAGE OWNERSHIP LOST | refusing to use another Edge tab')
    if ready_selector and not await page.locator(ready_selector).count():
        raise RuntimeError('QAC PAGE NOT READY | expected QAC module DOM not found')


async def _has_visible(page: Page, selector: str) -> bool:
    """Return True only when at least one matching element is actually visible.

    QAC keeps menu cards in the DOM after entering a process, but hides them.
    Using locator.count() alone therefore causes the app to mistake an already
    opened module for the home menu and click a hidden VIEW MORE button.
    """
    try:
        loc = page.locator(selector)
        count = await loc.count()
        for i in range(min(count, 20)):
            try:
                if await loc.nth(i).is_visible():
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


async def _has_daily_document_ui(page: Page) -> bool:
    """Detect Production Check Sheet by its live module UI, not menu text."""
    if await _is_login_page(page):
        return False
    selectors = (
        'tr[data-task]',
        '.calendar-monitor',
        'a.menu-measure-task',
        'a.menu-view-task[data-task]',
    )
    for selector in selectors:
        try:
            if await page.locator(selector).count() > 0:
                return True
        except Exception:
            pass
    return False

async def _window_name(page: Page) -> str:
    try:
        return str(await page.evaluate("window.name || ''") or "")
    except Exception:
        return ""


async def _is_login_page(page: Page) -> bool:
    try:
        user_count = await page.locator(
            'input.form-control[placeholder="username"]'
        ).count()
        pass_count = await page.locator(
            'input.form-control[placeholder="password"]'
        ).count()
        return user_count > 0 and pass_count > 0
    except Exception:
        return False


async def _is_module_page(page: Page, module: QACModule) -> bool:
    # A tagged tab can later be redirected back to Login after session expiry.
    # Never treat a login page as an already-open module.
    if not is_trusted_qac_url(await _safe_url(page)) or await _is_login_page(page):
        return False

    # Production Check Sheet has strong live-DOM markers. Check these before
    # looking at the menu card because QAC leaves hidden VIEW MORE cards in DOM.
    if module.key in ("daily_document", "sample_register") and await _has_daily_document_ui(page):
        return (await _window_name(page)) == module.window_tag

    # First choice: page tagged by this application. window.name survives reload
    # and normal same-tab navigation, making repeated tab switching reliable.
    if await _window_name(page) == module.window_tag:
        # Only a *visible* menu card means this tab has really returned home.
        if await _has_visible(page, module.menu_selector):
            return False
        return True

    url = (await _safe_url(page)).lower()

    # Tagged pages of other workflows must never be claimed by this module.
    tag = await _window_name(page)
    if tag in {m.window_tag for m in QAC_MODULES.values()} and tag != module.window_tag:
        return False
    # Never adopt an untagged live Check Sheet as Sample; ownership must be explicit.
    if module.key == "sample_register":
        return False

    # Heuristics for sessions/pages opened manually before this application.
    # Do not use generic measure.html alone because both QAC modules may open
    # measure pages and must not be confused with each other.
    markers = {
        "auto_register": (
            "production control board",
            "control board",
        ),
        "sample_register": (
            "production check sheet", "check sheet",
        ),
        "daily_document": (
            "production check sheet",
            "check sheet",
        ),
    }.get(module.key, ())

    try:
        title = (await page.title()).lower()
    except Exception:
        title = ""

    if any(m in title or m.replace(" ", "") in url.replace("_", "") for m in markers):
        return True

    try:
        body_text = (await page.locator("body").inner_text(timeout=700)).lower()
        if any(m in body_text for m in markers):
            # Avoid treating the QAC home/menu page as already inside the module:
            # the home page can contain both module names in VIEW MORE cards.
            home_has_target_menu = await _has_visible(page, module.menu_selector)
            if not home_has_target_menu:
                return True
    except Exception:
        pass

    return False


async def _find_existing_module_page(
    context: BrowserContext,
    module: QACModule,
) -> Optional[Page]:
    for page in context.pages:
        if not await _is_module_page(page, module):
            continue
        # A tagged Daily Document tab may currently be inside measure.html.
        # Batch scan/collector operations require the task-list page, so do not
        # reuse a measure page as if it were the module list.
        if module.key in ("daily_document", "sample_register") and not await _has_daily_document_ui(page):
            continue
        return page
    return None


async def _get_or_create_menu_page(
    context: BrowserContext,
    home_url: str,
) -> Page:
    # Prefer an existing QAC menu/login tab. Never repurpose an active
    # measure.html document tab because it may be in use by another workflow.
    for page in context.pages:
        if await _window_name(page) in {m.window_tag for m in QAC_MODULES.values()}:
            continue
        url = (await _safe_url(page)).lower()
        if "measure.html" in url:
            continue
        if await _is_login_page(page):
            return page
        try:
            if await _has_visible(page, 'a[data-factory-process="2"]'):
                return page
        except Exception:
            pass
        if url.rstrip("/") == home_url.rstrip("/").lower():
            return page

    # All existing QAC tabs may belong to active workflows. NEVER navigate
    # Auto Register, Daily Document or Sample away from their live module page.
    # Create a fresh home tab only for a module not yet opened.
    page = await context.new_page()
    await page.goto(home_url, wait_until="domcontentloaded", timeout=30000)
    return page


async def _login_if_needed(
    page: Page,
    employee_id: str,
    progress=None,
) -> bool:
    if not await _is_login_page(page):
        return False

    emp = str(employee_id or "").strip()
    if not emp:
        raise RuntimeError("กรุณากรอก Employee ID ก่อนเชื่อมต่อ QAC")

    if progress:
        progress("QAC LOGIN | กำลังเข้าสู่ระบบด้วย Employee ID")

    username = page.locator(
        'input.form-control[placeholder="username"]'
    ).first
    password = page.locator(
        'input.form-control[placeholder="password"]'
    ).first
    sign_in = page.locator(
        'button.form-control.btn.bg-blue-active.btn-flat'
    ).first

    await username.fill(emp)
    await password.fill(emp)
    await sign_in.click()

    # Sign-in is successful only after the login controls disappear. QAC may
    # continue loading menu data after DOMContentLoaded, so give it a bounded
    # ready window instead of assuming click == login complete.
    try:
        await username.wait_for(state="detached", timeout=30000)
    except Exception:
        if await _is_login_page(page):
            raise RuntimeError(
                "QAC Sign In ไม่สำเร็จ หรือหน้า QAC ยังไม่ตอบสนองภายใน 30 วินาที"
            )

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=15000)
    except Exception:
        pass
    await page.wait_for_timeout(800)
    return True


async def ensure_qac_session_and_module_async(
    cdp_url: str,
    employee_id: str,
    module_key: str | None = None,
    home_url: str = QAC_HOME_URL,
    progress=None,
) -> dict:
    """Ensure QAC login and optionally enter one QAC module.

    This function is intentionally navigation-only. Auto Register and Daily
    Document business logic stay in their own modules/workers.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")
        context = browser.contexts[0]

        module = None
        if module_key:
            module = QAC_MODULES.get(module_key)
            if module is None:
                raise RuntimeError(f"Unknown QAC module: {module_key}")

            existing = await _find_existing_module_page(context, module)
            if existing is not None:
                try:
                    await existing.bring_to_front()
                except Exception:
                    pass
                if progress:
                    progress(
                        f"QAC MODULE READY | {module.process_name} เปิดอยู่แล้ว ไม่กด VIEW MORE ซ้ำ"
                    )
                return {
                    "ok": True,
                    "logged_in": True,
                    "module": module.key,
                    "module_name": module.process_name,
                    "opened": False,
                    "reused": True,
                    "url": await _safe_url(existing),
                }

        page = await _get_or_create_menu_page(context, home_url)

        # If this is an old non-login QAC page, navigate to home only when the
        # required menu is not available. This preserves an already-good page.
        if not await _is_login_page(page):
            target_available = False
            if module is not None:
                try:
                    target_available = await _has_visible(page, module.menu_selector)
                except Exception:
                    target_available = False
            if module is None or not target_available:
                url = (await _safe_url(page)).lower()
                if url.rstrip("/") != home_url.rstrip("/").lower():
                    if progress:
                        progress("QAC HOME | เปิดหน้าหลัก QAC")
                    await page.goto(home_url, wait_until="domcontentloaded", timeout=30000)

        logged_now = await _login_if_needed(page, employee_id, progress)

        if module is None:
            if progress:
                progress("QAC SESSION READY | Login สำเร็จ")
            return {
                "ok": True,
                "logged_in": True,
                "logged_now": logged_now,
                "module": None,
                "opened": False,
                "reused": False,
                "url": await _safe_url(page),
            }

        # QAC menu cards may be populated asynchronously after login.
        selector = module.menu_selector
        try:
            await page.locator(selector).first.wait_for(state="visible", timeout=20000)
        except Exception:
            # One normal recovery refresh is safe here: no document edit has
            # started yet. It also handles the user's observed incomplete-load
            # condition on the QAC menu page.
            if progress:
                progress(
                    f"QAC MENU INCOMPLETE | ไม่พบ {module.process_name} → Refresh แล้วเริ่ม Navigation ใหม่"
                )
            await page.reload(wait_until="domcontentloaded", timeout=30000)
            await _login_if_needed(page, employee_id, progress)
            await page.locator(selector).first.wait_for(state="visible", timeout=20000)

        before_pages = set(id(p) for p in context.pages)
        before_url = await _safe_url(page)
        if progress:
            progress(f"QAC MODULE | เปิด {module.process_name}")

        # A login/result SweetAlert can remain visible after the menu itself is
        # ready and physically intercept VIEW MORE.  Clear only passive blockers
        # (BUSY/INFO). Never accept an unrelated confirmation here.
        await prepare_for_navigation_action(page, progress, wait_ms=900)

        target = page.locator(selector).first
        click_error = None
        try:
            # QAC can navigate/detach the menu element while Playwright is still
            # finalising the click. no_wait_after avoids turning a successful
            # dispatch into a false 30s navigation timeout.
            await target.click(timeout=15000, no_wait_after=True)
        except Exception as exc:
            click_error = exc

        # Give QAC a bounded window to navigate or create a new tab.  A click can
        # legitimately throw after the element is detached even though QAC has
        # already accepted it; decide by resulting browser state, not exception
        # text alone.
        candidate = page
        dispatched = False
        for _ in range(60):  # up to ~6 seconds
            for p in context.pages:
                if id(p) not in before_pages:
                    candidate = p
                    dispatched = True
                    break
            if dispatched:
                break

            current_url = await _safe_url(page)
            module_detected = await _is_module_page(page, module)
            if navigation_was_dispatched(
                before_url, current_url, module_detected=module_detected
            ):
                candidate = page
                dispatched = True
                break
            await page.wait_for_timeout(100)

        if click_error is not None and not dispatched:
            # One safe retry is permitted only when the browser is provably still
            # on the same menu state. This avoids double-opening a module after a
            # successful-but-timeout click.
            if progress:
                progress("QAC MODULE CLICK RETRY | action ยังไม่ถูกส่ง → ตรวจ popup แล้วลองอีกครั้ง")
            await prepare_for_navigation_action(page, progress, wait_ms=700)
            await page.locator(selector).first.wait_for(state="visible", timeout=10000)
            await page.locator(selector).first.click(timeout=10000, no_wait_after=True)
            click_error = None
            await page.wait_for_timeout(500)
            candidate = page
            for p in context.pages:
                if id(p) not in before_pages:
                    candidate = p
                    break
        elif click_error is not None and progress:
            progress("QAC MODULE CLICK RECOVERED | click timeout แต่ QAC navigation เริ่มแล้ว → ทำงานต่อ")

        try:
            await candidate.evaluate("tag => { window.name = tag; }", module.window_tag)
        except Exception:
            pass
        # QAC renders module data through jQuery after normal page load. Do not
        # report MODULE READY until both browser load and QAC AJAX are complete.
        try:
            await candidate.wait_for_function(
                "document.readyState === 'complete' && "
                "(!window.jQuery || window.jQuery.active === 0)",
                timeout=90000,
            )
            if module.key in ("daily_document", "sample_register"):
                await candidate.locator(
                    ".calendar-monitor, tr[data-task]"
                ).first.wait_for(state="attached", timeout=90000)
            elif module.key == "auto_register":
                # When PCB opens directly into measure.html, do not announce READY
                # until the document header/event controls have actually arrived.
                current_url = (await _safe_url(candidate)).lower()
                if "measure.html" in current_url:
                    await candidate.locator(
                        "h1[data-title][data-line-id], select.dropdown_topic, select.dropdown_model"
                    ).first.wait_for(state="attached", timeout=90000)
        except Exception as exc:
            raise RuntimeError(
                f"QAC {module.process_name} โหลดไม่ Complete ภายใน 90 วินาที"
            ) from exc
        try:
            await candidate.bring_to_front()
        except Exception:
            pass

        if progress:
            progress(f"QAC MODULE READY | {module.process_name}")

        return {
            "ok": True,
            "logged_in": True,
            "logged_now": logged_now,
            "module": module.key,
            "module_name": module.process_name,
            "opened": True,
            "reused": False,
            "url": await _safe_url(candidate),
        }

from __future__ import annotations
import time
import asyncio
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError

from .qac_sync import (
    sync_events_incremental,
    read_document_identity,
    cache_saved_result,
    cache_event_payload,
)
from .qac_interaction import acknowledge_visible_modal, install_native_dialog_guard
from .qac_production_output_adapter import handle_production_output_commit
from .qac_alarm_adapter import save_alarm_event

SAVE_TIMEOUT_MS = 60000
STEP_TIMEOUT_MS = 10000
QAC_SELECT_READY_MS = 4500
QAC_REFRESH_TIMEOUT_MS = 30000
QAC_MAX_REFRESH_RESTARTS = 2


class QACPageIncomplete(RuntimeError):
    """QAC DOM exists but dynamic page data/options are not fully loaded."""


def _fmt(hhmm: str) -> str:
    h, m = map(int, hhmm.split(":"))
    suffix = "AM" if h < 12 else "PM"
    hh = h % 12 or 12
    return f"{hh}:{m:02d} {suffix}"

async def _active_form(page):
    forms = page.locator(".task-downtime:visible")
    if await forms.count() < 1:
        raise RuntimeError("ไม่พบ New Time & Event form ที่กำลังแสดง")
    return forms.last

async def _set_select(form, selector: str, value: str):
    loc = form.locator(selector).first
    try:
        await loc.wait_for(state="attached", timeout=STEP_TIMEOUT_MS)
    except Exception as exc:
        raise QACPageIncomplete(
            f"ไม่พบ QAC dropdown ที่พร้อมใช้งาน: {selector}"
        ) from exc

    wanted = str(value or "").strip()
    deadline = time.monotonic() + QAC_SELECT_READY_MS / 1000
    last_options = []

    while time.monotonic() < deadline:
        try:
            last_options = await loc.locator("option").evaluate_all(
                """els => els.map(x => ({
                    value: String(x.value || '').trim(),
                    text: String(x.textContent || '').trim()
                }))"""
            )
            if any(str(x.get("value", "")).strip() == wanted for x in last_options):
                break
        except Exception:
            pass
        await loc.page.wait_for_timeout(150)
    else:
        raise QACPageIncomplete(
            f"QAC โหลดข้อมูลไม่สมบูรณ์: ไม่พบ option [{wanted}] ใน {selector} "
            f"| available={last_options[:12]}"
        )

    try:
        await loc.select_option(value=wanted, timeout=3000)
    except Exception as exc:
        raise QACPageIncomplete(
            f"QAC dropdown ยังไม่พร้อมเลือก [{wanted}] ใน {selector}"
        ) from exc

    await loc.dispatch_event("change")
    await loc.page.wait_for_timeout(40)



async def _set_select_contains(
    form,
    selector: str,
    text_contains: str
):
    loc = form.locator(selector).first
    await loc.wait_for(
        state="attached",
        timeout=STEP_TIMEOUT_MS
    )

    needle = " ".join(str(text_contains or "").strip().lower().split())
    deadline = time.monotonic() + 1.8
    options = []
    matches = []

    while time.monotonic() < deadline:
        try:
            options = await loc.locator("option").evaluate_all(
                """els => els.map(x => ({
                    value: String(x.value || '').trim(),
                    text: String(x.textContent || '').trim()
                }))"""
            )
            matches = []
            for option in options:
                text = " ".join(str(option.get("text", "")).strip().lower().split())
                value = str(option.get("value", "")).strip()
                if needle in text and value:
                    matches.append(option)
            if matches:
                break
        except Exception:
            pass
        await loc.page.wait_for_timeout(80)

    if len(matches) == 0:
        raise QACPageIncomplete(
            f"QAC โหลดข้อมูลไม่สมบูรณ์: ไม่พบ Machine ที่มีคำว่า "
            f"'{text_contains}' | available={options[:12]}"
        )

    if len(matches) > 1:
        raise RuntimeError(
            f"พบ Machine ที่มีคำว่า "
            f"'{text_contains}' มากกว่า 1 รายการ "
            f"| matches={matches}"
        )

    await loc.select_option(
        value=str(matches[0]["value"]).strip(),
        timeout=STEP_TIMEOUT_MS
    )
    await loc.dispatch_event("change")
    await loc.page.wait_for_timeout(40)


async def _wait_select_option(loc, *, value: str = "", label: str = "", timeout_ms: int = 1800):
    """Wait briefly for asynchronously populated QAC <option> data.

    QAC often attaches the select before its AJAX options arrive.  The old code
    treated that short gap as a broken page and immediately F5/restarted the
    whole record, which was both slow and unstable.
    """
    deadline = time.monotonic() + max(0, timeout_ms) / 1000.0
    target_value = str(value or "").strip()
    target_label = " ".join(str(label or "").split()).casefold()
    last_options = []
    while time.monotonic() < deadline:
        try:
            last_options = await loc.locator("option").evaluate_all(
                """els => els.map(x => ({
                    value: String(x.value || '').trim(),
                    text: String(x.textContent || '').trim()
                }))"""
            )
            for option in last_options:
                ov = str(option.get("value", "") or "").strip()
                ot = " ".join(str(option.get("text", "") or "").split()).casefold()
                if target_value and ov == target_value:
                    return ov, last_options
                if target_label and ot == target_label:
                    return ov, last_options
        except Exception:
            pass
        await loc.page.wait_for_timeout(80)
    return "", last_options


async def _set_select_config(
    form,
    selector: str,
    value: str = "",
    label: str = ""
):
    loc = form.locator(selector).first
    await loc.wait_for(
        state="attached",
        timeout=STEP_TIMEOUT_MS
    )

    value = str(value or "").strip()
    label = " ".join(str(label or "").split())

    # Fast path first: if QAC has already populated the option, select it with
    # no fixed sleep.  If AJAX is still filling the dropdown, wait on the
    # actual option instead of refreshing the entire QAC page.
    selected_value, options = await _wait_select_option(
        loc, value=value, label=label, timeout_ms=1800
    )
    if not selected_value:
        raise QACPageIncomplete(
            f"QAC โหลดข้อมูลไม่สมบูรณ์: ไม่พบ option '{label}' ใน {selector} "
            f"| available={options[:12]}"
        )

    await loc.select_option(value=selected_value, timeout=STEP_TIMEOUT_MS)
    await loc.dispatch_event("change")

    # Yield one browser turn only. Dependent selects now wait for their own
    # concrete option rather than paying a fixed delay after every field.
    await loc.page.wait_for_timeout(40)

async def _refresh_qac_page(page, progress=None, prefix: str = ""):
    if progress:
        progress(f"{prefix} QAC โหลดไม่สมบูรณ์ -> Refresh (F5) อัตโนมัติ")

    try:
        await page.reload(
            wait_until="domcontentloaded",
            timeout=QAC_REFRESH_TIMEOUT_MS
        )
    except Exception:
        # A QAC page can keep background requests open.  The reload itself may
        # still have succeeded, so continue with a bounded DOM wait.
        pass

    try:
        await page.wait_for_load_state("domcontentloaded", timeout=10000)
    except Exception:
        pass

    await page.wait_for_timeout(1500)


async def _prepare_with_refresh_restart(
    page,
    prepare_once,
    prefix: str,
    progress=None,
    max_restarts: int = QAC_MAX_REFRESH_RESTARTS,
):
    """Prepare one QAC record; refresh and restart the record if options vanish.

    IMPORTANT: prepare_once must stop before Save.  This guarantees that a
    refresh never repeats a record that may already have been committed.
    """
    for attempt in range(max_restarts + 1):
        try:
            return await prepare_once()
        except QACPageIncomplete as exc:
            if attempt >= max_restarts:
                raise RuntimeError(
                    f"QAC โหลดข้อมูลไม่สมบูรณ์หลัง Refresh {max_restarts} ครั้ง | {exc}"
                ) from exc

            if progress:
                progress(
                    f"{prefix} ตรวจพบหน้า QAC โหลดไม่ครบ: {exc}"
                )

            await _refresh_qac_page(page, progress, prefix)

            if progress:
                progress(
                    f"{prefix} เริ่มกระบวนการรายการนี้ใหม่ตั้งแต่ต้น "
                    f"({attempt + 1}/{max_restarts})"
                )


async def _fill(form, selector: str, value: str):
    loc = form.locator(selector).first
    await loc.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)
    await loc.fill(value)
    await loc.dispatch_event("input")
    await loc.dispatch_event("change")
    await loc.dispatch_event("blur")



async def _open_new_event(page):
    """
    Click the visible New Time & Event step and return only the active visible
    task-downtime form. QAC keeps hidden/cloned forms in the DOM.
    """
    steps = page.locator(
        ".f1-step:visible",
        has_text="New Time & Event"
    )

    if await steps.count() < 1:
        raise QACPageIncomplete("ไม่พบปุ่ม New Time & Event - หน้า QAC อาจโหลดไม่ครบ")

    await steps.last.click()

    deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000

    while time.monotonic() < deadline:
        try:
            form = await _active_form(page)
            topic = form.locator("select.dropdown_topic").first

            if await topic.count() and await topic.is_visible():
                return form
        except Exception:
            pass

        await page.wait_for_timeout(100)

    raise QACPageIncomplete(
        "กด New Time & Event แล้ว แต่ไม่พบฟอร์มที่กำลังแสดง"
    )


async def _result_ids(page):
    values = await page.evaluate("""() => [...new Set(
        [...document.querySelectorAll('.f1-step[data-result], .task-downtime[data-result-id]')]
        .map(e => e.getAttribute('data-result') || e.getAttribute('data-result-id'))
        .filter(v => v && v !== '0')
    )]""")
    return set(values)

async def _save(page, form):
    # Operator flow: visible Save -> QAC Confirm -> Saving/Loading -> Result.
    # The shared interaction controller understands the real Production Check
    # Sheet SweetAlert states and never clicks a loading spinner.
    await install_native_dialog_guard(page)
    save = form.locator("button.btn-save:visible:not([disabled])").first

    if await save.count() < 1:
        raise RuntimeError("ไม่พบปุ่ม Save / บันทึก ที่พร้อมใช้งาน")

    # SweetAlert/Time Event DOM is frequently replaced while save is in flight.
    # A Playwright actionability failure does NOT prove that QAC rejected Save.
    # Send the click at most once; the caller must verify a new result identity.
    try:
        await save.click(timeout=STEP_TIMEOUT_MS, no_wait_after=True)
    except Exception as e:
        if not _is_navigation_context_error(e) and not _is_transient_dom_click_error(e):
            raise

    try:
        await acknowledge_visible_modal(
            page, None, wait_ms=350, max_rounds=8, busy_timeout_ms=90000
        )
    except Exception as e:
        if _is_navigation_context_error(e):
            await _wait_page_ready_after_navigation(page, timeout_ms=2500)
        elif _is_transient_dom_click_error(e):
            # QAC may have processed Save; the caller verifies actual Result ID.
            pass
        else:
            raise

def _is_transient_dom_click_error(error) -> bool:
    """An uncertain click requires result verification, never an automatic retry."""
    value = str(error or '').casefold()
    return any(token in value for token in (
        'not attached to the dom', 'element was detached',
        'element is not stable', 'element is not attached',
        'locator.click: timeout', 'locator.scroll_into_view_if_needed: timeout',
    ))


def _is_navigation_context_error(error) -> bool:
    text = str(error or "").lower()
    return any(
        token in text
        for token in (
            "execution context was destroyed",
            "most likely because of a navigation",
            "cannot find context with specified id",
            "frame was detached",
        )
    )


async def _wait_page_ready_after_navigation(page, timeout_ms: int = 5000):
    deadline = time.monotonic() + (timeout_ms / 1000)
    while time.monotonic() < deadline:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=800)
        except Exception:
            pass
        try:
            if await page.evaluate("() => Boolean(document && document.body)"):
                return True
        except Exception:
            pass
        await page.wait_for_timeout(100)
    return False


def _normalize_qac_date(value):
    from datetime import datetime
    raw = str(value or '').strip()
    for fmt in ('%Y-%m-%d', '%d-%m-%Y', '%d/%m/%Y', '%Y/%m/%d'):
        try:
            return datetime.strptime(raw, fmt).strftime('%Y-%m-%d')
        except ValueError:
            pass
    return raw


async def _assert_document_identity(page, expected: dict):
    """Do not write unless independent, live document identity matches scan."""
    if not expected:
        raise RuntimeError('MISSING_DOCUMENT_IDENTITY: scan again before writing')
    actual = await read_document_identity(page)
    for key in ('production_date', 'line', 'document_no'):
        old = str(expected.get(key) or '').strip()
        now = str(actual.get(key) or '').strip()
        if key == 'production_date':
            old, now = _normalize_qac_date(old), _normalize_qac_date(now)
        if not old or not now or old.casefold() != now.casefold():
            raise RuntimeError(f'DOCUMENT_CHANGED: {key}; write blocked; rescan required')
    # An absent Shift on Measure is expected; if it is present, it must match.
    if actual.get('shift') and expected.get('shift') and actual['shift'].casefold() != expected['shift'].casefold():
        raise RuntimeError('DOCUMENT_CHANGED: shift; write blocked')
    # The same CDP tab URL can navigate; compare its document identity too.
    if expected.get('url') and actual.get('url') and str(expected['url']).split('#')[0] != str(actual['url']).split('#')[0]:
        raise RuntimeError('DOCUMENT_CHANGED: url; write blocked')
    return actual


async def _wait_complete(page, before_ids, before_count):
    deadline = time.monotonic() + SAVE_TIMEOUT_MS / 1000
    navigation_retries = 0

    while time.monotonic() < deadline:
        try:
            popup = page.locator(".swal2-popup:visible")
            if await popup.count():
                text = (await popup.first.inner_text()).strip()
                low = text.lower()
                if "error" in low or "ไม่สามารถ" in text or "ไม่ถูกต้อง" in text:
                    raise RuntimeError(f"QAC Error: {text}")

            current_ids = await _result_ids(page)
            new_ids = current_ids - before_ids
            if new_ids:
                if len(new_ids) != 1:
                    raise RuntimeError(
                        f"AMBIGUOUS_SAVE_RESULT: {len(new_ids)} new IDs detected; "
                        "cannot attribute save to this worker"
                    )
                return next(iter(new_ids))

            timeline_count = await page.locator(".f1-step[data-result]").count()
            if timeline_count > before_count:
                await page.wait_for_timeout(120)
                continue

        except RuntimeError:
            raise
        except Exception as e:
            if _is_navigation_context_error(e):
                navigation_retries += 1
                await _wait_page_ready_after_navigation(page, timeout_ms=2500)
            await page.wait_for_timeout(100)
            continue

        await page.wait_for_timeout(150)

    raise RuntimeError(
        "QAC ยังไม่ Complete/ไม่พบ Result ใหม่ภายใน "
        f"{int(SAVE_TIMEOUT_MS/1000)} วินาที "
        f"(navigation_retries={navigation_retries})"
    )


def _norm_text(value) -> str:
    return " ".join(str(value or "").strip().lower().split())

def _norm_clock(value) -> str:
    raw = str(value or "").strip()
    if not raw: return ""
    for fmt in ("%H:%M:%S","%H:%M","%I:%M %p","%I:%M:%S %p"):
        try:
            dt = time.strptime(raw.upper(), fmt)
            return f"{dt.tm_hour:02d}:{dt.tm_min:02d}"
        except ValueError:
            pass
    return raw.lower()

async def _existing_events(page):
    return await page.evaluate("""() => {
        const roots=[...document.querySelectorAll('.task-downtime[data-result-id], .fieldset.task-downtime[data-result-id]')];
        const seen=new Set(), out=[];
        const val=(r,s)=>{const e=r.querySelector(s); return e?String(e.value||'').trim():'';};
        const text=(r,s)=>{
            const e=r.querySelector(s);
            if(!e) return '';
            const o=e.options ? e.options[e.selectedIndex] : null;
            return String(o ? o.textContent : '').trim();
        };
        for(const r of roots){
            const id=String(r.getAttribute('data-result-id')||'').trim();
            if(!id||id==='0'||seen.has(id)) continue;
            seen.add(id);
            out.push({
                result_id:id,
                topic_value:val(r,'select.dropdown_topic'),
                topic_label:text(r,'select.dropdown_topic'),
                category_value:val(r,'select.dropdown_topic_sub'),
                category_label:text(r,'select.dropdown_topic_sub'),
                model_value:val(r,'select.dropdown_model'),
                model_label:text(r,'select.dropdown_model'),
                machine_value:val(r,'select.dropdown_machine'),
                machine_label:text(r,'select.dropdown_machine'),
                start:val(r,'.startCheck input'),
                end:val(r,'.endCheck input'),
                description:val(r,'textarea.txt-comment'),
                process_value:val(r,'select.dropdown_i-tag_process_sub'),
                actual_qty:(() => {
                    const inputs=[...r.querySelectorAll('input')];
                    for(const el of inputs){
                        const meta=(
                            String(el.name||'')+' '+
                            String(el.id||'')+' '+
                            String(el.className||'')
                        ).toLowerCase();
                        if(meta.includes('actual')){
                            return String(el.value||'').trim();
                        }
                        const p=el.closest('.form-group,.row,[class*="col-"]');
                        const t=String(p ? p.innerText : '').toLowerCase();
                        if(
                            t.includes('actual (qty)') ||
                            t.includes('จำนวนชิ้นงานจริง')
                        ){
                            return String(el.value||'').trim();
                        }
                    }
                    return '';
                })()
            });
        }
        return out;
    }""")

def _existing_alarm_key(row):
    return (
        str(row.get("topic_value") or ""),
        str(row.get("category_value") or ""),
        str(row.get("model_value") or ""),
        str(row.get("machine_value") or ""),
        _norm_clock(row.get("start")),
        _norm_clock(row.get("end")),
        _norm_text(row.get("description")),
        str(row.get("process_value") or ""),
    )


def _alarm_action_key(action):
    return (
        "24216",
        "112",
        str(action.get("model_value") or ""),
        str(action.get("machine_value") or ""),
        _norm_clock(action.get("start")),
        _norm_clock(action.get("stop")),
        _norm_text(action.get("description")),
        (
            str(action.get("itag_process_value") or "")
            if action.get("itag_mode") == "I-TAG"
            else ""
        ),
    )

def _token(value, label):
    value = str(value or "").strip()
    if value:
        return value
    return "label:" + _norm_text(label)


def _existing_auto_keys(row):
    topic_tokens = {
        str(row.get("topic_value") or "").strip(),
        "label:" + _norm_text(row.get("topic_label")),
    }
    category_tokens = {
        str(row.get("category_value") or "").strip(),
        "label:" + _norm_text(row.get("category_label")),
    }
    model = str(row.get("model_value") or "")
    start = _norm_clock(row.get("start"))
    end = _norm_clock(row.get("end"))

    keys = set()

    for topic in topic_tokens:
        for category in category_tokens:
            if not topic or not category:
                continue
            keys.add(
                ("production", topic, category, model, start)
            )
            keys.add(
                ("timed", topic, category, start, end)
            )

    return keys


def _auto_action_keys(action):
    topic_tokens = set()
    category_tokens = set()

    topic_value = str(
        action.get("downtime_value") or ""
    ).strip()
    topic_label = _norm_text(
        action.get("downtime_label")
    )
    category_value = str(
        action.get("category_value") or ""
    ).strip()
    category_label = _norm_text(
        action.get("category_label")
    )

    if topic_value:
        topic_tokens.add(topic_value)
    if topic_label:
        topic_tokens.add(
            "label:" + topic_label
        )

    if category_value:
        category_tokens.add(
            category_value
        )
    if category_label:
        category_tokens.add(
            "label:" + category_label
        )

    keys = set()

    for topic in topic_tokens:
        for category in category_tokens:
            if action.get("kind") == "production":
                keys.add(
                    (
                        "production",
                        topic,
                        category,
                        str(
                            action.get(
                                "model_value"
                            )
                            or ""
                        ),
                        _norm_clock(
                            action.get("start")
                        ),
                    )
                )
            else:
                keys.add(
                    (
                        "timed",
                        topic,
                        category,
                        _norm_clock(
                            action.get("start")
                        ),
                        _norm_clock(
                            action.get("end")
                        ),
                    )
                )

    return keys


async def _wait_control(control, progress=None):
    if control is None: return "continue"
    if control.stop_event.is_set():
        if progress: progress("STOP requested - หยุดก่อนรายการถัดไป")
        return "stop"
    paused=False
    while control.pause_event.is_set():
        if control.stop_event.is_set():
            if progress: progress("STOP requested while paused")
            return "stop"
        if not paused and progress:
            progress("PAUSED - รอ Resume/Stop")
            paused=True
        await asyncio.sleep(0.15)
    if paused and progress: progress("RESUMED")
    return "continue"

async def _prepare_auto_register_form(page, action, prefix, progress=None):
    if progress:
        progress(f"{prefix} กด New Time & Event")

    form = await _open_new_event(page)

    if action["kind"] == "production":
        if progress:
            progress(f"{prefix} Downtime = {action['downtime_label']}")
        await _set_select_config(
            form,
            "select.dropdown_topic",
            action.get("downtime_value", ""),
            action.get("downtime_label", "")
        )

        if progress:
            progress(f"{prefix} Category = {action['category_label']}")
        await _set_select_config(
            form,
            "select.dropdown_topic_sub",
            action.get("category_value", ""),
            action.get("category_label", "")
        )

        if progress:
            progress(
                f"{prefix} Model = {action['model_name']} "
                f"[{action['model_value']}]"
            )
        await _set_select(
            form,
            "select.dropdown_model",
            action["model_value"]
        )

        description = str(action.get("description", ""))
        if description:
            await _fill(form, "textarea.txt-comment", description)

        if progress:
            progress(f"{prefix} Start = {action['start']}")
        await _fill(form, ".startCheck input", _fmt(action["start"]))

    elif action["kind"] == "break":
        if progress:
            progress(f"{prefix} Downtime = {action['downtime_label']}")
        await _set_select_config(
            form,
            "select.dropdown_topic",
            action.get("downtime_value", ""),
            action.get("downtime_label", "")
        )

        if progress:
            progress(f"{prefix} Category = {action['category_label']}")
        await _set_select_config(
            form,
            "select.dropdown_topic_sub",
            action.get("category_value", ""),
            action.get("category_label", "")
        )

        description = str(action.get("description", ""))
        if description:
            if progress:
                progress(f"{prefix} Description = {description}")
            await _fill(form, "textarea.txt-comment", description)

        if progress:
            progress(
                f"{prefix} Start = {action['start']} | Stop = {action['end']}"
            )
        await _fill(form, ".startCheck input", _fmt(action["start"]))
        await _fill(form, ".endCheck input", _fmt(action["end"]))

    else:
        raise RuntimeError(f"ไม่รองรับ action type: {action['kind']}")

    return form


async def execute_register_async(
    cdp_url,
    page_index,
    actions,
    dry_run=True,
    progress=None,
    control=None,
    expected_document=None,
):
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")

        pages = browser.contexts[0].pages
        if page_index < 0 or page_index >= len(pages):
            raise RuntimeError("QAC tab ไม่อยู่แล้ว กรุณา Scan ใหม่")

        page = pages[page_index]
        await _assert_document_identity(page, expected_document)
        await page.bring_to_front()

        (
            _document_key,
            _identity,
            existing,
            cache_stats,
        ) = await sync_events_incremental(
            page,
            progress=progress
        )

        existing_keys = set()
        for row in existing:
            existing_keys.update(
                _existing_auto_keys(row)
            )

        if progress:
            progress(
                "Duplicate Interlock: SQLite Cache "
                f"{len(existing)} Result | "
                f"read_new={cache_stats['read_details']}"
            )

        for i, action in enumerate(actions, 1):
            if await _wait_control(control, progress) == "stop":
                break
            candidate_keys = _auto_action_keys(action)
            prefix = f"[{i}/{len(actions)}]"

            if progress:
                progress(
                    f"{prefix} เริ่ม {action['kind']} "
                    f"{action['start']}-{action['end']}"
                    + (" [DRY RUN]" if dry_run else "")
                )

            if existing_keys.intersection(candidate_keys):
                if progress:
                    progress(f"{prefix} DUPLICATE BLOCKED ✓ มีข้อมูลใน QAC แล้ว")
                continue

            if dry_run:
                continue

            async def _prepare_current_auto():
                return await _prepare_auto_register_form(
                    page, action, prefix, progress
                )

            form = await _prepare_with_refresh_restart(
                page,
                _prepare_current_auto,
                prefix,
                progress
            )

            # Capture baseline only after preparation succeeds.  A recovery
            # refresh restarts the current record before this point.
            before_ids = await _result_ids(page)
            before_count = await page.locator(
                ".f1-step[data-result]"
            ).count()

            if progress:
                progress(f"{prefix} กดปุ่มบันทึก")

            await _assert_document_identity(page, expected_document)
            await _save(page, form)

            if progress:
                progress(f"{prefix} รอ Complete...")

            result = await _wait_complete(
                page,
                before_ids,
                before_count
            )

            if progress:
                progress(f"{prefix} COMPLETE ✓ ({result})")

            existing_keys.update(candidate_keys)

            try:
                await cache_event_payload(
                    page,
                    str(result),
                    {
                        "source": "auto-register",
                        "topic_value": action.get(
                            "downtime_value",
                            ""
                        ),
                        "topic_label": action.get(
                            "downtime_label",
                            ""
                        ),
                        "category_value": action.get(
                            "category_value",
                            ""
                        ),
                        "category_label": action.get(
                            "category_label",
                            ""
                        ),
                        "model_value": action.get(
                            "model_value",
                            ""
                        ),
                        "model_label": action.get(
                            "model_name",
                            ""
                        ),
                        "start": action.get(
                            "start",
                            ""
                        ),
                        "end": action.get(
                            "end",
                            ""
                        ),
                        "description": action.get(
                            "description",
                            ""
                        ),
                    }
                )
            except Exception as cache_error:
                if progress:
                    progress(
                        f"{prefix} CACHE WARNING: "
                        f"{cache_error}"
                    )

            await page.wait_for_timeout(250)

        return True


def _parse_qac_time(value: str) -> str:
    """Return the human-visible QAC clock string (12-hour + AM/PM).

    NOTE: the real QAC save JavaScript parses the same textbox with the format
    ``HH:mm A`` even though the datetimepicker displays ``hh:mm A``. On some
    Moment.js builds that mismatch can turn 21:xx into 09:xx during save. The
    runtime writer below therefore verifies the *actual QAC Moment parser* and
    uses a parser-compatible raw value before Save.
    """
    value = str(value).strip()

    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            dt = time.strptime(value, fmt)
            h = dt.tm_hour
            m = dt.tm_min
            suffix = "AM" if h < 12 else "PM"
            hh = h % 12 or 12
            return f"{hh}:{m:02d} {suffix}"
        except ValueError:
            continue

    raise RuntimeError(f"รูปแบบเวลาไม่ถูกต้อง: {value}")


def _clock_parts(value: str) -> tuple[int, int]:
    raw = str(value).strip()
    for fmt in ("%H:%M:%S", "%H:%M"):
        try:
            dt = time.strptime(raw, fmt)
            return dt.tm_hour, dt.tm_min
        except ValueError:
            continue
    raise RuntimeError(f"รูปแบบเวลาไม่ถูกต้อง: {value}")


def _qac_save_clock_candidates(value: str) -> list[str]:
    """Candidate strings tested against QAC's own ``moment(...,'HH:mm A')``.

    The first candidate preserves the operator-facing 12-hour format. The
    second intentionally carries the 24-hour hour together with the meridiem;
    this is required by some real QAC deployments whose save code incorrectly
    uses ``HH`` with ``A``. We never assume which one is correct: the browser's
    own Moment.js parser is queried at runtime and only an exact 24-hour match
    is accepted.
    """
    h, m = _clock_parts(value)
    suffix = "AM" if h < 12 else "PM"
    human_h = h % 12 or 12
    candidates = [f"{human_h:02d}:{m:02d} {suffix}", f"{h:02d}:{m:02d} {suffix}", f"{h:02d}:{m:02d}"]
    out = []
    for item in candidates:
        if item not in out:
            out.append(item)
    return out


async def _qac_moment_parse_clock(loc, raw_value: str) -> str:
    """Ask the real QAC page how its save parser interprets a clock string."""
    try:
        return str(await loc.evaluate(
            """(el, raw) => {
                if (!window.moment) return '';
                const m = window.moment(String(raw || ''), 'HH:mm A');
                if (!m || !m.isValid()) return '';
                return m.format('HH:mm');
            }""",
            raw_value,
        ) or "")
    except Exception:
        return ""


async def _fill_trouble_time(form, selector: str, value: str, progress=None, label: str = "Time"):
    """Fill one QAC Trouble time using QAC's *real* Moment.js behavior.

    1) Drive the visible datetimepicker in its declared ``hh:mm A`` format so
       QAC recalculates Loss Time exactly as an operator action would.
    2) Test candidate raw textbox values against the page's own save parser
       ``moment(value, 'HH:mm A')``.
    3) Leave only a value that the QAC save code itself proves resolves to the
       expected 24-hour hour/minute. If no candidate matches, block Save rather
       than registering a wrong time.
    """
    human_value = _parse_qac_time(value)
    h, m = _clock_parts(value)
    expected = f"{h:02d}:{m:02d}"
    loc = form.locator(selector).first
    await loc.wait_for(state="visible", timeout=STEP_TIMEOUT_MS)

    # First reproduce the normal operator-facing datetimepicker state.
    await loc.fill(human_value)
    await loc.dispatch_event("input")
    await loc.dispatch_event("change")
    try:
        await loc.evaluate(
            """(el) => {
                if (window.jQuery && window.moment) {
                    const $el = window.jQuery(el);
                    const $group = $el.closest('.input-group.date');
                    try {
                        $group.trigger({
                            type: 'dp.change',
                            date: window.moment(el.value, 'hh:mm A')
                        });
                    } catch (e) {}
                }
            }"""
        )
    except Exception:
        pass

    # Now satisfy the parser QAC actually uses inside preConfirm/save.
    chosen = ""
    parsed = ""
    for candidate in _qac_save_clock_candidates(value):
        qac_parsed = await _qac_moment_parse_clock(loc, candidate)
        if qac_parsed == expected:
            chosen = candidate
            parsed = qac_parsed
            break

    if not chosen:
        raise RuntimeError(
            f"QAC time parser ไม่สามารถยืนยันเวลา {value} เป็น {expected} ได้ จึงยกเลิกก่อน Save"
        )

    # IMPORTANT: set the final raw value *after* the dp.change calculation and
    # do not blur it again; some datetimepicker versions would normalize it
    # back to 12-hour text before QAC's buggy HH:mm A save parser reads it.
    await loc.fill(chosen)
    await loc.dispatch_event("input")
    await loc.dispatch_event("change")
    actual = str(await loc.input_value() or "").strip()
    actual_parsed = await _qac_moment_parse_clock(loc, actual)
    if actual_parsed != expected:
        raise RuntimeError(
            f"QAC time verify ไม่ผ่าน: source={value} | input={actual!r} | "
            f"qac_parse={actual_parsed or '-'} | expected={expected}"
        )

    if progress:
        progress(
            f"QAC TIME VERIFIED | {label} source={value} | input={actual} | qac_parse={actual_parsed}"
        )
    await loc.page.wait_for_timeout(80)



async def _enable_and_fill_itag(form, action, progress, prefix):
    """
    Enable I-TAG and fill fields that QAC normally reveals after the checkbox.
    """
    checkbox = form.locator(
        'input[type="checkbox"].i-tag-checked'
    ).first

    await checkbox.wait_for(
        state="attached",
        timeout=STEP_TIMEOUT_MS
    )

    if await checkbox.is_disabled():
        raise RuntimeError(
            "I-TAG checkbox ถูก Disable โดย QAC สำหรับรายการนี้"
        )

    if progress:
        progress(f"{prefix} I-TAG = ON")

    if not await checkbox.is_checked():
        await checkbox.check()
        await checkbox.dispatch_event("change")

    # QAC rejects and unchecks when user has no I-TAG group.
    await form.locator(".i-tag-input").first.wait_for(
        state="visible",
        timeout=STEP_TIMEOUT_MS
    )

    if not await checkbox.is_checked():
        raise RuntimeError(
            "QAC ไม่อนุญาตออก I-TAG สำหรับ User นี้"
        )

    # Keeping place defaults to NG box (007) in QAC. Enforce it only if empty.
    keeping = form.locator(
        "select.dropdown_keeping_place"
    ).first
    if await keeping.count():
        current = await keeping.input_value()
        if not current or current == "0":
            await _set_select(
                form,
                "select.dropdown_keeping_place",
                "007"
            )
        if progress:
            progress(f"{prefix} Keeping Place = NG box")

    # Production Line Found = line of selected QAC document.
    if progress:
        progress(
            f"{prefix} Production Line Found = "
            f"{action['itag_line_name']}"
        )

    line_candidates = form.locator(
        "select.dropdown_i-tag_process"
    )

    line_select = None
    for idx in range(await line_candidates.count()):
        candidate = line_candidates.nth(idx)
        try:
            if await candidate.is_visible():
                line_select = candidate
                break
        except Exception:
            continue

    if line_select is None:
        raise QACPageIncomplete(
            "ไม่พบช่อง Production Line Found ที่กำลังแสดงใน QAC"
        )

    try:
        await line_select.select_option(
            value=str(action["itag_line_value"]),
            timeout=STEP_TIMEOUT_MS
        )
    except Exception as exc:
        raise QACPageIncomplete(
            "QAC โหลด Production Line Found ไม่สมบูรณ์: "
            f"{action['itag_line_name']} [{action['itag_line_value']}]"
        ) from exc
    await line_select.dispatch_event("change")

    # QAC dynamically loads Process Found after Production Line Found changes.
    #
    # IMPORTANT:
    # QAC keeps more than one I-TAG form fragment in DOM. The previous
    # locator searched descendants from a select element and Playwright
    # strict mode found duplicate <option value="303"> nodes.
    #
    # Resolve the ONE visible Process Found <select> first, then use
    # select_option directly. select_option waits for the requested
    # option and avoids the duplicate-option strict-mode problem.
    sub_candidates = form.locator(
        "select.dropdown_i-tag_process_sub"
    )

    sub = None
    for idx in range(await sub_candidates.count()):
        candidate = sub_candidates.nth(idx)
        try:
            if await candidate.is_visible():
                sub = candidate
                break
        except Exception:
            continue

    if sub is None:
        raise QACPageIncomplete(
            "ไม่พบช่อง Process Found ที่กำลังแสดงใน QAC"
        )

    desired_sub = str(action["itag_process_value"])

    try:
        await sub.select_option(
            value=desired_sub,
            timeout=STEP_TIMEOUT_MS
        )
    except Exception as exc:
        available = await sub.locator("option").evaluate_all(
            """els => els.map(x => ({
                value: String(x.value || ''),
                text: String(x.textContent || '').trim()
            }))"""
        )
        raise QACPageIncomplete(
            "QAC โหลด Process Found ไม่สมบูรณ์: "
            f"{action['itag_process_name']} "
            f"[{desired_sub}] | available={available[:12]}"
        ) from exc

    await sub.dispatch_event("change")

    if progress:
        progress(
            f"{prefix} Process Found = "
            f"{action['itag_process_name']}"
        )

    # Shift 1-6 chosen in Alarm Import header.
    shift = form.locator("input.txt-cut-shift").first
    await shift.wait_for(
        state="visible",
        timeout=STEP_TIMEOUT_MS
    )
    await shift.fill(str(action["itag_shift"]))
    await shift.dispatch_event("input")
    await shift.dispatch_event("change")
    await shift.dispatch_event("blur")

    if progress:
        progress(f"{prefix} I-TAG Shift = {action['itag_shift']}")

    # Model selection should have generated Lot No automatically.
    lot = form.locator("input.txt-lot-no").first
    if await lot.count():
        lot_value = (await lot.input_value()).strip()
        if not lot_value:
            raise RuntimeError(
                "QAC ไม่ได้สร้าง I-TAG Lot No จาก Model/Document"
            )
        if progress:
            progress(f"{prefix} I-TAG Lot No = {lot_value}")


async def _prepare_alarm_import_form(page, action, prefix, progress=None):
    if progress:
        progress(f"{prefix} กด New Time & Event")

    form = await _open_new_event(page)

    if progress:
        progress(f"{prefix} Downtime = Trouble")
    await _set_select(form, "select.dropdown_topic", "24216")

    if progress:
        progress(f"{prefix} Category = Machine")
    await _set_select(form, "select.dropdown_topic_sub", "112")

    if progress:
        progress(
            f"{prefix} Model = {action['model_name']} [{action['model_value']}]"
        )
    await _set_select(form, "select.dropdown_model", action["model_value"])

    if progress:
        progress(
            f"{prefix} Machine = {action['machine_name']} [{action['machine_value']}]"
        )
    await _set_select(form, "select.dropdown_machine", action["machine_value"])

    if progress:
        progress(
            f"{prefix} NG Product = {action['ng_name']} [{action['ng_value']}]"
        )
    await _set_select(form, "select.dropdown_ng_type", action["ng_value"])

    ng_qty = int(action.get("ng_qty", 1))
    if ng_qty < 1:
        raise RuntimeError(
            f"{prefix} NG Product Qty ต้องมากกว่า 0 (actual={ng_qty})"
        )

    if progress:
        progress(f"{prefix} NG Product Qty = {ng_qty}")
    await _fill(form, "input.txt-ng-qty", str(ng_qty))

    if action.get("itag_mode") == "I-TAG":
        await _enable_and_fill_itag(form, action, progress, prefix)
    elif progress:
        progress(f"{prefix} I-TAG = Normal (ไม่ออก I-TAG)")

    if progress:
        progress(f"{prefix} Description = {action['description']}")
    await _fill(form, "textarea.txt-comment", action["description"])

    if progress:
        progress(
            f"{prefix} Start = {action['start']} | Stop = {action['stop']}"
        )
    await _fill_trouble_time(form, ".startCheck input", action["start"], progress, f"{prefix} Start")
    await _fill_trouble_time(form, ".endCheck input", action["stop"], progress, f"{prefix} Stop")

    return form


async def execute_alarm_import_async(
    cdp_url: str,
    page_index: int,
    actions: list[dict],
    dry_run: bool = True,
    progress=None,
    control=None,
    duplicate_check: bool = True,
):
    """
    Sequential QAC Trouble import.
    One row must COMPLETE before the next row starts.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")

        pages = browser.contexts[0].pages
        if page_index < 0 or page_index >= len(pages):
            raise RuntimeError("QAC tab ไม่อยู่แล้ว กรุณา Scan ใหม่")

        page = pages[page_index]
        await page.bring_to_front()

        if duplicate_check:
            (
                _document_key,
                _identity,
                existing,
                cache_stats,
            ) = await sync_events_incremental(
                page,
                progress=progress
            )

            existing_keys = {
                _existing_alarm_key(row)
                for row in existing
            }

            if progress:
                progress(
                    "Duplicate Interlock: SQLite Cache "
                    f"{len(existing)} Result | "
                    f"read_new={cache_stats['read_details']}"
                )
        else:
            existing_keys = set()

            if progress:
                progress(
                    "Duplicate Interlock: SKIPPED "
                    "(OCR NG policy)"
                )

        total = len(actions)

        for i, action in enumerate(actions, 1):
            if await _wait_control(control, progress) == "stop":
                break
            prefix = f"[Alarm {i}/{total}]"
            candidate_key = _alarm_action_key(action)

            if progress:
                progress(
                    f"{prefix} {action['machine_code']} | "
                    f"{action['start']} -> {action['stop']} | "
                    f"{action['message']}"
                    + (" [DRY RUN]" if dry_run else "")
                )

            if candidate_key in existing_keys:
                if progress:
                    progress(f"{prefix} DUPLICATE BLOCKED ✓ QAC มีข้อมูลตรงกันแล้ว")
                continue

            if dry_run:
                continue

            async def _prepare_current_alarm():
                return await _prepare_alarm_import_form(
                    page, action, prefix, progress
                )

            form = await _prepare_with_refresh_restart(
                page,
                _prepare_current_alarm,
                prefix,
                progress
            )

            before_ids = await _result_ids(page)
            before_count = await page.locator(
                ".f1-step[data-result]"
            ).count()

            if progress:
                progress(f"{prefix} กด Save / บันทึก")

            # Alarm Import has its own QAC page behavior. Keep the latest
            # import/parser logic, but use the page-specific save flow that
            # was production-proven before the shared Production Check Sheet
            # modal controller was introduced.
            await save_alarm_event(page, form, progress)

            if progress:
                progress(f"{prefix} รอ Complete...")

            result = await _wait_complete(
                page,
                before_ids,
                before_count
            )

            if progress:
                progress(f"{prefix} COMPLETE ✓ ({result})")

            existing_keys.add(candidate_key)

            try:
                await cache_event_payload(
                    page,
                    str(result),
                    {
                        "source": "alarm-import",
                        "topic_value": "24216",
                        "topic_label": "Trouble",
                        "category_value": "112",
                        "category_label": "Machine",
                        "model_value": action.get(
                            "model_value",
                            ""
                        ),
                        "model_label": action.get(
                            "model_name",
                            ""
                        ),
                        "machine_value": action.get(
                            "machine_value",
                            ""
                        ),
                        "machine_label": action.get(
                            "machine_name",
                            ""
                        ),
                        "start": action.get(
                            "start",
                            ""
                        ),
                        "end": action.get(
                            "stop",
                            ""
                        ),
                        "description": action.get(
                            "description",
                            ""
                        ),
                        "process_value": (
                            action.get(
                                "itag_process_value",
                                ""
                            )
                            if action.get(
                                "itag_mode"
                            ) == "I-TAG"
                            else ""
                        ),
                    }
                )
            except Exception as cache_error:
                if progress:
                    progress(
                        f"{prefix} CACHE WARNING: "
                        f"{cache_error}"
                    )

            await page.wait_for_timeout(250)

        return True



async def _find_actual_qty_input(form):
    candidates = [
        "input.txt-actual-qty",
        "input.txt-actual",
        "input[name*='actual' i]",
        "input[id*='actual' i]",
        "input[class*='actual' i]",
    ]

    for selector in candidates:
        loc = form.locator(selector).first
        try:
            if await loc.count() and await loc.is_visible():
                return loc
        except Exception:
            pass

    inputs = form.locator("input")

    for idx in range(await inputs.count()):
        loc = inputs.nth(idx)

        try:
            if not await loc.is_visible():
                continue

            text = await loc.evaluate(
                """el => {
                    const p=el.closest('.form-group,.row,[class*="col-"]');
                    return String(p ? p.innerText : '').toLowerCase();
                }"""
            )

            if (
                "actual (qty)" in text
                or "จำนวนชิ้นงานจริง" in text
            ):
                return loc
        except Exception:
            continue

    raise RuntimeError(
        "ไม่พบช่อง Actual (Qty) ใน Production Output"
    )


async def _click_update(page, form):
    candidates = [
        form.locator(
            "button.btn-update:visible:not([disabled])"
        ).first,
        form.locator(
            "button.btn-process:visible:not([disabled])",
            has_text="Update"
        ).first,
        form.locator(
            "button:visible:not([disabled])",
            has_text="อัพเดท"
        ).first,
    ]

    button = None

    for loc in candidates:
        try:
            if await loc.count():
                button = loc
                break
        except Exception:
            pass

    if button is None:
        raise RuntimeError(
            "ไม่พบปุ่ม Update / อัพเดท"
        )

    await install_native_dialog_guard(page)
    await button.scroll_into_view_if_needed()
    await button.click(timeout=STEP_TIMEOUT_MS)

    # Production Output has a page-specific legacy SweetAlert2 flow.
    # Handle confirmation/busy/success here, then let the caller verify Qty.
    await handle_production_output_commit(page, None)


async def _open_existing_result(page, result_id: str):
    step = page.locator(
        f'.f1-step[data-result="{result_id}"]:visible'
    ).first

    if await step.count() < 1:
        raise RuntimeError(
            f"ไม่พบ Timeline Result ID {result_id}"
        )

    await step.click()

    deadline = time.monotonic() + STEP_TIMEOUT_MS / 1000

    while time.monotonic() < deadline:
        forms = page.locator(".task-downtime:visible")

        if await forms.count():
            form = forms.last
            rid = str(
                await form.get_attribute("data-result-id")
                or ""
            )

            if not rid or rid == str(result_id):
                return form

        await page.wait_for_timeout(100)

    raise RuntimeError(
        f"เปิด Result ID {result_id} แล้ว "
        "แต่ไม่พบฟอร์มที่กำลังแสดง"
    )


def _config_option_match(
    event_value,
    event_label,
    action_value,
    action_label,
):
    action_value = str(
        action_value or ""
    ).strip()

    if (
        action_value
        and str(event_value or "").strip()
        == action_value
    ):
        return True

    action_label_norm = _norm_text(
        action_label
    )

    return bool(
        action_label_norm
        and _norm_text(event_label)
        == action_label_norm
    )


def _production_existing_match(event, action):
    return (
        _config_option_match(
            event.get("topic_value"),
            event.get("topic_label"),
            action.get("downtime_value"),
            action.get("downtime_label"),
        )
        and
        _config_option_match(
            event.get("category_value"),
            event.get("category_label"),
            action.get("category_value"),
            action.get("category_label"),
        )
        and
        str(event.get("model_value") or "")
        == str(action.get("model_value") or "")
        and
        _norm_clock(event.get("start"))
        == _norm_clock(action.get("qac_event_time"))
    )


def _timed_existing_match(event, action):
    if not _config_option_match(
        event.get("topic_value"),
        event.get("topic_label"),
        action.get("downtime_value"),
        action.get("downtime_label"),
    ):
        return False

    if not _config_option_match(
        event.get("category_value"),
        event.get("category_label"),
        action.get("category_value"),
        action.get("category_label"),
    ):
        return False

    if (
        _norm_clock(event.get("start"))
        != _norm_clock(action.get("start"))
        or
        _norm_clock(event.get("end"))
        != _norm_clock(action.get("end"))
        or
        _norm_text(event.get("description"))
        != _norm_text(action.get("description"))
    ):
        return False

    if action.get("model_value"):
        if (
            str(event.get("model_value") or "")
            != str(action.get("model_value") or "")
        ):
            return False

    if (
        action.get("machine_value")
        or action.get("machine_label")
    ):
        if not _config_option_match(
            event.get("machine_value"),
            event.get("machine_label"),
            action.get("machine_value"),
            action.get("machine_label"),
        ):
            return False

    return True


async def _create_timed_record(page, action, progress, prefix):
    before_ids = await _result_ids(page)
    before_count = await page.locator(
        ".f1-step[data-result]"
    ).count()

    if progress:
        progress(f"{prefix} กด New Time & Event")

    form = await _open_new_event(page)

    await _set_select_config(
        form,
        "select.dropdown_topic",
        action.get("downtime_value", ""),
        action.get("downtime_label", "")
    )
    await _set_select_config(
        form,
        "select.dropdown_topic_sub",
        action.get("category_value", ""),
        action.get("category_label", "")
    )

    if action.get("model_value"):
        await _set_select(
            form,
            "select.dropdown_model",
            action["model_value"]
        )

    if action.get("machine_search_text"):
        await _set_select_contains(
            form,
            "select.dropdown_machine",
            action.get("machine_search_text", "")
        )
    elif (
        action.get("machine_value")
        or action.get("machine_label")
    ):
        await _set_select_config(
            form,
            "select.dropdown_machine",
            action.get("machine_value", ""),
            action.get("machine_label", "")
        )

    if action.get("description"):
        await _fill(
            form,
            "textarea.txt-comment",
            action["description"]
        )

    await _fill_trouble_time(
        form,
        ".startCheck input",
        action["start"]
    )
    await _fill_trouble_time(
        form,
        ".endCheck input",
        action["end"]
    )

    # Production Output uses its own Time & Event popup behavior.
    save = form.locator("button.btn-save:visible:not([disabled])").first
    if await save.count() < 1:
        raise RuntimeError("ไม่พบปุ่ม Save / บันทึก ที่พร้อมใช้งานใน Production Output")
    try:
        await save.click(timeout=STEP_TIMEOUT_MS, no_wait_after=True)
        if progress: progress(f"{prefix} SAVE CLICK RETURNED")
    except Exception as exc:
        if not (_is_navigation_context_error(exc) or _is_transient_dom_click_error(exc)):
            raise
        if progress: progress(f"{prefix} SAVE CLICK UNCERTAIN | {type(exc).__name__}: {str(exc)[:200]} | verify Result ID before retry")
    try:
        await handle_production_output_commit(page, progress)
    except Exception as exc:
        if progress: progress(f"{prefix} POPUP ACK UNCERTAIN | {type(exc).__name__}: {str(exc)[:200]} | verify Result ID")
        if 'QAC ERROR:' in str(exc).upper() or 'QAC WARNING:' in str(exc).upper():
            raise

    result = await _wait_complete(
        page,
        before_ids,
        before_count
    )

    if progress:
        progress(f"{prefix} COMPLETE ✓ ({result})")

    return str(result)


async def _read_form_event(form):
    async def selected_text(selector):
        loc = form.locator(selector).first
        try:
            if await loc.count():
                return (
                    await loc.locator(
                        "option:checked"
                    ).first.inner_text()
                ).strip()
        except Exception:
            pass
        return ""

    async def value(selector):
        loc = form.locator(selector).first
        try:
            if await loc.count():
                return (
                    await loc.input_value()
                ).strip()
        except Exception:
            pass
        return ""

    actual_qty = ""

    try:
        qty = await _find_actual_qty_input(form)
        actual_qty = (
            await qty.input_value()
        ).strip()
    except Exception:
        pass

    return {
        "result_id": str(
            await form.get_attribute(
                "data-result-id"
            )
            or ""
        ),
        "topic_value": await value(
            "select.dropdown_topic"
        ),
        "topic_label": await selected_text(
            "select.dropdown_topic"
        ),
        "category_value": await value(
            "select.dropdown_topic_sub"
        ),
        "category_label": await selected_text(
            "select.dropdown_topic_sub"
        ),
        "model_value": await value(
            "select.dropdown_model"
        ),
        "model_label": await selected_text(
            "select.dropdown_model"
        ),
        "machine_value": await value(
            "select.dropdown_machine"
        ),
        "machine_label": await selected_text(
            "select.dropdown_machine"
        ),
        "start": await value(
            ".startCheck input"
        ),
        "end": await value(
            ".endCheck input"
        ),
        "description": await value(
            "textarea.txt-comment"
        ),
        "actual_qty": actual_qty,
    }


async def _scan_timeline_event_details(
    page,
    progress=None
):
    ids = await page.locator(
        ".f1-step[data-result]"
    ).evaluate_all(
        """els => [...new Set(
            els.map(
                e => String(
                    e.getAttribute('data-result')
                    || ''
                ).trim()
            ).filter(
                v => v && v !== '0'
            )
        )]"""
    )

    out = []

    for index, result_id in enumerate(
        ids,
        1
    ):
        try:
            if progress:
                progress(
                    f"Pre-flight QAC detail "
                    f"{index}/{len(ids)}"
                )

            form = await _open_existing_result(
                page,
                result_id
            )
            row = await _read_form_event(
                form
            )

            if not row.get("result_id"):
                row["result_id"] = str(
                    result_id
                )

            out.append(row)
        except Exception:
            continue

    return out


def _merge_event_details(primary, fallback):
    by_id = {
        str(row.get("result_id", "")): row
        for row in primary
        if str(row.get("result_id", ""))
    }

    for row in fallback:
        rid = str(
            row.get("result_id", "")
        )

        if not rid:
            continue

        old = by_id.get(rid)

        if old is None:
            by_id[rid] = row
            continue

        # Fill missing fields from clicked timeline form.
        for key, value in row.items():
            if (
                not str(old.get(key, "") or "").strip()
                and str(value or "").strip()
            ):
                old[key] = value

    return list(by_id.values())


async def execute_production_output_async(
    cdp_url: str,
    page_index: int,
    actions: list[dict],
    dry_run: bool = True,
    progress=None,
    control=None,
):
    """
    Create Setup/Stop Line only if missing, and UPDATE existing
    Production Output Actual Qty. Missing hourly Production Output points
    block the batch before any QAC changes.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)

        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")

        pages = browser.contexts[0].pages

        if page_index < 0 or page_index >= len(pages):
            raise RuntimeError(
                "QAC tab ไม่อยู่แล้ว กรุณา Scan ใหม่"
            )

        page = pages[page_index]
        await page.bring_to_front()

        (
            _document_key,
            _identity,
            existing,
            cache_stats,
        ) = await sync_events_incremental(
            page,
            progress=progress
        )

        if progress:
            progress(
                "Production QAC Cache "
                f"{len(existing)} Result | "
                f"read_new={cache_stats['read_details']}"
            )

        production_actions = [
            a for a in actions
            if a.get("kind") == "production_update"
        ]

        missing = []

        for action in production_actions:
            found = next(
                (
                    e for e in existing
                    if _production_existing_match(e, action)
                ),
                None
            )

            if not found:
                missing.append(action["qac_event_time"])
                continue

            action["_result_id"] = str(
                found.get("result_id", "")
            )

            raw_qty = str(
                found.get("actual_qty", "")
                or ""
            ).strip()

            try:
                action["_existing_qty"] = int(float(raw_qty))
            except Exception:
                action["_existing_qty"] = None

        if missing:
            raise RuntimeError(
                "Production Output เดิมไม่ครบ "
                "จึงไม่เริ่ม Update เพื่อป้องกันข้อมูลบางส่วน "
                f"| Missing={missing}"
            )

        total = len(actions)

        for index, action in enumerate(actions, 1):
            if await _wait_control(control, progress) == "stop":
                break

            prefix = f"[Production {index}/{total}]"
            kind = action.get("kind")

            if kind in ("setup", "stop_line"):
                found = next(
                    (
                        e for e in existing
                        if _timed_existing_match(e, action)
                    ),
                    None
                )

                if found:
                    if progress:
                        progress(
                            f"{prefix} EXISTS ✓ {kind} skip"
                        )
                    continue

                if dry_run:
                    if progress:
                        progress(
                            f"{prefix} NEW {kind} "
                            f"{action['start']} -> {action['end']} "
                            "[DRY RUN]"
                        )
                    continue

                result_id = await _create_timed_record(
                    page,
                    action,
                    progress,
                    prefix
                )

                try:
                    detail = await cache_event_payload(
                        page,
                        result_id,
                        {
                            "source": "production-import",
                            "topic_value": action.get(
                                "downtime_value",
                                ""
                            ),
                            "topic_label": action.get(
                                "downtime_label",
                                ""
                            ),
                            "category_value": action.get(
                                "category_value",
                                ""
                            ),
                            "category_label": action.get(
                                "category_label",
                                ""
                            ),
                            "model_value": action.get(
                                "model_value",
                                ""
                            ),
                            "model_label": action.get(
                                "model_name",
                                ""
                            ),
                            "machine_value": action.get(
                                "machine_value",
                                ""
                            ),
                            "machine_label": action.get(
                                "machine_label",
                                ""
                            ),
                            "start": action.get(
                                "start",
                                ""
                            ),
                            "end": action.get(
                                "end",
                                ""
                            ),
                            "description": action.get(
                                "description",
                                ""
                            ),
                        }
                    )
                    if detail:
                        existing.append(
                            detail
                        )
                except Exception as cache_error:
                    if progress:
                        progress(
                            f"{prefix} CACHE WARNING: "
                            f"{cache_error}"
                        )

                continue

            if kind == "production_update":
                target_qty = int(action.get("qty", 0))
                existing_qty = action.get("_existing_qty")

                if (
                    existing_qty is not None
                    and existing_qty == target_qty
                ):
                    if progress:
                        progress(
                            f"{prefix} COMPLETE ✓ "
                            f"{action['qac_event_time']} "
                            f"Qty={target_qty} already"
                        )
                    continue

                if dry_run:
                    if progress:
                        progress(
                            f"{prefix} UPDATE "
                            f"{action['qac_event_time']} "
                            f"{existing_qty} -> {target_qty} "
                            "[DRY RUN]"
                        )
                    continue

                result_id = action.get("_result_id", "")

                if not result_id:
                    raise RuntimeError(
                        f"{prefix} ไม่มี Result ID"
                    )

                form = await _open_existing_result(
                    page,
                    result_id
                )

                qty_input = await _find_actual_qty_input(form)

                await qty_input.fill(str(target_qty))
                await qty_input.dispatch_event("input")
                await qty_input.dispatch_event("change")
                await qty_input.dispatch_event("blur")

                if progress:
                    progress(
                        f"{prefix} Actual Qty "
                        f"{action['qac_event_time']} = "
                        f"{target_qty}"
                    )

                await _click_update(page, form)
                await page.wait_for_timeout(250)

                verified = None

                try:
                    verified = await cache_saved_result(
                        page,
                        str(result_id)
                    )
                except Exception as cache_error:
                    if progress:
                        progress(
                            f"{prefix} CACHE WARNING: "
                            f"{cache_error}"
                        )

                if verified is not None:
                    raw = str(
                        verified.get("actual_qty", "")
                        or ""
                    ).strip()

                    try:
                        current = int(float(raw))
                    except Exception:
                        current = None

                    if (
                        current is not None
                        and current != target_qty
                    ):
                        raise RuntimeError(
                            f"{prefix} QAC Qty verify ไม่ตรง "
                            f"expected={target_qty}, actual={current}"
                        )

                if progress:
                    progress(
                        f"{prefix} COMPLETE ✓ "
                        f"{action['qac_event_time']} "
                        f"Qty={target_qty}"
                    )
                continue

            raise RuntimeError(
                f"ไม่รองรับ Production action: {kind}"
            )

        return True


async def execute_manual_qac_events_async(
    cdp_url: str,
    page_index: int,
    actions: list[dict],
    progress=None,
):
    """Create validated manual hourly events in QAC, one event at a time.

    The action values must come from the live QAC HTML option masters.  Each
    record is created through the same New Time & Event form and therefore
    follows QAC's real DownTime -> Category -> Model/Machine -> Time -> Save
    dependency chain instead of inventing local-only values.
    """
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts:
            raise RuntimeError("ไม่พบ Browser Context")
        pages = browser.contexts[0].pages
        if page_index < 0 or page_index >= len(pages):
            raise RuntimeError("QAC tab ไม่อยู่แล้ว กรุณา Scan ใหม่")

        page = pages[page_index]
        await page.bring_to_front()

        (_document_key, _identity, existing, _stats) = await sync_events_incremental(
            page, progress=progress
        )

        results = []
        total = len(actions)
        for index, action in enumerate(actions, 1):
            prefix = f"[Manual Event {index}/{total}]"

            found = next(
                (e for e in existing if _timed_existing_match(e, action)),
                None,
            )
            if found:
                if progress:
                    progress(
                        f"{prefix} EXISTS ✓ "
                        f"{action.get('downtime_label','')} / "
                        f"{action.get('category_label','')} "
                        f"{action.get('start','')}-{action.get('end','')}"
                    )
                results.append(str(found.get("result_id") or ""))
                continue

            if progress:
                progress(
                    f"{prefix} DownTime={action.get('downtime_label','')} -> "
                    f"Category={action.get('category_label','')} -> "
                    f"Machine={action.get('machine_label','-')} -> "
                    f"Time={action.get('start','')}-{action.get('end','')}"
                )

            result_id = await _create_timed_record(page, action, progress, prefix)
            results.append(result_id)

            try:
                detail = await cache_event_payload(
                    page,
                    result_id,
                    {
                        "source": "hourly-manual-event",
                        "topic_value": action.get("downtime_value", ""),
                        "topic_label": action.get("downtime_label", ""),
                        "category_value": action.get("category_value", ""),
                        "category_label": action.get("category_label", ""),
                        "model_value": action.get("model_value", ""),
                        "model_label": action.get("model_name", ""),
                        "machine_value": action.get("machine_value", ""),
                        "machine_label": action.get("machine_label", ""),
                        "start": action.get("start", ""),
                        "end": action.get("end", ""),
                        "description": action.get("description", ""),
                    },
                )
                if detail:
                    existing.append(detail)
            except Exception:
                pass

        return results

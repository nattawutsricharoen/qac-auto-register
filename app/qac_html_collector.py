from __future__ import annotations

import asyncio
import csv
import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable, Iterable

from .qac_interaction import interaction_checkpoint, install_native_dialog_guard


@dataclass
class _Node:
    tag: str
    attrs: dict[str, str]
    parent: "_Node | None" = None
    children: list["_Node"] = field(default_factory=list)
    chunks: list[str] = field(default_factory=list)

    def text(self) -> str:
        parts = list(self.chunks)
        for child in self.children:
            parts.append(child.text())
        return " ".join(" ".join(parts).replace("\xa0", " ").split())

    def has_class(self, value: str) -> bool:
        return value in self.attrs.get("class", "").split()

    def walk(self) -> Iterable["_Node"]:
        yield self
        for child in self.children:
            yield from child.walk()


class _TreeParser(HTMLParser):
    _void = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = _Node(tag.lower(), {str(k): str(v or "") for k, v in attrs}, self.stack[-1])
        self.stack[-1].children.append(node)
        if tag.lower() not in self._void:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self._void:
            self.stack.pop()

    def handle_endtag(self, tag):
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                break

    def handle_data(self, data):
        if data and data.strip():
            self.stack[-1].chunks.append(data)


def _first_descendant(node: _Node, class_name: str) -> _Node | None:
    return next((item for item in node.walk() if item.has_class(class_name)), None)


def _input_type(step: _Node, fieldset: _Node | None) -> str:
    value = (fieldset.attrs.get("data-input-format") if fieldset else "") or step.attrs.get("data-input", "")
    classes = (fieldset.attrs.get("class", "") if fieldset else "")
    if "task-okng" in classes or value == "4":
        return "OK_NG"
    if value == "1":
        return "NUMBER"
    if value == "2":
        return "TEXT"
    return f"INPUT_{value}" if value else "UNKNOWN"


def _document_kind(document_name: str, category: str = "") -> str:
    text = f"{document_name} {category}".casefold()
    if "initial-final" in text or "initial / final" in text or "initial final" in text:
        return "INITIAL_FINAL_SAMPLE"
    if "daily" in text or "check sheet" in text or "condition check" in text:
        return "DAILY_CHECK_SHEET"
    return "OTHER"


def _row_empty(row: _Node) -> bool:
    raw = row.attrs.get("data-empty")
    if raw:
        return raw.strip().casefold() == "true"
    for node in row.walk():
        raw = node.attrs.get("data-empty")
        if raw:
            return raw.strip().casefold() == "true"
    return False


def _row_value(row: _Node) -> str:
    for node in row.walk():
        if node.tag in {"input", "textarea", "select"}:
            value = node.attrs.get("value", "")
            if str(value).strip():
                return str(value).strip()
    text = row.text()
    text = re.sub(r"#\s*\d+", " ", text)
    text = re.sub(r"No Result\s*/.*", " ", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _extract_results(fieldset: _Node | None) -> list[dict]:
    if fieldset is None:
        return []
    results = []
    for row in fieldset.walk():
        if row.tag != "tr" or not row.attrs.get("data-result-no"):
            continue
        slot = row.attrs.get("data-result-no", "").strip()
        empty = _row_empty(row)
        data_type = row.attrs.get("data-type", "").strip()
        value = "" if empty else _row_value(row)
        if not value and data_type in {"0", "1"}:
            value = "OK" if data_type == "1" else "NG"
        if empty and not value:
            continue
        results.append({
            "slot": int(slot) if slot.isdigit() else slot,
            "empty": empty,
            "value": value,
            "result_type": data_type,
        })
    return results


def parse_qac_html(html_text: str, source_html: str = "") -> dict:
    """Convert one saved QAC Measure page into a stable, portable schema.

    data-item is retained for diagnosis only. Runtime mapping must use the
    document identity plus section/label because QAC IDs can change when a
    document is recreated.
    """
    parser = _TreeParser()
    parser.feed(str(html_text or ""))
    nodes = list(parser.root.walk())

    def metadata(label: str) -> str:
        wanted = label.strip().casefold()
        for node in nodes:
            if node.tag not in {"h5", "label"} or node.text().strip().casefold() != wanted:
                continue
            if node.parent:
                siblings = node.parent.children
                try:
                    pos = siblings.index(node)
                    for sibling in siblings[pos + 1:]:
                        if sibling.tag in {"h1", "h2", "h3", "h4", "p", "span"} and sibling.text():
                            return sibling.text()
                except ValueError:
                    pass
        return ""

    fieldsets = {
        node.attrs.get("data-item", ""): node
        for node in nodes
        if node.has_class("fieldset") and node.attrs.get("data-item")
    }
    fields = []
    for step in nodes:
        if not step.has_class("f1-step") or not step.attrs.get("data-item"):
            continue
        icon = _first_descendant(step, "f1-step-icon")
        body = _first_descendant(step, "f1-step-p")
        item_id = step.attrs.get("data-item", "")
        form = fieldsets.get(item_id)
        slot_numbers = []
        if form:
            for node in form.walk():
                raw = node.attrs.get("data-result-no", "")
                if raw.isdigit():
                    slot_numbers.append(int(raw))
        frequency_raw = (form.attrs.get("data-frequency") if form else "") or step.attrs.get("data-frequency", "")
        frequency = int(frequency_raw) if str(frequency_raw).isdigit() else (max(slot_numbers) if slot_numbers else 0)
        results = _extract_results(form)
        latest_value = ""
        if results:
            latest = sorted(results, key=lambda item: int(item.get("slot") or 0))[-1]
            latest_value = str(latest.get("value") or "")
        fields.append({
            "section": icon.text() if icon else "",
            "label": body.text() if body else "",
            "input_type": _input_type(step, form),
            "required": ((form.attrs.get("data-required") if form else "") or step.attrs.get("data-required", "")) == "1",
            "frequency": frequency,
            "result_count": len(results),
            "latest_value": latest_value,
            "latest_results": results,
            "data_item": item_id,
            "data_type": step.attrs.get("data-type", ""),
            "data_judge": step.attrs.get("data-judge", ""),
            "source_html": source_html,
        })

    line = metadata("Line :") or metadata("Line:")
    document_name = metadata("Document name:")
    category = metadata("Category :") or metadata("Category:")
    model_rule = "ALL_MODEL" if "all model" in document_name.casefold() else "DYNAMIC"
    return {
        "schema_version": 1,
        "captured_at": datetime.now().isoformat(timespec="seconds"),
        "production_date": metadata("Production date:"),
        "line": line,
        "line_rule": "DYNAMIC",
        "model_rule": model_rule,
        "document_no": metadata("Document No."),
        "document_name": document_name,
        "document_kind": _document_kind(document_name, category),
        "category": category,
        "field_count": len(fields),
        "maximum_slot": max((field["frequency"] for field in fields), default=0),
        "fields": fields,
        "source_html": source_html,
    }


def _safe_name(value: str, fallback: str = "document") -> str:
    value = re.sub(r"[<>:\"/\\|?*\x00-\x1f]+", "_", str(value or ""))
    value = re.sub(r"\s+", "_", value).strip(" ._")
    return value[:150] or fallback


FIELD_MAPPING_COLUMNS = [
    "document_no", "document_name", "document_kind", "category", "line_rule", "model_rule",
    "section", "label", "input_type", "required", "frequency", "result_count", "latest_value", "data_item",
    "data_type", "data_judge", "source_html",
]


def _write_field_mapping_csv(path: Path, schemas: list[dict]) -> None:
    """Write heterogeneous field schemas using a stable, complete CSV shape."""
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=FIELD_MAPPING_COLUMNS)
        writer.writeheader()
        for schema in schemas:
            for field in schema.get("fields", []):
                row = {}
                for key in FIELD_MAPPING_COLUMNS:
                    row[key] = field.get(key, schema.get(key, ""))
                writer.writerow(row)


def _norm(value: str) -> str:
    return " ".join(str(value or "").replace("\xa0", " ").split()).casefold()


async def _wait_control(control) -> None:
    if control is None:
        return
    while control.pause_event.is_set() and not control.stop_event.is_set():
        await asyncio.sleep(0.15)
    if control.stop_event.is_set():
        raise InterruptedError("ผู้ใช้สั่งหยุด HTML Collector")


def _parse_monitor_date_text(value: str):
    """Parse QAC's visible `30 Sep 2026` monitor value into a date."""
    text = " ".join(str(value or "").replace("\xa0", " ").split())
    if not text:
        return None
    for fmt in ("%d %b %Y", "%d %B %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            pass
    return None


async def _visible_monitor_scope(page):
    """Return the row that owns the calendar icon the operator can actually see."""
    icon = page.locator("i.calendar-monitor:visible").first
    # A previous interrupted Sample Register may leave its QAC session on
    # measure.html. The icon exists only on the Production Check Sheet, so
    # waiting for :visible there hides the real state and costs 30 seconds.
    if await page.locator("i.calendar-monitor:visible").count() == 0:
        current_url = str(getattr(page, "url", "") or "")
        measure_panels = await page.locator(".fieldset[data-item]:visible").count()
        list_rows = await page.locator("tr[data-task]:visible").count()
        if measure_panels and "measure.html" in current_url.casefold():
            raise RuntimeError(
                "QAC อยู่หน้า Measure จากการทำงานก่อนหน้า ไม่ใช่ Production Check Sheet; "
                "กรุณากลับหน้า Check Sheet ใน QAC Session ของ Sample แล้วกด Prepare ใหม่ "
                f"(url={current_url})"
            )
        raise RuntimeError(
            "ไม่พบ Calendar ที่มองเห็นบน Production Check Sheet; "
            "ตรวจสอบว่า QAC Session ของ Sample เปิดหน้ารายการงานอยู่และ Login ยังไม่หมดอายุ "
            f"(url={current_url}; visible_task_rows={list_rows}; measure_panels={measure_panels})"
        )
    await icon.wait_for(state="visible", timeout=3000)
    # QAC keeps calendar/date controls in the same visible row. Scoping every
    # action to this row prevents clicks on hidden/cloned datetimepickers.
    return icon.locator(
        "xpath=ancestor::div[contains(concat(' ', normalize-space(@class), ' '), ' row ')][1]"
    )


async def _read_visible_monitor_date(page):
    try:
        scope = await _visible_monitor_scope(page)
        loc = scope.locator(".date-monitor:visible").first
        if await loc.count() == 0:
            return None
        return _parse_monitor_date_text(await loc.inner_text())
    except Exception:
        return None


async def _wait_visible_monitor_date(page, target_date, timeout_ms: int = 90000):
    """Wait for QAC's *visible DOM monitor* to acknowledge navigation.

    Playwright's click acknowledgement is not QAC's date acknowledgement. A
    busy QAC may dispatch the calendar change after several seconds. The
    timeout is a failure boundary, never a success condition; no repeated
    clicks or inferred dates are permitted.
    """
    last_seen = None
    deadline = asyncio.get_running_loop().time() + max(1.0, timeout_ms / 1000)
    while asyncio.get_running_loop().time() < deadline:
        last_seen = await _read_visible_monitor_date(page)
        if last_seen == target_date:
            return last_seen
        # Read DOM again rather than sleeping for an assumed server response.
        # Playwright's locator wait is driven by browser DOM mutation/polling.
        remaining = max(1, int((deadline - asyncio.get_running_loop().time()) * 1000))
        if remaining <= 1:
            break
        try:
            await page.wait_for_function(
                """expected => {
                    const icons = [...document.querySelectorAll('i.calendar-monitor')];
                    const visible = el => !!el && el.getClientRects().length > 0 &&
                        getComputedStyle(el).display !== 'none' &&
                        getComputedStyle(el).visibility !== 'hidden';
                    const icon = icons.find(visible);
                    const row = icon?.closest('div.row');
                    const dateNode = row && [...row.querySelectorAll('.date-monitor')].find(visible);
                    if (!dateNode) return false;
                    const actual = (dateNode.textContent || '').replace(/\\s+/g, ' ').trim();
                    return actual === expected;
                }""",
                target_date.strftime('%d %b %Y'),
                timeout=min(remaining, 2000),
                polling='raf',
            )
        except Exception:
            # Monitor text may have locale/format differences: the Python date
            # parser above remains the authoritative check.
            pass
    actual = last_seen.isoformat() if last_seen else "unknown"
    raise RuntimeError(
        f"QAC ไม่ยืนยันวันที่บนหน้าจอเป็น {target_date.isoformat()} "
        f"(date-monitor={actual}; waited_for_DOM={timeout_ms}ms; ไม่คลิกซ้ำ)"
    )


async def _calendar_picker_is_open(page) -> bool:
    """Return True only for the calendar owned by the visible QAC monitor."""
    try:
        scope = await _visible_monitor_scope(page)
        return await scope.locator('.calendar-picker:visible').count() > 0
    except Exception:
        return False


async def _close_calendar_popup(page, log: Callable[[str], None], production_date: str) -> None:
    """Close only the operator-visible calendar after QAC accepted the date."""
    scope = await _visible_monitor_scope(page)
    for _ in range(8):
        if await scope.locator('.calendar-picker:visible').count() == 0:
            log(f"CALENDAR CLOSED | target={production_date}")
            return
        await page.wait_for_timeout(125)

    calendar = scope.locator('i.calendar-monitor:visible').first
    if await calendar.count() > 0:
        log(f"CALENDAR STILL OPEN | target={production_date} | closing with visible calendar control")
        await calendar.click(timeout=10000)
        for _ in range(8):
            if await scope.locator('.calendar-picker:visible').count() == 0:
                log(f"CALENDAR CLOSED | target={production_date} | by calendar control")
                return
            await page.wait_for_timeout(125)

    if await scope.locator('.calendar-picker:visible').count() > 0:
        log(f"CALENDAR STILL OPEN | target={production_date} | closing with Escape")
        await page.keyboard.press('Escape')
        for _ in range(8):
            if await scope.locator('.calendar-picker:visible').count() == 0:
                log(f"CALENDAR CLOSED | target={production_date} | by Escape")
                return
            await page.wait_for_timeout(125)

    if await scope.locator('.calendar-picker:visible').count() > 0:
        raise RuntimeError(
            f"Calendar popup ของ {production_date} ยังเปิดอยู่หลัง QAC ยืนยันวันที่แล้ว"
        )


async def _set_date(page, production_date: str, log: Callable[[str], None]) -> None:
    """Navigate the real Production Check Sheet calendar like an operator.

    QAC process 25 owns the date state. Its left/right arrows update
    `.date-monitor`, display the Loading SweetAlert and call getTaskList().
    Its datetimepicker does the same only when `dp.change` fires. Therefore a
    click is never considered successful until the visible `.date-monitor`
    changes to the requested date.
    """
    target = datetime.strptime(production_date, "%Y-%m-%d").date()
    await install_native_dialog_guard(page, log)
    await interaction_checkpoint(page, log, name=f"before date {production_date}", wait_ms=200)

    scope = await _visible_monitor_scope(page)
    current = await _read_visible_monitor_date(page)

    # Human behaviour: if the requested day is already on screen, do not open
    # and close the calendar just to re-select the same date.
    if current == target:
        log(f"DATE ALREADY ACTIVE | {production_date} | monitor verified")
        return

    # The scan policy is D then D-1. QAC has a dedicated previous-day control
    # whose own click handler changes date-monitor + shows loading + getTaskList.
    # Prefer that real UI path over reopening the datetimepicker.
    if current is not None and target == current - timedelta(days=1):
        left = scope.locator("i.left-monitor:visible").first
        await left.wait_for(state="visible", timeout=10000)
        log(f"DATE NAVIGATE LEFT | from={current.isoformat()} | target={production_date}")
        await left.click(timeout=10000)
        await _wait_visible_monitor_date(page, target, timeout_ms=90000)
        log(f"DATE MONITOR VERIFIED | {production_date} | via left-monitor")
        await interaction_checkpoint(page, log, name=f"after left date {production_date}", wait_ms=350)
        return

    if current is not None and target == current + timedelta(days=1):
        right = scope.locator("i.right-monitor:visible").first
        await right.wait_for(state="visible", timeout=10000)
        log(f"DATE NAVIGATE RIGHT | from={current.isoformat()} | target={production_date}")
        await right.click(timeout=10000)
        await _wait_visible_monitor_date(page, target, timeout_ms=90000)
        log(f"DATE MONITOR VERIFIED | {production_date} | via right-monitor")
        await interaction_checkpoint(page, log, name=f"after right date {production_date}", wait_ms=350)
        return

    # Non-adjacent date: use the visible datetimepicker owned by this monitor.
    picker = scope.locator('.calendar-picker:visible')
    if await picker.count() == 0:
        calendar = scope.locator("i.calendar-monitor:visible").first
        log(f"CALENDAR CLICK | target={production_date}")
        await calendar.click(timeout=10000)
        for _ in range(15):
            if await scope.locator('.calendar-picker:visible').count() > 0:
                break
            await page.wait_for_timeout(100)
        if await scope.locator('.calendar-picker:visible').count() == 0:
            raise RuntimeError(f"กด Calendar แล้ว แต่ปฏิทินที่มองเห็นไม่เปิดสำหรับ {production_date}")
    else:
        log(f"CALENDAR ALREADY OPEN | target={production_date} | reuse operator-visible popup")

    await interaction_checkpoint(page, log, name=f"calendar open {production_date}", wait_ms=200)
    day_value = target.strftime("%m/%d/%Y")
    visible_day = scope.locator(
        f'.calendar-picker:visible td[data-action="selectDay"][data-day="{day_value}"]:visible'
    ).first
    if await visible_day.count() == 0:
        raise RuntimeError(
            f"ไม่พบวันที่ {production_date} ใน Calendar ที่อยู่กับ date-monitor ที่ผู้ใช้มองเห็น"
        )

    await visible_day.click(timeout=10000)
    log(f"DATE CLICKED | {production_date} | waiting QAC dp.change acknowledgement")

    # Critical acknowledgement: QAC's dp.change handler updates date-monitor
    # before calling getTaskList(). Without this, the click did not reach the
    # active datetimepicker even if Playwright reported click success.
    await _wait_visible_monitor_date(page, target, timeout_ms=90000)
    log(f"DATE MONITOR VERIFIED | {production_date} | dp.change accepted")

    await interaction_checkpoint(page, log, name=f"after date select {production_date}", wait_ms=350)
    await _close_calendar_popup(page, log, production_date)


async def _wait_qac_complete(
    page,
    log: Callable[[str], None],
    state_name: str,
    ready_selector: str | None = None,
    timeout_seconds: int = 90,
) -> None:
    """Wait for browser COMPLETE, QAC AJAX complete, and destination DOM."""
    log(f"WAIT COMPLETE | {state_name}")
    await install_native_dialog_guard(page, log)
    await interaction_checkpoint(page, log, name=f"before wait {state_name}", wait_ms=250)
    try:
        await page.wait_for_function(
            "document.readyState === 'complete'",
            timeout=timeout_seconds * 1000,
        )
        await page.wait_for_function(
            "!window.jQuery || window.jQuery.active === 0",
            timeout=timeout_seconds * 1000,
        )
        if ready_selector:
            await page.locator(ready_selector).first.wait_for(
                state="attached", timeout=timeout_seconds * 1000
            )
        # One quiet interval prevents a late QAC AJAX request from starting
        # immediately after the first jQuery.active==0 observation.
        await page.wait_for_timeout(500)
        await page.wait_for_function(
            "document.readyState === 'complete' && "
            "(!window.jQuery || window.jQuery.active === 0)",
            timeout=timeout_seconds * 1000,
        )
    except Exception as exc:
        raise RuntimeError(
            f"QAC ไม่ตอบกลับ Complete ที่ขั้นตอน {state_name} "
            f"ภายใน {timeout_seconds} วินาที"
        ) from exc
    await interaction_checkpoint(page, log, name=f"complete {state_name}", wait_ms=350)
    log(f"COMPLETE | {state_name}")


async def _return_to_check_sheet(page, log: Callable[[str], None], task_id: str) -> None:
    """Return from Measure without trusting QAC's missing DOMContentLoaded event."""
    log(f"BACK START | task={task_id}")
    # Reference 'View' is a QAC modal, not necessarily a browser navigation.
    # Close its visible task-scoped Close button before considering go_back().
    close_buttons = page.locator(f'button.btn-close[data-task="{task_id}"]:visible')
    if await close_buttons.count() == 1:
        log(f'QAC TASK MODAL CLOSE | task={task_id}')
        await close_buttons.first.click(timeout=12000)
        await interaction_checkpoint(page, log, name=f'after Close task={task_id}', wait_ms=500)
        if await page.locator('i.calendar-monitor:visible').count() and not await page.locator('.fieldset[data-item]:visible').count():
            log(f'BACK READY | task={task_id} | via QAC Close')
            return
    # The QAC Measure action may already have restored the list. Never make
    # another history traversal when the check-sheet is already visible.
    try:
        on_list = await page.locator('i.calendar-monitor:visible').count() > 0
        on_measure = await page.locator('.fieldset[data-item]:visible').count() > 0
        if on_list and not on_measure:
            log(f"BACK SKIP | task={task_id} | Check Sheet already visible | url={page.url}")
            return
        if await page.locator('input.form-control[placeholder="username"]:visible').count():
            raise RuntimeError('QAC LOGIN DETECTED | stop back-navigation, manual login required')
        log(f"BACK NAVIGATION | task={task_id} | source={page.url} | measure={on_measure}")
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(f'Cannot verify QAC page before Back: {exc}') from exc
    try:
        # QAC can reach master.html without emitting the lifecycle event that a
        # normal Playwright go_back wait expects.
        await page.go_back(wait_until="commit", timeout=15000)
    except Exception as exc:
        url = str(getattr(page, "url", "") or "")
        calendar_count = await page.locator("i.calendar-monitor").count()
        if "master.html" not in url.casefold() and calendar_count == 0:
            raise RuntimeError(
                f"ย้อนกลับ Production Check Sheet ไม่สำเร็จ: {exc}"
            ) from exc
        log("BACK NAVIGATION ACK | master page ตอบกลับแล้ว ตรวจ DOM ต่อ")

    if await page.locator('input.form-control[placeholder="username"]:visible').count():
        raise RuntimeError('QAC LOGIN DETECTED AFTER BACK | do not continue navigation')
    await page.locator("i.calendar-monitor:visible").first.wait_for(
        state="visible", timeout=90000
    )
    await _wait_qac_complete(
        page,
        log,
        "Back to Production Check Sheet",
        ready_selector="i.calendar-monitor:visible",
    )
    log(f"BACK READY | task={task_id}")


async def _click_measure_action(page, task_id: str, log: Callable[[str], None]) -> None:
    """Click QAC Measure despite duplicated hidden action-menu clones."""
    selector = f'a.menu-measure-task[data-task="{task_id}"]'
    locator = page.locator(selector)
    try:
        await locator.first.wait_for(state="attached", timeout=15000)
    except Exception as exc:
        raise RuntimeError(f"ไม่พบปุ่ม Measure ของ Task {task_id}") from exc
    visible_index = await locator.evaluate_all("""els => els.findIndex(el => {
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' &&
               style.opacity !== '0' && el.getClientRects().length > 0;
    })""")
    if int(visible_index) >= 0:
        log(f"MEASURE CLICK | task={task_id} | visible clone={visible_index}")
        await locator.nth(int(visible_index)).click(timeout=15000)
        await interaction_checkpoint(page, log, name=f"after Measure task={task_id}", wait_ms=1000)
        return

    # Act like an operator: open the row action/dropdown first, then click the
    # now-visible Measure command. Never dispatch a hidden DOM click.
    row = page.locator(f'tr[data-task="{task_id}"]').filter(has=locator.first).first
    if await row.count() == 0:
        row = page.locator(f'tr[data-task="{task_id}"]').first
    triggers = row.locator(
        'button.dropdown-toggle:visible, a.dropdown-toggle:visible, '
        'button[data-toggle="dropdown"]:visible, a[data-toggle="dropdown"]:visible, '
        '.btn-group > button:visible, .btn-group > a.btn:visible'
    )
    trigger = None
    for i in range(min(await triggers.count(), 8)):
        candidate = triggers.nth(i)
        if await candidate.is_visible() and await candidate.is_enabled():
            trigger = candidate
            break
    if trigger is None:
        raise RuntimeError(
            f"ปุ่ม Measure ของ Task {task_id} มีเฉพาะ element ที่ซ่อนอยู่ และไม่พบ Action menu ที่มองเห็นให้ operator กด"
        )
    log(f"ACTION MENU CLICK | task={task_id}")
    await trigger.click(timeout=10000)
    await page.wait_for_timeout(180)
    visible_index = await locator.evaluate_all("""els => els.findIndex(el => {
        const style = window.getComputedStyle(el);
        return style.display !== 'none' && style.visibility !== 'hidden' &&
               style.opacity !== '0' && el.getClientRects().length > 0;
    })""")
    if int(visible_index) < 0:
        raise RuntimeError(f"เปิด Action menu แล้วแต่ปุ่ม Measure ของ Task {task_id} ยังไม่แสดง")
    log(f"MEASURE CLICK | task={task_id} | after action menu")
    await locator.nth(int(visible_index)).click(timeout=15000)
    await interaction_checkpoint(page, log, name=f"after Measure task={task_id}", wait_ms=1000)


async def _task_rows(page) -> list[dict]:
    return await page.locator("tr[data-task]").evaluate_all("""els => els.map(tr => {
        const cells = Array.from(tr.querySelectorAll(':scope > td'));
        const measure = tr.querySelector('a.menu-measure-task');
        const style = window.getComputedStyle(tr);
        return {
          task_id: tr.getAttribute('data-task') || (measure && measure.getAttribute('data-task')) || '',
          lot: tr.getAttribute('data-lot') || (measure && measure.getAttribute('data-lot')) || '',
          document_name: cells[3] ? cells[3].innerText.trim() : '',
          can_measure: !!measure,
          can_view: !!tr.querySelector('a.menu-view-task'),
          visible: style.display !== 'none' && style.visibility !== 'hidden' &&
                   style.opacity !== '0' && tr.getClientRects().length > 0
        };
    })""")


def _visible_task_rows(rows: list[dict]) -> list[dict]:
    """Return only task rows that an operator can currently see.

    Production Check Sheet process 25 does NOT guarantee that a row's
    ``data-lot`` / displayed Production Date equals ``.date-monitor``.  The
    monitor date defines QAC's 08:00 -> next-day 08:00 query window, so a
    29-Sep monitor may legitimately contain rows whose Production Date is
    30-Sep.  Treating row dates as an acknowledgement of the monitor date
    creates false MISSING results.
    """
    return [row for row in rows if bool(row.get("visible"))]


async def _reuse_or_restore_task_list(
    page,
    production_date: str,
    log: Callable[[str], None],
) -> list[dict]:
    """Reuse the returned list first; open Calendar only when it is not active."""
    rows = await _task_rows(page)
    monitor_date = await _read_visible_monitor_date(page)
    reusable = _visible_task_rows(rows)
    if monitor_date is not None and monitor_date.isoformat() == production_date and reusable:
        row_dates = sorted({
            str(row.get("lot") or "") for row in reusable if row.get("lot")
        })
        log(
            f"QAC LIST REUSE | monitor={production_date} | "
            f"rows={len(reusable)} | row_dates={','.join(row_dates[:3]) or '-'} | ไปเอกสารถัดไป"
        )
        return reusable

    visible_dates = sorted({
        str(row.get("lot") or "") for row in rows
        if row.get("visible") and row.get("lot")
    })
    log(
        f"CALENDAR REQUIRED | target={production_date} | "
        f"monitor={monitor_date.isoformat() if monitor_date else '-'} | "
        f"row_dates={','.join(visible_dates[:3]) or '-'}"
    )
    await _set_date(page, production_date, log)
    await _wait_qac_complete(
        page,
        log,
        f"Restore Calendar {production_date}",
        ready_selector="i.calendar-monitor:visible, tr[data-task]",
    )
    return await _wait_for_task_list(
        page, production_date, log, timeout_seconds=90
    )


async def _wait_for_task_list(
    page,
    production_date: str,
    log: Callable[[str], None],
    timeout_seconds: int = 60,
) -> list[dict]:
    """Wait until process-25's visible task table is stable for the monitor day.

    QAC Production Check Sheet uses ``.date-monitor`` as the authoritative
    requested day, then queries ``08:00`` of that day through ``08:00`` of the
    next day.  Consequently, row ``data-lot`` / Production Date may differ
    from the monitor day (for example monitor 29-Sep with 30-Sep rows from the
    same production window).  The correct acknowledgement is therefore:

      1. visible date-monitor == requested day;
      2. QAC AJAX/Loading has completed (handled by _wait_qac_complete before
         this function); and
      3. the operator-visible task table remains unchanged for a short quiet
         interval.

    Never require row dates to equal the monitor date.
    """
    deadline = asyncio.get_running_loop().time() + max(5, timeout_seconds)
    last_signature = None
    stable_polls = 0
    last_log_bucket = -1
    latest_rows: list[dict] = []

    while asyncio.get_running_loop().time() < deadline:
        if await page.locator('input.form-control[placeholder="username"]').count() > 0:
            raise RuntimeError("QAC Session หมดอายุระหว่างรอ Document List")

        monitor_date = await _read_visible_monitor_date(page)
        if monitor_date is None:
            raise RuntimeError("อ่านวันที่จาก QAC date-monitor ไม่ได้")
        if monitor_date.isoformat() != production_date:
            raise RuntimeError(
                f"QAC date-monitor ไม่ตรงกับวันที่ที่รอ: "
                f"target={production_date}, monitor={monitor_date.isoformat()}"
            )

        rows = await _task_rows(page)
        latest_rows = _visible_task_rows(rows)
        signature = tuple(sorted(
            (
                str(row.get("task_id") or ""),
                str(row.get("lot") or ""),
                _norm(row.get("document_name")),
            )
            for row in latest_rows
        ))

        if signature == last_signature:
            stable_polls += 1
        else:
            stable_polls = 0
            last_signature = signature

        # Six 500 ms polls ~= 3 seconds of a stable, operator-visible table.
        # Empty is also a valid result once stable: it means QAC really has no
        # task rows for that monitor window, not that stale rows were filtered
        # out by a mismatched Production Date.
        if stable_polls >= 6:
            row_dates = sorted({
                str(row.get("lot") or "") for row in latest_rows if row.get("lot")
            })
            log(
                f"QAC LIST READY | monitor={production_date} | "
                f"rows={len(latest_rows)} | row_dates={','.join(row_dates[:3]) or '-'} | table stable"
            )
            return latest_rows

        remaining = max(0, int(deadline - asyncio.get_running_loop().time()))
        elapsed_bucket = (timeout_seconds - remaining) // 5
        if elapsed_bucket != last_log_bucket:
            last_log_bucket = elapsed_bucket
            row_dates = sorted({
                str(row.get("lot") or "") for row in latest_rows if row.get("lot")
            })
            log(
                f"WAIT QAC LIST | monitor={production_date} | "
                f"rows={len(latest_rows)} | row_dates={','.join(row_dates[:3]) or '-'} | "
                f"timeout_in={remaining}s"
            )
        await page.wait_for_timeout(500)

    row_dates = sorted({
        str(row.get("lot") or "")
        for row in _visible_task_rows(await _task_rows(page))
        if row.get("lot")
    })
    raise RuntimeError(
        f"QAC Document List ของ monitor {production_date} ไม่ stable ภายใน {timeout_seconds} วินาที "
        f"(Production Date ในแถว: {', '.join(row_dates[:5]) or 'ไม่มีแถว'})"
    )


async def collect_qac_html_async(
    cdp_url: str,
    production_date: str,
    documents: list[dict],
    output_root: str | Path,
    progress: Callable[[str], None] | None = None,
    control=None,
    delay_ms: int = 400,
    overwrite_existing: bool = False,
) -> dict:
    """Collect selected QAC HTML through a response-gated browser state machine."""
    from playwright.async_api import async_playwright

    def log(message: str) -> None:
        if progress:
            progress(str(message))

    selected_day = datetime.strptime(production_date, "%Y-%m-%d").date()
    search_window_dates = [
        (selected_day - timedelta(days=1)).isoformat(),
        selected_day.isoformat(),
    ]
    search_dates = [
        selected_day.isoformat(),
        (selected_day - timedelta(days=1)).isoformat(),
    ]
    batch_dir = (
        Path(output_root).expanduser().resolve()
        / f"QAC_HTML_{search_window_dates[0]}_to_{search_window_dates[1]}"
    )
    raw_dir = batch_dir / "raw_html"
    schema_dir = batch_dir / "schemas"
    raw_dir.mkdir(parents=True, exist_ok=True)
    schema_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = batch_dir / "manifest.json"
    previous = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        except Exception:
            previous = {}
    previous_by_key = {
        str(x.get("document_key")): x
        for x in previous.get("documents", [])
        if x.get("status") in {"COLLECTED", "SKIPPED_EXISTING"}
    }
    results: list[dict] = []
    resolved_keys: set[str] = set()

    def document_key(document: dict) -> str:
        seed = "|".join([
            production_date,
            str(document.get("document_name") or "").strip(),
            str(document.get("document_no") or "").strip(),
        ])
        return hashlib.sha1(seed.encode("utf-8")).hexdigest()[:16]

    def checkpoint() -> None:
        manifest_path.write_text(json.dumps({
            "schema_version": 2,
            "selected_date": production_date,
            "searched_dates": search_window_dates,
            "updated_at": datetime.now().isoformat(timespec="seconds"),
            "documents": results,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    for document in documents:
        key = document_key(document)
        if overwrite_existing:
            continue
        if key in previous_by_key:
            old = dict(previous_by_key[key])
            old_schema = batch_dir / str(old.get("schema_file") or "")
            old_html = batch_dir / str(old.get("raw_html") or "")
            if not old_schema.exists() or not old_html.exists():
                continue
            if str(old.get("found_date") or "").strip() != production_date:
                continue
            old["status"] = "SKIPPED_EXISTING"
            results.append(old)
            resolved_keys.add(key)
            log(
                f"SKIP EXISTING | {document.get('document_name', '')} | "
                f"raw={old.get('raw_html', '')}"
            )

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            if not browser.contexts:
                raise RuntimeError("ไม่พบ QAC Browser Context")
            context = browser.contexts[0]
            module_page = None
            for page in context.pages:
                try:
                    if (await page.evaluate("window.name || ''")) == "QAC_DAILY_DOCUMENT_MODULE":
                        module_page = page
                        break
                    if await page.locator("tr[data-task]").count() > 0:
                        module_page = page
                        break
                except Exception:
                    continue
            if module_page is None:
                raise RuntimeError("ไม่พบหน้า Production Check Sheet ที่เปิดอยู่")
            await module_page.bring_to_front()
            await _wait_qac_complete(
                module_page, log, "Production Check Sheet",
                ready_selector=".calendar-monitor, tr[data-task]",
            )

            for search_date in search_dates:
                await _wait_control(control)
                if len(resolved_keys) >= len(documents):
                    break
                log(f"DATE SEARCH START | {search_date}")
                await _set_date(module_page, search_date, log)
                await _wait_qac_complete(
                    module_page, log, f"Calendar {search_date}",
                    ready_selector=".calendar-monitor, tr[data-task]",
                )
                try:
                    task_rows = await _wait_for_task_list(
                        module_page, search_date, log, timeout_seconds=90
                    )
                except RuntimeError as exc:
                    log(f"DATE SEARCH ERROR | {search_date} | {exc}")
                    continue
                by_name = {}
                for row in task_rows:
                    by_name.setdefault(_norm(row.get("document_name")), []).append(row)

                for document in documents:
                    await _wait_control(control)
                    wanted_name = str(document.get("document_name") or "").strip()
                    key = document_key(document)
                    if key in resolved_keys:
                        continue
                    matches = by_name.get(_norm(wanted_name), [])
                    if not matches:
                        continue
                    task = matches[0]
                    if not task.get("can_measure"):
                        results.append({**document, **task, "document_key": key, "found_date": search_date, "status": "NO_MEASURE", "error": "ไม่มีปุ่ม Measure"})
                        resolved_keys.add(key)
                        checkpoint()
                        continue

                    sequence = len(resolved_keys) + 1
                    log(f"[{sequence}/{len(documents)}] MEASURE | date={search_date} | {wanted_name}")
                    measure_page = module_page
                    measure_opened = False
                    try:
                        pages_before = set(context.pages)
                        await _click_measure_action(
                            module_page, str(task.get("task_id") or ""), log
                        )
                        measure_opened = True
                        await module_page.wait_for_timeout(150)
                        new_pages = [page for page in context.pages if page not in pages_before]
                        if new_pages:
                            measure_page = new_pages[-1]
                        await _wait_qac_complete(
                            measure_page, log,
                            f"Measure task={task.get('task_id', '')}",
                            ready_selector=".fieldset[data-item]",
                        )
                        html_text = await measure_page.content()
                        stem = _safe_name(f"{search_date}_{document.get('document_no') or task.get('task_id')}_{wanted_name}")
                        html_path = raw_dir / f"{stem}.html"
                        html_path.write_text(html_text, encoding="utf-8")
                        schema = parse_qac_html(html_text, html_path.name)
                        schema.update({"document_key": key, "task_id": str(task.get("task_id") or ""), "found_date": search_date})
                        schema_path = schema_dir / f"{stem}.json"
                        schema_path.write_text(json.dumps(schema, ensure_ascii=False, indent=2), encoding="utf-8")
                        result = {
                            **document,
                            "document_key": key,
                            "task_id": str(task.get("task_id") or ""),
                            "found_date": search_date,
                            "status": "COLLECTED",
                            "field_count": schema.get("field_count", 0),
                            "maximum_slot": schema.get("maximum_slot", 0),
                            "raw_html": str(html_path.relative_to(batch_dir)),
                            "schema_file": str(schema_path.relative_to(batch_dir)),
                            "error": "",
                        }
                        results.append(result)
                        resolved_keys.add(key)
                        checkpoint()
                        log(f"[{len(resolved_keys)}/{len(documents)}] COLLECTED | fields={schema.get('field_count', 0)} | {wanted_name}")
                    except Exception as exc:
                        results.append({**document, **task, "document_key": key, "found_date": search_date, "status": "ERROR", "error": str(exc)})
                        resolved_keys.add(key)
                        checkpoint()
                        log(f"[{len(resolved_keys)}/{len(documents)}] ERROR | {wanted_name} | {exc}")
                    finally:
                        if not measure_opened:
                            pass
                        elif measure_page is not module_page:
                            try:
                                await measure_page.close()
                            except Exception:
                                pass
                            await module_page.bring_to_front()
                        else:
                            await _return_to_check_sheet(
                                module_page, log, str(task.get("task_id") or "")
                            )
                        if measure_opened:
                            if measure_page is not module_page:
                                await _wait_qac_complete(
                                    module_page, log, "Back to Production Check Sheet",
                                    ready_selector="i.calendar-monitor:visible",
                                )
                                log(f"BACK READY | task={task.get('task_id', '')}")
                            task_rows = await _reuse_or_restore_task_list(
                                module_page, search_date, log
                            )
                            by_name = {}
                            for row in task_rows:
                                by_name.setdefault(_norm(row.get("document_name")), []).append(row)
                    if delay_ms > 0:
                        await asyncio.sleep(delay_ms / 1000)

            for document in documents:
                key = document_key(document)
                if key in resolved_keys:
                    continue
                results.append({
                    **document,
                    "document_key": key,
                    "searched_dates": ",".join(search_window_dates),
                    "status": "MISSING",
                    "error": "ไม่พบเอกสารหลังค้นหาครบทั้งสองวันที่",
                })
                resolved_keys.add(key)
                log(f"[{len(resolved_keys)}/{len(documents)}] MISSING BOTH DATES | {document.get('document_name', '')}")
                checkpoint()
        finally:
            await browser.close()

    all_schemas = []
    for path in sorted(schema_dir.glob("*.json")):
        try:
            all_schemas.append(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            continue
    (batch_dir / "document_schema.json").write_text(json.dumps({"schema_version": 2, "selected_date": production_date, "searched_dates": search_window_dates, "documents": all_schemas}, ensure_ascii=False, indent=2), encoding="utf-8")

    with (batch_dir / "extraction_report.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        columns = ["status", "found_date", "searched_dates", "line", "model", "period", "document_name", "document_no", "task_id", "field_count", "maximum_slot", "raw_html", "schema_file", "error"]
        writer = csv.DictWriter(handle, fieldnames=columns, extrasaction="ignore")
        writer.writeheader(); writer.writerows(results)
    _write_field_mapping_csv(batch_dir / "field_mapping.csv", all_schemas)

    return {
        "output_directory": str(batch_dir),
        "total": len(documents),
        "collected": sum(x.get("status") == "COLLECTED" for x in results),
        "skipped": sum(x.get("status") == "SKIPPED_EXISTING" for x in results),
        "missing": sum(x.get("status") == "MISSING" for x in results),
        "errors": sum(x.get("status") in {"ERROR", "NO_MEASURE"} for x in results),
        "results": results,
    }

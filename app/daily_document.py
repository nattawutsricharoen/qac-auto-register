from __future__ import annotations

from pathlib import Path
from typing import Iterable
import csv
import os
from datetime import datetime, timedelta


def resolve_document_source(path_value: str, app_root: Path) -> Path:
    raw = os.path.expandvars(str(path_value or '').strip().strip('"'))
    if not raw:
        raise RuntimeError('ยังไม่ได้กำหนด Daily Document List Source ใน Settings')
    p = Path(raw)
    if not p.is_absolute():
        p = app_root / p
    return p.resolve()


def _clean(value) -> str:
    if value is None:
        return ''
    return str(value).strip()


def _canon(value: str) -> str:
    return ''.join(ch.lower() for ch in _clean(value) if ch.isalnum())


ALIASES = {
    'line': {'line', 'productionline'},
    'type': {'type'},
    'model': {'model'},
    'period': {'period'},
    'document_name': {'documentname', 'document', 'name'},
    'document_no': {'documentno', 'documentnumber', 'docno'},
    'target_num': {'targetnum', 'target', 'targetnumber'},
    'status': {'status'},
}


def classify_document_kind(row: dict) -> str:
    name = _clean(row.get('document_name')).casefold()
    period = _clean(row.get('period')).casefold()
    if any(marker in name for marker in (
        'production sample initial-final',
        'production sample initial / final',
        'stud bolt st#',
        'helium leak-production sample',
        'gas filling st#',
    )):
        return 'AUTO_CSV'
    if any(marker in name for marker in (
        'linear gauge present value',
        'tablet control',
    )):
        return 'MANUAL_VALUE'
    if any(marker in name for marker in (
        'cleaning before break',
        'machine daily condition check',
        'machine calibration',
        'checking the electrode pressing plane',
        'interlock & master check',
        'type change check',
        'master jig & dummy jig',
    )):
        return 'MANUAL_OK_NG'
    if period in {'daily', 'weekly'}:
        return 'REVIEW'
    return 'REVIEW'


def _header_map(headers: Iterable) -> dict[str, int]:
    normalized = [_canon(v) for v in headers]
    result = {}
    for key, aliases in ALIASES.items():
        for i, value in enumerate(normalized):
            if value in aliases:
                result[key] = i
                break
    required = ('line', 'model', 'period', 'document_name')
    missing = [k for k in required if k not in result]
    if missing:
        raise RuntimeError(
            'Document List header ไม่ครบ: ' + ', '.join(missing)
            + ' | ต้องมีอย่างน้อย Line, Model, Period, Document Name'
        )
    return result


def _row_to_dict(values, hm: dict[str, int]) -> dict:
    def get(key: str) -> str:
        idx = hm.get(key)
        if idx is None or idx >= len(values):
            return ''
        return _clean(values[idx])
    row = {
        'line': get('line'),
        'type': get('type'),
        'model': get('model'),
        'period': get('period'),
        'document_name': get('document_name'),
        'document_no': get('document_no'),
        'target_num': get('target_num'),
        'status': get('status'),
    }
    row['document_kind'] = classify_document_kind(row)
    return row


def _load_xlsx(path: Path, sheet_name: str) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[sheet_name] if sheet_name in wb.sheetnames else wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration:
            return []
        hm = _header_map(headers)
        out = []
        for values in rows:
            row = _row_to_dict(values, hm)
            if not row['document_name']:
                continue
            out.append(row)
        return out
    finally:
        wb.close()


def _load_csv(path: Path) -> list[dict]:
    with path.open('r', encoding='utf-8-sig', newline='') as f:
        rows = list(csv.reader(f))
    if not rows:
        return []
    hm = _header_map(rows[0])
    out = []
    for values in rows[1:]:
        row = _row_to_dict(values, hm)
        if row['document_name']:
            out.append(row)
    return out


def load_document_master(
    source_path: str,
    app_root: Path,
    sheet_name: str = 'Raw',
    active_only: bool = True,
) -> tuple[list[dict], Path]:
    path = resolve_document_source(source_path, app_root)
    if not path.exists():
        raise RuntimeError(f'Document List Source ไม่พบไฟล์: {path}')
    suffix = path.suffix.lower()
    if suffix in ('.xlsx', '.xlsm'):
        rows = _load_xlsx(path, sheet_name or 'Raw')
    elif suffix == '.csv':
        rows = _load_csv(path)
    else:
        raise RuntimeError('รองรับ Document List เฉพาะ .xlsx, .xlsm หรือ .csv')

    if active_only:
        rows = [
            r for r in rows
            if not r.get('status') or r.get('status', '').strip().lower() == 'active'
        ]

    # Stable de-duplication for accidentally duplicated master rows.
    seen = set()
    result = []
    for row in rows:
        key = (
            row.get('line', '').casefold(),
            row.get('model', '').casefold(),
            row.get('document_name', '').casefold(),
            row.get('document_no', '').casefold(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(row)
    return result, path

from .qac_task_scan import scan_qac_documents_async


async def open_daily_measure_async(cdp_url: str, task_id: str, document: dict | None = None) -> dict:
    """Open the exact scanned QAC row via its visible Action menu, read-only."""
    from playwright.async_api import async_playwright
    from .qac_session import is_trusted_qac_url, require_owned_qac_page
    from .qac_html_collector import (
        _click_measure_action, _reuse_or_restore_task_list, _task_rows,
        _visible_task_rows, _wait_qac_complete,
    )
    from .daily_slot_schema import verify_daily_measure_identity
    task_id = str(task_id or '').strip()
    doc = dict(document or {})
    date = str(doc.get('_scanned_production_date') or doc.get('found_date') or '').strip()
    if not task_id or not date or doc.get('task_id') != task_id:
        raise RuntimeError('Measure/Edit requires an exact scanned Task ID and Production Date')
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            if not browser.contexts:
                raise RuntimeError('QAC browser context unavailable')
            context = browser.contexts[0]
            page = None
            for candidate in context.pages:
                if candidate.is_closed() or not is_trusted_qac_url(candidate.url):
                    continue
                try:
                    if await candidate.evaluate('window.name || ""') == 'QAC_DAILY_DOCUMENT_MODULE':
                        page = candidate
                        break
                except Exception:
                    continue
            if page is None:
                raise RuntimeError('QAC DAILY module session not found')
            await require_owned_qac_page(page, tag='QAC_DAILY_DOCUMENT_MODULE',
                                         ready_selector='.calendar-monitor, tr[data-task]')
            rows = _visible_task_rows(await _task_rows(page))
            row = next((r for r in rows if str(r.get('task_id')) == task_id and
                        str(r.get('lot') or '')[:10] == date), None)
            if row is None:
                rows = await _reuse_or_restore_task_list(page, str(doc.get('monitor_date') or date), lambda _: None)
                row = next((r for r in rows if str(r.get('task_id')) == task_id and
                            str(r.get('lot') or '')[:10] == date), None)
            if row is None:
                raise RuntimeError(f'MEASURE TASK NOT FOUND | task={task_id} date={date} | Rescan')
            await _click_measure_action(page, task_id, lambda _: None)
            await _wait_qac_complete(page, lambda _: None, f'Measure {task_id}',
                                     ready_selector='.task-infomation, .fieldset[data-item]')
            await verify_daily_measure_identity(page, dict(doc, _daily_production_date=date))
            return {'task_id': task_id, 'opened': True, 'production_date': date}
        finally:
            await browser.close()

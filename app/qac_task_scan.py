"""QAC shared read-only task discovery; independent of Daily and Sample rules."""
from __future__ import annotations
from datetime import datetime, timedelta

async def scan_qac_documents_async(cdp_url: str, production_date: str, documents: list[dict], progress=None, *, module_tag: str = "QAC_DAILY_DOCUMENT_MODULE") -> list[dict]:
    """Scan the Production Check Sheet task table for exact master names.

    Search the chosen production date in its own and adjacent QAC monitor
    windows (the UI uses an 08:00-to-08:00 query). Require exact data-lot
    equality with the explicitly requested date. Never substitute today or
    accept a name-only hit.
    """
    from playwright.async_api import async_playwright
    from .qac_html_collector import _set_date, _wait_for_task_list, _wait_qac_complete

    def log(msg):
        if progress:
            progress(str(msg))

    def norm(text: str) -> str:
        return ' '.join(str(text or '').replace('\xa0', ' ').split()).casefold()

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            context = browser.contexts[0]
            page = None
            for p in context.pages:
                try:
                    if (await p.evaluate("window.name || ''")) == module_tag:
                        page = p
                        break
                except Exception:
                    pass
            if page is None:
                raise RuntimeError(f'ไม่พบหน้า QAC ที่ตรงกับ Session {module_tag} กรุณาเปิด Module ก่อน Scan')

            # Recover from an interrupted prior Register only when the URL and
            # live DOM both prove this is the QAC Measure screen. Never try a
            # blind history traversal on an unknown QAC page.
            if await page.locator("i.calendar-monitor:visible").count() == 0:
                url = str(getattr(page, "url", "") or "")
                if "measure.html" in url.casefold() and await page.locator(".fieldset[data-item]:visible").count() > 0:
                    log(f"SAMPLE CHECK SHEET RESTORE | previous Measure page detected | url={url}")
                    try:
                        await page.go_back(wait_until="commit", timeout=15000)
                    except Exception as exc:
                        if "master.html" not in str(getattr(page, "url", "") or "").casefold():
                            raise RuntimeError(f"Sample QAC session กลับจาก Measure ไม่สำเร็จ: {exc}") from exc
                    await _wait_qac_complete(page, log, "Restore Sample Check Sheet", ready_selector=".calendar-monitor, tr[data-task]")
                    if await page.locator("i.calendar-monitor:visible").count() == 0:
                        raise RuntimeError("QAC กลับจาก Measure แล้ว แต่ยังไม่มี Calendar ของ Production Check Sheet ที่มองเห็น")
                    log("SAMPLE CHECK SHEET RESTORED | calendar visible")
                else:
                    raise RuntimeError(
                        "SAMPLE QAC WRONG PAGE | ไม่พบ Calendar; "
                        "กรุณาเปิดหน้า Production Check Sheet ของ Sample Session "
                        f"(url={url})"
                    )

            selected_day = datetime.strptime(production_date, '%Y-%m-%d').date()
            search_dates = [
                selected_day.isoformat(),
                (selected_day - timedelta(days=1)).isoformat(),
                (selected_day + timedelta(days=1)).isoformat(),
            ]
            found_by_doc = {}

            for search_date in search_dates:
                if len(found_by_doc) == len(documents):
                    break
                log(f"DATE SEARCH START | {search_date} | requested_production_date={selected_day.isoformat()}")
                await _set_date(page, search_date, log)
                await _wait_qac_complete(
                    page,
                    log,
                    f"Calendar {search_date}",
                    ready_selector=".calendar-monitor, tr[data-task]",
                )
                try:
                    rows = await _wait_for_task_list(
                        page,
                        search_date,
                        log,
                        timeout_seconds=90,
                    )
                except RuntimeError as exc:
                    log(f"DATE SEARCH ERROR | {search_date} | {exc}")
                    continue

                # QAC process 25's date-monitor is authoritative.  Its query
                # window is 08:00 -> next-day 08:00, so rows displayed under a
                # 29-Sep monitor may legitimately carry Production Date 30-Sep.
                # Search the operator-visible rows returned for that monitor
                # window; do not reject them by data-lot.
                by_key = {}
                for r in rows:
                    by_key.setdefault(norm(r.get('document_name')), []).append(r)

                # Task discovery must match the requested PRODUCTION date, not
                # merely the QAC calendar monitor's day (08:00-day boundary).
                requested_lot = selected_day.isoformat()
                for index, doc in enumerate(documents):
                    if index in found_by_doc:
                        continue
                    wanted = norm(doc.get('document_name'))
                    matches = by_key.get(wanted, [])
                    if not matches:
                        matches = [
                            r for r in rows
                            if norm(r.get('document_name')) == wanted
                        ]
                    exact = [r for r in matches if str(r.get('lot') or '').strip()[:10] == requested_lot]
                    if matches and not exact:
                        log(f'DAILY SCAN WRONG DATE | requested={requested_lot} | document={doc.get("document_name")} | candidate_lots={[r.get("lot") for r in matches[:4]]} | skip')
                    if len(exact) > 1:
                        # Multiple dates/name matches require a unique reliable
                        # identity. A guessed first row risks writing wrong data.
                        doc_no = norm(doc.get('document_no'))
                        narrowed = [r for r in exact if norm(r.get('document_no')) == doc_no] if doc_no else exact
                        if len(narrowed) != 1:
                            log(f'DAILY SCAN AMBIGUOUS | date={requested_lot} | document={doc.get("document_name")} | task_ids={[r.get("task_id") for r in exact]} | skip')
                            continue
                        exact = narrowed
                    if exact:
                        r = exact[0]
                        found_by_doc[index] = {
                            **doc, **r,
                            'found_date': requested_lot,
                            'monitor_date': search_date,
                            'searched_dates': search_date,
                            'scan_status': 'FOUND', 'action': 'EDIT',
                        }
                        log(f'FOUND | production_date={requested_lot} | monitor={search_date} | {doc.get("document_name")} | task={r.get("task_id")}')

            result = []
            for index, doc in enumerate(documents):
                if index in found_by_doc:
                    result.append(found_by_doc[index])
                else:
                    result.append({
                        **doc,
                        'task_id': '',
                        'found_date': '',
                        'searched_dates': ','.join(search_dates),
                        'scan_status': 'MISSING',
                        'action': 'CREATE',
                    })
                    log(f"MISSING REQUESTED DATE | {doc.get('document_name')}")
            return result
        finally:
            await browser.close()



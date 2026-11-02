"""Fail-closed Inflator Data Inspection upload/check via the existing QAC CDP session.

QAC writes are non-idempotent: ambiguous upload responses MUST NOT be retried.
"""
from __future__ import annotations
import asyncio
import re
from pathlib import Path
from playwright.async_api import async_playwright

MODULE_TAG = 'QAC_PRODUCTION_TRANSFER_MODULE'
MODULE_SELECTOR = 'a.btn.btn-sm.btn-primary[data-factory-process="2"][data-process="10"][data-product-type="4"]'


def extract_lot(filename: str) -> str:
    stem = Path(filename).stem
    m = re.match(r'^(\d{8}-[A-Za-z0-9]+-\d+)(?:CR|R)?(?:\(|$)', stem, re.I)
    if not m:
        raise ValueError('ไม่สามารถระบุ Production Lot อย่างปลอดภัยจากชื่อไฟล์ กรุณาตรวจชื่อไฟล์')
    return m.group(1)


def judges_all_pass(judges: list[str]) -> bool:
    return bool(judges) and all(str(j).strip().upper() == 'PASS' for j in judges)


async def _find_module(context, employee_id, progress):
    for p in context.pages:
        try:
            if await p.evaluate('window.name') == MODULE_TAG and not p.is_closed():
                return p
        except Exception:
            pass
    # Open an independent tab; do not repurpose Auto/Daily/Sample tabs.
    from .qac_session import QAC_HOME_URL, _login_if_needed
    page = await context.new_page()
    await page.goto(QAC_HOME_URL, wait_until='domcontentloaded', timeout=30000)
    await _login_if_needed(page, employee_id, progress)
    await page.locator(MODULE_SELECTOR).first.wait_for(state='visible', timeout=25000)
    existing_ids = {id(p) for p in context.pages}
    before_url = page.url
    await page.locator(MODULE_SELECTOR).first.click(no_wait_after=True, timeout=15000)
    for _ in range(80):
        fresh = [p for p in context.pages if id(p) not in existing_ids]
        target = fresh[-1] if fresh else page
        if (target.url != before_url or fresh) and await target.get_by_text('Register Task', exact=True).count():
            await target.evaluate('tag => window.name = tag', MODULE_TAG)
            progress('TRANSFER MODULE READY | Inflator Data Inspection')
            return target
        await asyncio.sleep(.2)
    raise RuntimeError('ไม่พบหน้า Inflator Data Inspection หลัง VIEW MORE')


async def _alert_ok(page, required=True):
    alert = page.locator('.swal2-container:visible')
    try:
        await alert.wait_for(state='visible', timeout=60000 if required else 1500)
    except Exception:
        if required: raise RuntimeError('QAC ไม่ตอบกลับด้วย Complete/Success popup')
        return
    text = (await alert.inner_text()).lower()
    if any(x in text for x in ('error', 'failed', 'warning', 'ผิดพลาด', 'ไม่สำเร็จ')):
        raise RuntimeError('QAC popup แจ้งปัญหา: ' + text[:400])
    if not any(x in text for x in ('complete', 'success', 'สำเร็จ')):
        raise RuntimeError('QAC popup ไม่ยืนยัน Success: ' + text[:400])
    await alert.locator('button.swal2-confirm').click(timeout=10000, no_wait_after=True)


async def _upload(page, file_path, progress):
    button = page.locator('.box-widget.btn-primary').filter(has_text='Register Task').first
    await button.wait_for(state='visible', timeout=20000)
    await button.click(timeout=15000)
    fileinput = page.locator('input[type="file"]')
    if await fileinput.count():
        await fileinput.first.set_input_files(file_path)
    else:
        async with page.expect_file_chooser(timeout=12000) as chosen:
            await page.get_by_text('browse', exact=True).click()
        await (await chosen.value).set_files(file_path)
    confirm = page.locator('button[type="submit"].btn-primary').filter(has_text=re.compile('Confirm|ยืนยัน')).first
    await confirm.wait_for(state='visible', timeout=15000)
    # This is a non-idempotent write: submit ONCE only; never retry on timeout.
    progress('TRANSFER UPLOAD SUBMIT | รอ QAC Complete')
    await confirm.click(no_wait_after=True, timeout=15000)
    await _alert_ok(page, required=True)
    progress('TRANSFER UPLOAD SUCCESS | QAC acknowledged')


def _judge_values_from_rows(rows: list[dict]) -> list[str]:
    matches = [r for r in rows if r.get('label', '').strip().lower() in ('judge', 'judgement', 'judgment')]
    if len(matches) != 1:
        raise RuntimeError('ไม่พบแถว Judge ที่ชัดเจนเพียงแถวเดียว')
    values = matches[0]['values']
    if not judges_all_pass(values):
        raise RuntimeError(f'Judge ไม่ใช่ PASS ทุกหัวข้อ: {values}')
    return values


async def _inspect(page, task_id, lot, progress):
    # Read every cell via DOM, including horizontally scrolled/off-screen columns.
    view = page.locator(f'a.menu-view-task[data-task="{task_id}"]').first
    await view.wait_for(state='visible', timeout=20000)
    if await view.get_attribute('data-lot') != lot:
        raise RuntimeError('Lot ของ task ไม่ตรงกับไฟล์ที่อัปโหลด')
    await view.click(timeout=15000)
    modal = page.locator('.modal:visible').filter(has_text='Inspection Result').first
    await modal.wait_for(state='visible', timeout=20000)
    rows = await modal.locator('table tr').evaluate_all('''trs => trs.map(tr => ({
        label: (tr.querySelector('th,td')?.innerText || '').trim(),
        values: Array.from(tr.querySelectorAll('th,td')).slice(1).map(x => (x.innerText || '').trim())
    }))''')
    judges = _judge_values_from_rows(rows)
    progress(f'TRANSFER JUDGE VERIFIED | {len(judges)} PASS')
    checked = modal.locator(f'button.button-checked[data-task="{task_id}"]')
    await checked.wait_for(state='visible', timeout=10000)
    # Some QAC pages use "Checked" button to *perform* checking while others
    # show it as an already-checked state.  Require explicit state confirmation.
    status = (await checked.inner_text()).strip().lower()
    if 'checked' not in status and 'ตรวจสอบแล้ว' not in status:
        raise RuntimeError('ปุ่ม Checked ไม่ตรงกับ HTML ที่ยืนยัน')
    await checked.click(timeout=15000, no_wait_after=True)
    await _alert_ok(page, required=True)
    progress('TRANSFER CHECKED | QAC popup confirmed')
    close = modal.locator(f'button.btn-close[data-task="{task_id}"]')
    await close.click(timeout=10000)
    return {'lot': lot, 'task_id': task_id, 'judge_count': len(judges)}


async def transfer_line_data_async(cdp_url: str, employee_id: str, file_path: str, progress):
    file_path = str(Path(file_path).resolve())
    if not Path(file_path).is_file():
        raise FileNotFoundError(file_path)
    if Path(file_path).suffix.lower() not in {'.xlsx', '.xlsm'}:
        raise ValueError('QAC Data Inspection รองรับเฉพาะไฟล์ Excel ที่กำหนด')
    lot = extract_lot(Path(file_path).name)
    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        if not browser.contexts: raise RuntimeError('ไม่พบ QAC Browser Context')
        context = browser.contexts[0]
        page = await _find_module(context, employee_id, progress)
        # Exact-lot preflight avoids submitting an existing lot again.
        existing = page.locator('a.menu-view-task[data-lot="%s"]' % lot)
        if await existing.count():
            raise RuntimeError('พบ Lot นี้ใน QAC แล้ว: ' + lot + ' — ไม่ Upload ซ้ำ')
        await _upload(page, file_path, progress)
        matches = page.locator('a.menu-view-task[data-lot="%s"]' % lot)
        try: await matches.first.wait_for(state='attached', timeout=30000)
        except Exception: raise RuntimeError('Upload Complete แต่ยังไม่พบ Task ของ Lot — ห้าม Upload ซ้ำ กรุณาตรวจ QAC')
        if await matches.count() != 1:
            raise RuntimeError('พบ Task ของ Lot เดียวกันหลายรายการ — ต้องตรวจสอบด้วยตนเอง')
        task_id = await matches.first.get_attribute('data-task')
        if not task_id or not task_id.isdigit():
            raise RuntimeError('Task ID ไม่ถูกต้อง')
        return await _inspect(page, task_id, lot, progress)

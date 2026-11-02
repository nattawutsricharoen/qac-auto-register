"""Daily-only read-only QAC Measure DOM discovery; no Sample business rules."""
from __future__ import annotations
from datetime import datetime
import asyncio
from decimal import Decimal, InvalidOperation
from .qac_html_collector import _click_measure_action, _return_to_check_sheet, _reuse_or_restore_task_list, _wait_qac_complete, _task_rows, _visible_task_rows

async def extract_daily_slot_schema(page):
    """Read QAC UI, including individually existing slots; never invent a count."""
    await _wait_qac_complete(page, lambda _: None, 'Daily Measure', ready_selector='.fieldset[data-item], .f1-step[data-item]')
    return await page.evaluate("""() => {
      const formatValue=(field,step)=>String(field.getAttribute('data-input-format')||step.getAttribute('data-input')||'');
      const steps=[...document.querySelectorAll('.f1-step[data-item]')];
      return steps.map(step=>{
        const item=step.getAttribute('data-item');
        const field=document.querySelector('.fieldset[data-item="'+CSS.escape(item)+'"]');
        if(!field)return null;
        const rows=[...field.querySelectorAll('tr[data-result-no]')];
        const slots=rows.map(row=>{
          const n=Number(row.getAttribute('data-result-no'));
          const inp=row.querySelector('input[data-result-no], textarea[data-result-no]');
          const resultId=inp?.getAttribute('data-result') || [...row.querySelectorAll('[data-result]')].map(x=>x.getAttribute('data-result')).find(x=>x && x!=='0') || '';
          const text=(row.textContent||'').trim();
          const noResult=/No Result|ไม่มีผลการตรวจสอบ/i.test(text);
          const emptyFlag=row.getAttribute('data-empty') || inp?.getAttribute('data-empty') || '';
          const tokens=text.toUpperCase().split(/[^A-Z]+/).filter(Boolean);
          const category=formatValue(field,step);
          const categorical=category==='4' ? ['OK','NG'] : category==='3' ? ['INITIAL','MIDDLE','FINAL'] : [];
          const hits=categorical.filter(v=>tokens.includes(v));
          const displayedValue=hits.length===1 ? hits[0] : '';
          const numeric=inp?.value || inp?.getAttribute('value') || '';
          const explicitResult=Boolean(resultId && resultId!=='0');
          const saved= !noResult && (explicitResult || (emptyFlag==='false' && (displayedValue || (category==='1' && String(numeric).trim()!==''))));
          const sidebarSuccess=step.getAttribute('data-success')==='1' || field.getAttribute('data-success')==='1';
          const cleanEmpty=emptyFlag==='true' && !explicitResult && !String(numeric).trim() && !displayedValue && (category==='1' ? !sidebarSuccess : noResult);
          const unknown=!saved && !cleanEmpty;
          return {number:n, saved:!!saved, result_id:resultId, value:displayedValue || (category==='1'?String(numeric).trim():''), status:saved?'SAVED':unknown?'UNKNOWN':'EMPTY'};
        }).filter(x=>Number.isInteger(x.number)&&x.number>0);
        const format=String(field.getAttribute('data-input-format')||step.getAttribute('data-input')||'');
        const options=format==='3' ? ['Initial','Middle','Final'] : format==='4' ? ['OK','NG'] : format==='1' ? ['VALUE'] : [];
        return {item, label:(step.querySelector('.f1-step-p')?.innerText||'').trim(),
          batch_empty_evidence: (step.getAttribute('data-success')==='0' && field.getAttribute('data-success')==='0' && rows.length>0 && rows.every(row=>{
             const inp=row.querySelector('input[data-result-no], textarea[data-result-no]');
             const result=inp?.getAttribute('data-result') || [...row.querySelectorAll('[data-result]')].map(x=>x.getAttribute('data-result')).find(x=>x&&x!=='0') || '';
             return row.getAttribute('data-empty')==='true' && !result && !String(inp?.value || inp?.getAttribute('value') || '').trim()
               && Number.isInteger(Number(row.getAttribute('data-result-no'))) && Number(row.getAttribute('data-result-no'))>0;
          })),
          format, frequency:Number(field.getAttribute('data-frequency')||step.getAttribute('data-frequency')||'0'),
          slots, options};
      }).filter(Boolean);
    }""")

def can_reuse_batch_item(item):
    """Only skip activation with complete, explicit persisted QAC evidence.

    A QAC fieldset can exist before AJAX loads its saved results. Text labels,
    sidebar success, empty flags, and an input value alone are insufficient.
    """
    if not isinstance(item, dict) or not item.get('item') or not item.get('slots'):
        return False
    if str(item.get('format')) not in ('1', '3', '4'):
        return False
    seen = set()
    for slot in item['slots']:
        try:
            number = int(slot['number'])
        except (TypeError, ValueError, KeyError):
            return False
        if number < 1 or number in seen:
            return False
        seen.add(number)
        if slot.get('status') != 'SAVED' or not slot.get('saved'):
            return False
        if not str(slot.get('result_id') or '').strip().strip('0'):
            return False
        value = str(slot.get('value') or '').strip()
        if not value:
            return False
        if str(item['format']) == '1':
            try:
                validate_qac_numeric_choice('VALUE:' + value)
            except (ValueError, TypeError):
                return False
        elif str(item['format']) == '4' and value.upper() not in ('OK', 'NG'):
            return False
        elif str(item['format']) == '3' and value.upper() not in ('INITIAL', 'MIDDLE', 'FINAL'):
            return False
    return True


def can_reuse_verified_empty_target(item):
    """Fast-path ONLY for an unsubmitted target with explicit QAC empty evidence.

    Reference results never use this optimization. QAC success=1 with an
    apparently empty fieldset is a lazy-load conflict, not a blank record.
    """
    if not isinstance(item, dict) or not item.get('batch_empty_evidence'):
        return False
    slots = item.get('slots') or []
    if not item.get('item') or not slots:
        return False
    seen = set()
    for slot in slots:
        try:
            n = int(slot['number'])
        except (TypeError, ValueError, KeyError):
            return False
        if n < 1 or n in seen or slot.get('status') != 'EMPTY' or slot.get('saved'):
            return False
        if slot.get('result_id') or str(slot.get('value') or '').strip():
            return False
        seen.add(n)
    return True


async def refresh_daily_results_by_activation(page, schema, log=None, *, target_scan=False):
    """QAC lazy-renders inspection results. Inspect each item after activating it.

    Never infer EMPTY from a non-activated fieldset. Only trust evidence from
    the active QAC DOM; abort rather than silently return an all-empty snapshot.
    """
    if not schema:
        return schema
    # One browser round trip for all already rendered results; do not trust
    # unactivated EMPTY/UNKNOWN rows or partially saved documents.
    import time
    started = time.perf_counter()
    refreshed=[]
    batch_accepted = 0
    activated = 0
    verified_empty = 0
    fallback_evidence = []
    for i, original in enumerate(schema):
        if can_reuse_batch_item(original):
            refreshed.append(original)
            batch_accepted += 1
            continue
        if target_scan and can_reuse_verified_empty_target(original):
            refreshed.append(original)
            verified_empty += 1
            continue
        activated += 1
        item_started = time.perf_counter()
        if len(fallback_evidence) < 12:
            fallback_evidence.append({
                'item': str(original.get('item') or ''),
                'format': str(original.get('format') or ''),
                'sidebar_empty_evidence': bool(original.get('batch_empty_evidence')),
                'statuses': [str(x.get('status') or '') for x in (original.get('slots') or [])][:8],
            })
        item_id=str(original['item'])
        step=page.locator(f'.f1-step[data-item="{item_id}"]').first
        field=page.locator(f'.fieldset[data-item="{item_id}"]').first
        await step.click(timeout=12000)
        await field.wait_for(state='visible',timeout=12000)
        # Ensure DOM from the selected item has been rendered, and busy overlay
        # has cleared; no unconditional sleep or whole-page HTML snapshots.
        await _wait_qac_complete(page, lambda _:None, f'Daily item {item_id}',
                                 ready_selector=f'.fieldset[data-item="{item_id}"]:visible')
        current=await extract_daily_item_schema(page,item_id)
        if not current or len(current['slots']) != len(original['slots']):
            raise RuntimeError(f'DAILY RESULT READER UNREADY | item={item_id} | abort scan')
        # QAC sometimes advertises a successful item even while its Result
        # rows remain blank (lazy loading/race). Never declare those EMPTY.
        success = await step.get_attribute('data-success')
        if success == '1' and current['slots'] and all(x['status']=='EMPTY' for x in current['slots']):
            for slot in current['slots']:
                slot['status']='UNKNOWN'
                slot['saved']=False
            if log:
                log(f'DAILY RESULT CONFLICT | item={item_id} sidebar_success=1 rows=EMPTY | mark UNKNOWN; block write')
        if current.get('format') == '1' and step is not None:
            sidebar_success = await step.get_attribute('data-success')
            if sidebar_success == '1' and not any(x['status']=='SAVED' for x in current['slots']):
                for slot in current['slots']:
                    if slot['status']=='EMPTY':
                        slot['status']='UNKNOWN'
                if log:
                    log(f'DAILY NUMERIC SUCCESS WITHOUT RESULT | item={item_id} | STOP/UNKNOWN; inspect QAC View')
        current['label']=original['label']
        current['frequency']=original['frequency']
        refreshed.append(current)
        if log and (time.perf_counter() - item_started) > 3.0:
            log(f'DAILY READER SLOW ITEM | item={item_id} elapsed_ms={int((time.perf_counter()-item_started)*1000)}')
        if log and (i < 3 or any(x['status']=='SAVED' for x in current['slots'])):
            log(f'DAILY ACTIVE RESULT | item={item_id} | slots='+
                ','.join(f"{x['number']}:{x['status']}:{x.get('value','')}" for x in current['slots']))
    if log:
        log(f'DAILY BATCH READ AUDIT | total={len(schema)} | batch_verified={batch_accepted} | target_empty_verified={verified_empty} | activated={activated} | elapsed_ms={int((time.perf_counter()-started)*1000)}')
        if activated:
            log(f'DAILY BATCH FALLBACK EVIDENCE | examples={fallback_evidence}')
    return refreshed


async def extract_daily_item_schema(page, item_id: str):
    """Read just one item's live DOM for preflight/verification; avoid 76-item scans."""
    return await page.evaluate("""itemId => {
      const step=[...document.querySelectorAll('.f1-step[data-item]')].find(s=>s.getAttribute('data-item')===itemId);
      const field=[...document.querySelectorAll('.fieldset[data-item]')].find(s=>s.getAttribute('data-item')===itemId);
      if (!step || !field) return null;
      const format=String(field.getAttribute('data-input-format')||step.getAttribute('data-input')||'');
      const options=format==='3'?['Initial','Middle','Final']:format==='4'?['OK','NG']:format==='1'?['VALUE']:[];
      const slots=[...field.querySelectorAll('tr[data-result-no]')].map(row=>{
        const number=Number(row.getAttribute('data-result-no'));
        const inp=row.querySelector('input[data-result-no],textarea[data-result-no]');
        const id=inp?.getAttribute('data-result')||[...row.querySelectorAll('[data-result]')].map(x=>x.getAttribute('data-result')).find(x=>x&&x!=='0')||'';
        const text=(row.textContent||'').trim();
        const noResult=/No Result|ไม่มีผลการตรวจสอบ/i.test(text);
        const flag=row.getAttribute('data-empty')||inp?.getAttribute('data-empty')||'';
        const tokens=text.toUpperCase().split(/[^A-Z]+/).filter(Boolean);
        const hits=(format==='4'?['OK','NG']:format==='3'?['INITIAL','MIDDLE','FINAL']:[]).filter(x=>tokens.includes(x));
        const value=hits.length===1?hits[0]:(format==='1'?String(inp?.value||inp?.getAttribute('value')||'').trim():'');
        const saved=!noResult&&(!!(id&&id!=='0')||(flag==='false'&&!!value));
        const sidebarSuccess=step.getAttribute('data-success')==='1' || field.getAttribute('data-success')==='1';
        const cleanEmpty=flag==='true' && !id && !value && (format==='1' ? !sidebarSuccess : noResult);
        return {number,saved:!!saved,result_id:id,value,status:saved?'SAVED':cleanEmpty?'EMPTY':'UNKNOWN'};
      }).filter(x=>Number.isInteger(x.number)&&x.number>0);
      return {item:itemId,format,slots,options,frequency:Number(field.getAttribute('data-frequency')||step.getAttribute('data-frequency')||'0'),label:(step.querySelector('.f1-step-p')?.innerText||'').trim()};
    }""", str(item_id))


def _normalise_qac_date(value: str) -> str:
    """Normalize QAC's displayed production day; never infer from calendar offset."""
    raw = ' '.join(str(value or '').replace('\xa0', ' ').split())
    for fmt in ('%d-%m-%Y', '%Y-%m-%d', '%d/%m/%Y', '%d/%m/%y', '%d-%b-%y', '%d %B %Y'):
        try:
            return datetime.strptime(raw, fmt).date().isoformat()
        except ValueError:
            pass
    return ''


async def verify_daily_measure_identity(page, document: dict, log=None):
    """Fail closed when actual QAC production date differs from selected day."""
    actual = await page.evaluate("""() => {
      const root=document.querySelector('.task-infomation.fieldset');
      if (!root) return null;
      const text=(root.textContent||'').replace(/\\s+/g,' ').trim();
      const headers=[...root.querySelectorAll('h5')];
      const productionHeader=headers.find(h=>/^Production date\\s*:/i.test((h.textContent||'').trim()));
      let productionDate='';
      if(productionHeader){
        const sibling=productionHeader.nextElementSibling;
        if(sibling) productionDate=(sibling.textContent||'').trim();
      }
      return {text:text.slice(0,4500), productionDate,
              itemCount:document.querySelectorAll('.fieldset[data-item]').length};
    }""")
    if not actual or actual['itemCount'] < 1:
        raise RuntimeError('DAILY PAGE IDENTITY UNKNOWN | Measure task information or items absent; no write')
    name=' '.join(str(document.get('document_name') or '').split())
    docno=str(document.get('document_no') or '').strip()
    text=' '.join(actual['text'].split())
    if name and name.casefold() not in text.casefold():
        raise RuntimeError(f'DAILY PAGE IDENTITY MISMATCH | expected_name={name}; no write')
    if docno and docno.casefold() not in text.casefold():
        raise RuntimeError(f'DAILY PAGE IDENTITY MISMATCH | expected_document_no={docno}; no write')
    expected = str(document.get('_daily_production_date') or document.get('_expected_production_date') or '').strip()
    observed = _normalise_qac_date(actual.get('productionDate', ''))
    if log:
        log(f'DAILY DATE EVIDENCE | expected={expected or "unset"} | displayed={actual.get("productionDate") or "missing"} | actual={observed or "UNREADABLE"}')
    if expected:
        if not observed:
            raise RuntimeError(f'DAILY PRODUCTION DATE UNKNOWN | expected={expected} | block QAC write')
        if observed != expected:
            raise RuntimeError(f'DAILY PRODUCTION DATE MISMATCH | expected={expected} actual={observed} | block QAC write; Scan correct day/task')
    if log:
        log(f'DAILY PAGE IDENTITY VERIFIED | document={name} | document_no={docno or "unavailable"} | production_date={observed or "unverified"} | items={actual["itemCount"]}')
    return actual


async def _read_daily_existing_values(page):
    """Read persisted values from QAC DOM only; no previous-day inference."""
    return await page.evaluate("""() => {
      const out=[];
      for (const step of document.querySelectorAll('.f1-step[data-item]')) {
        const id=step.getAttribute('data-item');
        const field=document.querySelector('.fieldset[data-item="'+CSS.escape(id)+'"]');
        if (!field) continue;
        const format=String(field.getAttribute('data-input-format')||step.getAttribute('data-input')||'');
        const label=(step.querySelector('.f1-step-p')?.innerText||'').trim();
        for (const row of field.querySelectorAll('tr[data-result-no]')) {
          const number=Number(row.getAttribute('data-result-no'));
          const input=row.querySelector('input[data-result-no],textarea[data-result-no]');
          const result=input?.getAttribute('data-result') || [...row.querySelectorAll('[data-result]')].map(x=>x.getAttribute('data-result')).find(Boolean);
          const text=(row.textContent||'').trim();
          const flag=row.getAttribute('data-empty') || input?.getAttribute('data-empty') || '';
          const actuallySaved=!!(result && result!=='0') || (flag==='false' && !/No Result|ไม่มีผลการตรวจสอบ/i.test(text));
          if (!actuallySaved || !Number.isInteger(number)) continue;
          let value='';
          if (format==='1') value=String(input?.value||input?.getAttribute('value')||'').trim();
          // For categorical results, require literal DOM text: never guess OK/NG
          // from undocumented codes like data-type=1.
          if (format==='3'||format==='4') {
            const text=(row.textContent||'').toLowerCase();
            const words=format==='3'?['Initial','Middle','Final']:['OK','NG'];
            const tokens=text.split(/[^a-z]+/i).filter(Boolean);
            const hits=words.filter(x=>tokens.includes(x.toLowerCase()));
            if (hits.length===1)value=hits[0];
          }
          out.push({item:id,label,format,number,value,result_id:result||"", readable:!!value});
        }
      }
      return out;
    }""")



async def _open_reference_task(page, task_id: str, log):
    """Open the same QAC Measure interface used by the target document.

    Never silently substitute View: View's result matrix is not the live
    per-item Measure DOM and previously caused unreadable numeric references.
    """
    try:
        await _click_measure_action(page, task_id, log)
    except Exception as exc:
        raise RuntimeError(
            f'DAILY REFERENCE MEASURE UNAVAILABLE | task={task_id}; '
            'QAC does not expose a usable Measure action; no View fallback'
        ) from exc
    log(f'DAILY REFERENCE MEASURE OPEN | task={task_id}')


def _reference_candidates(rows, wanted_name: str, reference_date: str, target_task: str):
    """A monitor-day search is NOT a production-day match (QAC 08:00 rollover)."""
    from .qac_html_collector import _norm
    return [r for r in _visible_task_rows(rows)
            if _norm(r.get('document_name') or '') == wanted_name
            and str(r.get('lot') or '').strip() == reference_date
            and str(r.get('task_id') or '').strip() != target_task
            and r.get('can_measure')]


async def discover_daily_slots(cdp_url: str, document: dict, progress=None):
    """Read selected task and read-only D-1 QAC results by exact document/item.

    D-1 lookup failure is not permission to fabricate a value. Always restore
    the user's current monitor day after read-only history navigation.
    """
    from datetime import date, timedelta
    from playwright.async_api import async_playwright
    from .qac_html_collector import _set_date, _wait_for_task_list, _norm
    log=progress or (lambda _:None)
    task_id=str(document.get('task_id') or '').strip()
    if not task_id: raise RuntimeError('Scan Task ID ก่อนเปิด Slot Configuration')
    task_date=str(document.get('found_date') or document.get('_daily_production_date') or '').strip()
    async with async_playwright() as pw:
      browser=await pw.chromium.connect_over_cdp(cdp_url)
      try:
        if not browser.contexts: raise RuntimeError('ไม่มี QAC Browser Context')
        context=browser.contexts[0]
        from .qac_session import require_owned_qac_page, is_trusted_qac_url
        module=None
        for candidate in context.pages:
          if candidate.is_closed() or not is_trusted_qac_url(candidate.url):
            continue
          try:
            if await candidate.evaluate('window.name||""')=='QAC_DAILY_DOCUMENT_MODULE':
              module=candidate
              break
          except Exception:
            continue
        if module is None:
          raise RuntimeError('QAC DAILY PAGE NOT FOUND | ต้องใช้แท็บ Daily ของโปรแกรมเท่านั้น')
        await require_owned_qac_page(module, tag='QAC_DAILY_DOCUMENT_MODULE',
                                     ready_selector='.calendar-monitor, tr[data-task]')
        if not any(str(x.get('task_id') or '')==task_id for x in _visible_task_rows(await _task_rows(module))):
          await _reuse_or_restore_task_list(module,task_date,log)
        pages_before=set(context.pages); measure=module
        try:
          await _click_measure_action(module,task_id,log)
          await module.wait_for_timeout(250)
          created=[x for x in context.pages if x not in pages_before]
          if created:measure=created[-1]
          await verify_daily_measure_identity(measure, document, log)
          schema=await extract_daily_slot_schema(measure)
          schema=await refresh_daily_results_by_activation(measure, schema, log, target_scan=True)
          # Populate the operator dialog with the actual target document values.
          # A result ID is evidence of persistence, not evidence of OK/NG.
          current_values=await _read_daily_existing_values(measure)
          by_existing={(str(v['item']), int(v['number'])):v for v in current_values}
          for item in schema:
            for slot in item['slots']:
              if not slot.get('saved'):continue
              v=by_existing.get((str(item['item']),int(slot['number'])))
              slot['current_value']=str(v.get('value') or '') if v else ''
              slot['current_value_readable']=bool(v and v.get('readable'))
          log(f'DAILY TARGET EXISTING READ | task={task_id} | saved={len(current_values)} | readable={sum(bool(v.get("readable")) for v in current_values)}')
          current_saved=sum(sum(bool(slot.get('saved')) for slot in item['slots']) for item in schema)
          current_unknown=sum(sum(slot.get('status')=='UNKNOWN' for slot in item['slots']) for item in schema)
          current_empty=sum(sum(slot.get('status')=='EMPTY' for slot in item['slots']) for item in schema)
          log(f'DAILY CURRENT RESULTS | task={task_id} | items={len(schema)} | saved_slots={current_saved} | empty_slots={current_empty} | unknown_slots={current_unknown}')
          if current_saved==0:
            log(f'DAILY ZERO SAVED EVIDENCE | task={task_id} | first_items={[(x["item"], [(z["number"],z["status"]) for z in x["slots"][:6]]) for x in schema[:2]]}')
          for item in schema:
            occupied=[f"{slot["number"]}:{slot.get("result_id") or "unknown"}" for slot in item['slots'] if slot.get('saved')]
            if occupied: log(f'DAILY CURRENT ITEM | item={item["item"]} | saved={",".join(occupied)}')
          if not schema:raise RuntimeError('ไม่พบรายการตรวจใน Measure HTML; ยกเลิกเพื่อป้องกันการลงผิด')
          log(f'DAILY HTML READ | task={task_id} | fields={len(schema)}')
          # Target checkpoint is independent of reference success/failure.
          try:
            from pathlib import Path as _Path
            from .daily_scan_checkpoint import DailyScanCheckpoint
            _checkpoints = DailyScanCheckpoint(_Path(__file__).resolve().parents[1] / 'database' / 'daily_scan_checkpoints.sqlite3')
            _checkpoints.save('TARGET', document, task_date, task_id, schema)
            log(f'DAILY TARGET CHECKPOINT SAVED | task={task_id} | items={len(schema)}')
          except (ValueError, OSError, TypeError) as checkpoint_exc:
            log(f'DAILY TARGET CHECKPOINT UNAVAILABLE | {checkpoint_exc}')
        finally:
          if measure is not module:
            await measure.close();await module.bring_to_front()
          else:
            await _return_to_check_sheet(module,log,task_id)

        # Optional explicit reference date: read its actual QAC Measure HTML,
        # never infer missing results or reuse another document's values.
        reference_date = str(document.get('_daily_reference_date') or '').strip()
        if reference_date:
          reference_error = None
          try:
            log(f'DAILY REFERENCE SEARCH | date={reference_date} | doc={document.get("document_name")}')
            wanted = _norm(document.get('document_name') or '')
            # Monitor is an 08:00-to-08:00 QAC window, NOT the same as data-lot.
            # Search the requested monitor, then its preceding monitor window.
            # Never accept the target task or another production date as a reference.
            from datetime import date as _date, timedelta as _timedelta
            monitor_days = [reference_date, (_date.fromisoformat(reference_date) - _timedelta(days=1)).isoformat()]
            matches = []
            for monitor_day in monitor_days:
              rows = await _reuse_or_restore_task_list(module, monitor_day, log)
              visible = _visible_task_rows(rows)
              matches = _reference_candidates(rows, wanted, reference_date, task_id)
              named = [r for r in visible if _norm(r.get('document_name') or '') == wanted]
              log(f'DAILY REFERENCE CANDIDATES | requested_date={reference_date} | monitor={monitor_day} | visible={len(visible)} | name_matches={len(named)} | exact_date_matches={len(matches)} | excluded_wrong_dates={[(r.get("task_id"), r.get("lot")) for r in named if r not in matches][:5]}')
              if matches:
                break
            if len(matches) == 1:
              log(f'DAILY REFERENCE TASK VERIFIED | task={matches[0].get("task_id")} | production_date={matches[0].get("lot")} | monitor={monitor_day}')
            if len(matches) != 1:
              log(f'DAILY REFERENCE NOT UNIQUE | date={reference_date} | matches={len(matches)} | available_named={sum(bool(r.get("document_name")) for r in visible)}')
              reference_error = f'Reference not unique: {len(matches)} matches on {reference_date}'
            else:
              ref_task = str(matches[0].get('task_id') or '')
              # Resume only an EXACT identity/date/task-bound verified reference.
              # Never resume today's Target from cache: preflight reads live QAC.
              cached_found = None
              try:
                from pathlib import Path as _Path
                from .daily_scan_checkpoint import DailyScanCheckpoint, verified_reference_values
                ref_document = dict(document)
                ref_document['_daily_production_date'] = reference_date
                ckpt = DailyScanCheckpoint(_Path(__file__).resolve().parents[1] / 'database' / 'daily_scan_checkpoints.sqlite3')
                old = ckpt.load('REFERENCE', ref_document, reference_date, ref_task)
                if old:
                  cached_found = verified_reference_values(old['items'])
                  log(f'DAILY REFERENCE CHECKPOINT RESUMED | task={ref_task} | date={reference_date} | values={len(cached_found)}')
              except (ValueError, OSError, TypeError) as exc:
                log(f'DAILY REFERENCE CHECKPOINT REJECTED | task={ref_task} | {exc}')
              if cached_found is not None:
                count = 0
                for field in schema:
                  for slot in field['slots']:
                    result = cached_found.get((str(field['item']), int(slot['number'])))
                    if not result or slot.get('saved') or slot.get('status') != 'EMPTY':
                      continue
                    value = str(result['value']).strip()
                    if field['format'] == '1':
                      try:
                        validate_qac_numeric_choice('VALUE:' + value)
                      except ValueError:
                        continue
                    elif value not in field['options']:
                      continue
                    slot.update(previous_value=value, previous_date=reference_date,
                                previous_result_id=result['result_id'], reference_source='QAC_MEASURE_CHECKPOINT')
                    count += 1
                log(f'DAILY REFERENCE LOADED | date={reference_date} | task={ref_task} | slots={count} | source=CHECKPOINT')
              else:
                before = set(context.pages)
                ref_page = module
                try:
                  await _open_reference_task(module, ref_task, log)
                  await module.wait_for_timeout(250)
                  spawned = [p for p in context.pages if p not in before]
                  if spawned: ref_page = spawned[-1]
                  # Reference uses exactly the same Measure identity and active-item
                  # reader as the target. Never read a View matrix or save snapshots.
                  reference_document = dict(document)
                  reference_document['_daily_production_date'] = reference_date
                  reference_document['_expected_production_date'] = reference_date
                  identity_verified = False
                  try:
                    await verify_daily_measure_identity(ref_page, reference_document, log)
                    identity_verified = True
                  except RuntimeError as exc:
                    log(f'DAILY REFERENCE IDENTITY MISMATCH | task={ref_task} | {exc}')
                    reference_error = f'Reference identity mismatch for task {ref_task}: {exc}'

                  if identity_verified:
                    reference_schema = await extract_daily_slot_schema(ref_page)
                    reference_schema = await refresh_daily_results_by_activation(
                        ref_page, reference_schema, log)
                    ref_items = await _read_daily_existing_values(ref_page)
                    found = {(str(x['item']), int(x['number'])): x for x in ref_items
                             if x.get('readable') and str(x.get('value') or '').strip()}
                    # Save reference independently before closing Measure: a QAC
                    # navigation failure must not discard previously verified values.
                    try:
                      from pathlib import Path as _Path
                      from .daily_scan_checkpoint import DailyScanCheckpoint
                      _checkpoints = DailyScanCheckpoint(_Path(__file__).resolve().parents[1] / 'database' / 'daily_scan_checkpoints.sqlite3')
                      _checkpoints.save('REFERENCE', reference_document, reference_date, ref_task, reference_schema)
                      log(f'DAILY REFERENCE CHECKPOINT SAVED | task={ref_task} | items={len(reference_schema)}')
                    except (ValueError, OSError, TypeError) as checkpoint_exc:
                      log(f'DAILY REFERENCE CHECKPOINT UNAVAILABLE | {checkpoint_exc}')
                    log(f'DAILY REFERENCE RESULT AUDIT | date={reference_date} | '
                        f'task={ref_task} | items={len(reference_schema)} | '
                        f'total_saved={len(ref_items)} | readable={len(found)} | '
                        f'unreadable={len(ref_items) - len(found)}')
                    count = 0
                    for field in schema:
                      for slot in field['slots']:
                        result = found.get((str(field['item']), int(slot['number'])))
                        if not result or slot.get('saved') or slot.get('status') != 'EMPTY':
                          continue
                        value = str(result['value']).strip()
                        if not value:
                          continue
                        if field['format'] == '1':
                          try:
                            validate_qac_numeric_choice('VALUE:' + value)
                          except ValueError:
                            log(f'DAILY REFERENCE INVALID NUMBER | item={field["item"]} '
                                f'| slot={slot["number"]} | no copy')
                            continue
                        elif value not in field['options']:
                          continue
                        slot['previous_value'] = value
                        slot['previous_date'] = reference_date
                        slot['previous_result_id'] = result.get('result_id') or ''
                        slot['reference_source'] = 'QAC_MEASURE'
                        count += 1
                    log(f'DAILY REFERENCE LOADED | date={reference_date} | '
                        f'task={ref_task} | slots={count} | source=QAC_MEASURE | '
                        'no snapshots')
                finally:
                  if ref_page is not module:
                    await ref_page.close()
                    await module.bring_to_front()
                  else:
                    await _return_to_check_sheet(module, log, ref_task)
          except Exception as exc:
            log(f'DAILY REFERENCE ERROR | date={reference_date} | {type(exc).__name__}: {exc}')
            reference_error = f'{type(exc).__name__}: {exc}'
          finally:
            try:
              if task_date:
                if monitor_days and monitor_day != task_date:
                  from datetime import date as _date, timedelta as _timedelta
                  cursor = _date.fromisoformat(monitor_day)
                  dest = _date.fromisoformat(task_date)
                  while abs((dest - cursor).days) > 1:
                    cursor += _timedelta(days=1 if dest > cursor else -1)
                    await _reuse_or_restore_task_list(module, cursor.isoformat(), log)
                await _reuse_or_restore_task_list(module, task_date, log)
            except Exception as exc:
              log(f'DAILY REFERENCE RESTORE ERROR | {exc}')
              reference_error = f'Reference restore failure: {exc}'
          if reference_error:
            # Reference is optional input for proposing values, never a prerequisite
            # for a user-authored manual slot plan. Never transfer unverified values.
            # The target's live saved-slot interlocks remain active at registration.
            for field in schema:
              for slot in field['slots']:
                for key in ('previous_value', 'previous_date', 'previous_result_id',
                            'reference_source'):
                  slot.pop(key, None)
            log(f'DAILY REFERENCE UNAVAILABLE | {reference_error} | '
                'Reference values NOT applied; manual slot selection only')
            log('DAILY MANUAL PLAN READY | reference unavailable | '
                'target saved-slot interlocks remain enabled')

        # Fast path: no historical QAC navigation. Latest confirmed values are
        # loaded from SQLite and validated against this live HTML schema.
        try:
          from .daily_latest_memory import DailyLatestMemory
          from pathlib import Path
          db=DailyLatestMemory(Path(__file__).resolve().parents[1] / 'database' / 'daily_latest.sqlite3')
          remembered={} if reference_date else db.read(document)
          loaded=0
          for item in schema:
            for slot in item['slots']:
              record=remembered.get((str(item['item']),int(slot['number'])))
              if record and not slot['saved']:
                value=str(record['value'])
                if item['format']=='1' or value in item['options']:
                  slot['previous_value']=value
                  slot['previous_result_id']=record['result_id']
                  slot['previous_date']=record['confirmed_at']
                  loaded+=1
          log(f'DAILY LATEST CACHE | loaded={loaded} | document={document.get("document_name")}')
        except ValueError as exc:
          log(f'DAILY LATEST CACHE DISABLED | {exc}')
        except Exception as exc:
          log(f'DAILY LATEST CACHE ERROR | {type(exc).__name__}: {str(exc)[:180]}')
        return schema
      finally:await browser.close()


def validate_qac_numeric_choice(choice: str) -> str:
    """Validate a finite decimal, preserving sign and trailing zeros exactly."""
    if not isinstance(choice, str) or not choice.startswith('VALUE:'):
        raise ValueError('Numeric result must use VALUE:<decimal>')
    raw = choice[6:]
    if not raw or raw != raw.strip() or any(c.isspace() for c in raw):
        raise ValueError('Numeric value is empty or contains whitespace')
    import re
    if not re.fullmatch(r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)', raw):
        raise ValueError(f'Invalid numeric value: {raw!r}')
    try:
        number = Decimal(raw)
    except InvalidOperation as exc:
        raise ValueError('Invalid decimal value') from exc
    if not number.is_finite():
        raise ValueError('NaN/Infinity are invalid QAC values')
    return raw


def _is_valid_numeric_choice(value: str) -> bool:
    try:
        validate_qac_numeric_choice(value)
        return True
    except ValueError:
        return False


def validate_daily_slot_plan(schema: list[dict], plan: dict) -> None:
    """Reject unknown, occupied or non-sequential selections before any QAC writes."""
    if not isinstance(plan, dict) or not plan:
        raise ValueError('กรุณาเลือก Slot ก่อนลงทะเบียน')
    items={str(f['item']):f for f in schema}
    for item_id, selection in plan.items():
        item=items.get(str(item_id))
        if item is None:
            raise ValueError(f'Item {item_id} ไม่มีใน HTML ปัจจุบัน')
        if not isinstance(selection,dict) or not selection:
            raise ValueError(f'Item {item_id} ไม่มี Slot ที่เลือก')
        # Slot keys are absolute QAC slot numbers, never a count of pending results.
        for slot, value in selection.items():
            try:slot_no=int(slot)
            except (TypeError,ValueError) as exc:raise ValueError(f'Invalid slot {slot}') from exc
            if slot_no not in [int(v['number']) for v in item['slots']]:raise ValueError(f'Item {item_id} Slot {slot_no} ไม่มีใน HTML')
            if value not in item['options'] and not (
                item['format']=='1' and isinstance(value,str) and
                _is_valid_numeric_choice(value)
            ):
                raise ValueError(f'Item {item_id} Slot {slot_no} มีชนิดผลตรวจไม่ตรง HTML')

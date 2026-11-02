from __future__ import annotations

import asyncio
from time import perf_counter
from typing import Callable
from .qac_interaction import interaction_checkpoint, install_native_dialog_guard

from .qac_html_collector import (
    _click_measure_action,
    _return_to_check_sheet,
    _reuse_or_restore_task_list,
    _wait_qac_complete,
)


def qac_numeric_values_equal(requested: str, displayed: str) -> bool:
    """QAC normalizes .51 to 0.5100 after blur; compare Decimal values, not text.

    Preserve the exact requested text separately for audit and memory. Never
    accept NaN, infinity, missing values, or a value that changes numerically.
    """
    from decimal import Decimal, InvalidOperation
    try:
        left, right = Decimal(str(requested).strip()), Decimal(str(displayed).strip())
        return left.is_finite() and right.is_finite() and left == right
    except (InvalidOperation, ValueError, TypeError):
        return False


def numeric_html_constraint(value: str, minimum: str | None, maximum: str | None,
                            step: str | None) -> str | None:
    """Diagnose native HTML number validity without modifying QAC constraints.

    An absent step defaults to 1 and uses min (or zero) as its step base.
    Returns a reason or None. This does not authorize saving a result.
    """
    from decimal import Decimal, InvalidOperation
    try:
        number = Decimal(str(value))
        lo = Decimal(str(minimum)) if minimum not in (None, '') else None
        hi = Decimal(str(maximum)) if maximum not in (None, '') else None
        if not number.is_finite():
            return 'NON_FINITE'
        if lo is not None and number < lo:
            return 'RANGE_UNDERFLOW'
        if hi is not None and number > hi:
            return 'RANGE_OVERFLOW'
        if step == 'any':
            return None
        increment = Decimal(str(step)) if step not in (None, '') else Decimal('1')
        if increment <= 0:
            increment = Decimal('1')
        if (number - (lo if lo is not None else Decimal('0'))) % increment != 0:
            return 'STEP_MISMATCH'
    except (InvalidOperation, ValueError, TypeError):
        return 'INVALID_NUMBER'
    return None


async def _wait_control(control) -> None:
    if control is None:
        return
    while control.pause_event.is_set() and not control.stop_event.is_set():
        await asyncio.sleep(0.15)
    if control.stop_event.is_set():
        raise InterruptedError("ผู้ใช้สั่งหยุด Daily Document Register")


from .qac_measure_actions import (
    _click_if_visible, _click_save,
)

async def _wait_daily_slot_persisted(page, item_id: str, number: int, *,
                                     progress=None, control=None, timeout_seconds=25) -> str:
    """Verify that QAC displays a persisted row, even when the Result ID is absent.

    QAC Trace shows saved categorical rows with data-empty=false and visible
    OK/NG text, but no data-result attribute.  Never infer success from a popup.
    """
    from .daily_slot_schema import extract_daily_slot_schema
    deadline = asyncio.get_running_loop().time() + timeout_seconds
    while True:
        await _wait_control(control)
        from .daily_slot_schema import extract_daily_item_schema
        field = await extract_daily_item_schema(page, str(item_id))
        slot = next((x for x in field['slots'] if int(x['number']) == number), None) if field else None
        if slot and slot['status'] == 'SAVED':
            return str(slot.get('result_id') or '')
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(f'DAILY SAVE UNVERIFIED | item={item_id} slot={number} '
                               f'| no persisted QAC row after {timeout_seconds}s; STOP, do not retry write')
        await asyncio.sleep(0.5)


async def _fresh_qac_numeric_readback(page, document: dict, production_date: str,
                                      item_id: str, number: int, expected: str,
                                      progress, control=None) -> str:
    """Read-only verification on a NEW Measure instance after QAC's Save ACK.

    QAC may retain a staged row (data-empty=true) in the original DOM even
    after its save dialog completes. Never infer persistence from that popup
    or the staged input. Reopen the exact Task and verify the server-loaded row.
    """
    from .daily_slot_schema import extract_daily_item_schema, verify_daily_measure_identity
    task = str(document.get('task_id') or '')
    if not task:
        raise RuntimeError('DAILY READBACK NO TASK ID | cannot verify numeric write')
    progress(f'DAILY NUMERIC SERVER READBACK | item={item_id} slot={number} task={task} | reopen Measure read-only')
    await _return_to_check_sheet(page, progress, task)
    await _wait_control(control)
    await _click_measure_action(page, task, progress)
    await _wait_qac_complete(page, progress, 'Numeric saved result readback',
                             ready_selector='.fieldset[data-item], .f1-step[data-item]')
    await verify_daily_measure_identity(page, dict(document, _daily_production_date=production_date), progress)
    fieldset = page.locator(f'.fieldset[data-item="{item_id}"]').first
    if await fieldset.count() != 1:
        raise RuntimeError(f'DAILY READBACK ITEM MISSING | item={item_id}')
    await _activate_daily_item(page, fieldset, item_id, progress, control=control)
    # Read the fresh server-loaded result after its item has become active.
    deadline = asyncio.get_running_loop().time() + 12
    while True:
        await _wait_control(control)
        field = await extract_daily_item_schema(page, item_id)
        slot = next((x for x in field['slots'] if int(x['number']) == number), None) if field else None
        if slot and slot['status'] == 'SAVED':
            actual = str(slot.get('value') or '')
            if not qac_numeric_values_equal(expected, actual):
                raise RuntimeError(f'DAILY READBACK VALUE CONFLICT | item={item_id} slot={number} expected={expected} actual={actual}')
            progress(f'DAILY NUMERIC SERVER VERIFIED | item={item_id} slot={number} value={actual}')
            return str(slot.get('result_id') or '')
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(f'DAILY SAVE UNVERIFIED | item={item_id} slot={number} | fresh Measure result not SAVED; STOP, do not retry write')
        await asyncio.sleep(0.3)


async def _daily_click_diagnostics(page, fieldset, item_id: str, number: int, selector: str, error: str) -> str:
    """Read-only click evidence; do not perform speculative retries or writes."""
    try:
        info = await page.evaluate("""({item, selector}) => {
          const field = [...document.querySelectorAll('.fieldset[data-item]')]
            .find(e => e.getAttribute('data-item') === item);
          const describe = e => ({tag:e.tagName, cls:String(e.className).slice(0,140),
            text:(e.textContent||'').trim().slice(0,80), disabled:!!e.disabled,
            visible:!!e.getClientRects().length && getComputedStyle(e).visibility!=='hidden',
            outer:e.outerHTML.slice(0,350)});
          return {url:location.href, fieldFound:!!field,
            fieldVisible:!!field?.getClientRects().length,
            candidateButtons:[...(field?.querySelectorAll('button,a,input[type=button]')||[])].slice(0,24).map(describe),
            matchingInField:field?[...field.querySelectorAll(selector)].length:0,
            matchingOnPage:[...document.querySelectorAll(selector)].length};
        }""", {'item':str(item_id), 'selector':selector})
        return f'DAILY CLICK DIAGNOSTIC | item={item_id} slot={number} | reason={error} | dom={str(info)[:3500]}'
    except Exception as exc:
        return f'DAILY CLICK DIAGNOSTIC | item={item_id} slot={number} | reason={error} | inspection_error={type(exc).__name__}: {exc}'


async def _daily_click_or_raise(page, fieldset, selector: str, item_id: str, number: int, progress) -> None:
    """Click only QAC's currently displayed item control; never insert slots or force a hidden button."""
    active_selector = ', '.join(x.strip() + ':visible:not([disabled])' for x in selector.split(','))
    # The Measure page animates between fieldsets. A visible fieldset can precede
    # its actionable buttons, which made the previous immediate count() return 0.
    # Don't select a hidden template in .ul1/.ul2, or a control for another item.
    try:
        await fieldset.locator(active_selector).first.wait_for(state='visible', timeout=12000)
    except Exception as exc:
        detail = await _daily_click_diagnostics(page, fieldset, item_id, number, selector,
                                                 'QAC item action not visible after 12s')
        if progress: progress(detail)
        raise RuntimeError(f'DAILY ITEM NOT READY | item={item_id} slot={number} | OK/NG not visible; STOP without writing') from exc
    candidates = fieldset.locator(active_selector)
    count = await candidates.count()
    if count != 1:
        detail = await _daily_click_diagnostics(page, fieldset, item_id, number, selector,
                                                 f'actionable buttons in item={count}')
        if progress: progress(detail)
        raise RuntimeError(f'DAILY CLICK AMBIGUOUS | item={item_id} slot={number} actionable={count}')
    if progress: progress(f'DAILY CLICK TARGET | item={item_id} slot={number} | scope=active-item selector={selector}')
    try:
        await candidates.first.click(timeout=10000)
    except Exception as exc:
        if progress: progress(await _daily_click_diagnostics(page, fieldset, item_id, number, selector,
                                                          f'{type(exc).__name__}: {str(exc)[:250]}'))
        raise RuntimeError(f'DAILY CLICK FAILED | item={item_id} slot={number} | {type(exc).__name__}: {str(exc)[:350]}') from exc


async def _read_live_item_controls(fieldset) -> dict:
    """Cheap, read-only DOM snapshot of the ACTIVE inspection, never whole-page HTML."""
    return await fieldset.evaluate("""root => {
      const shown = el => {
        if (!el || !el.isConnected || el.disabled) return false;
        const css = getComputedStyle(el), rect = el.getBoundingClientRect();
        return css.display !== 'none' && css.visibility !== 'hidden' &&
          Number(css.opacity) > 0 && rect.width > 0 && rect.height > 0;
      };
      const buttons = s => [...root.querySelectorAll(s)].filter(shown);
      const results = [...root.querySelectorAll('tr[data-result-no]')].map(tr => ({
        slot: Number(tr.getAttribute('data-result-no')),
        text: (tr.innerText || '').trim().slice(0, 120),
        input: tr.querySelector('input[data-result-no], textarea[data-result-no]')?.value || '',
        empty: tr.getAttribute('data-empty')
      }));
      return {
        item: root.getAttribute('data-item'),
        visible: shown(root),
        save: buttons('.btn-save, .btn-save-text').length,
        ok: buttons('.btn-ok, .btn-ok-pd').length,
        ng: buttons('.btn-ng, .btn-ng-pd').length,
        results
      };
    }""")


async def _inspect_after_slot(fieldset, *, item_id: str, slot_no: int,
                              remaining: int, progress, control=None, numeric=False) -> dict:
    """After EACH entry, observe QAC's actual next action, not a fixed step schedule.

    Save availability does not authorize early Save while operator-selected slots
    are still pending. The caller must first finish and verify its planned inputs.
    """
    deadline = asyncio.get_running_loop().time() + 6.0
    last = None
    while True:
        await _wait_control(control)
        state = await _read_live_item_controls(fieldset)
        last = state
        if not state['visible'] or str(state['item']) != str(item_id):
            raise RuntimeError(f'DAILY ITEM LOST | item={item_id} slot={slot_no}')
        if state['save'] > 1:
            raise RuntimeError(f'DAILY SAVE AMBIGUOUS | item={item_id} buttons={state["save"]}')
        if remaining:
            # Numeric fields expose no OK/NG buttons; the next numbered input is
            # already a valid next action after confirming the value was entered.
            if numeric or state['ok'] or state['ng'] or state['save']:
                progress(f'DAILY HTML STATE | item={item_id} slot={slot_no} '
                         f'save={state["save"]} ok={state["ok"]} ng={state["ng"]} '
                         f'next=CHECK_NEXT_SLOT remaining={remaining}')
                return state
        elif state['save'] == 1:
            progress(f'DAILY HTML STATE | item={item_id} slot={slot_no} '
                     f'save=1 next=SAVE')
            return state
        if asyncio.get_running_loop().time() >= deadline:
            raise RuntimeError(f'DAILY STATE UNREADY | item={item_id} slot={slot_no} '
                               f'remaining={remaining} state={str(last)[:500]}')
        await asyncio.sleep(0.15)


async def _qac_active_item_id(page) -> str | None:
    """Observe QAC navigation; never infer active item from planned sequence."""
    return await page.evaluate("""() => {
      const shown = el => !!el && getComputedStyle(el).display !== 'none' &&
        getComputedStyle(el).visibility !== 'hidden' && el.getClientRects().length > 0;
      const active = [...document.querySelectorAll('.fieldset[data-item]')].filter(shown);
      return active.length === 1 ? active[0].getAttribute('data-item') : null;
    }""")


def decide_daily_navigation(active: str | None, expected: str) -> str:
    """Auto-next, manual-next, or ambiguous; item ID is mandatory."""
    if active is None:
        return 'UNKNOWN'
    return 'AUTO_NEXT' if str(active) == str(expected) else 'MANUAL_NEXT'


async def _verify_numeric_batch_readonly(page, document, production_date, expected, progress, control=None):
    """Read back numeric ACKs inside the SAME Measure page, without leaving it.

    QAC populates saved result rows upon item activation. An unverified result
    is not proof of failure: stop without submitting or re-submitting anything.
    """
    from .daily_slot_schema import extract_daily_item_schema, verify_daily_measure_identity
    task = str(document.get('task_id') or '')
    if not task:
        raise RuntimeError('DAILY BATCH VERIFY NO TASK ID')
    progress(f'DAILY NUMERIC BATCH VERIFY START | task={task} slots={len(expected)} mode=SAME_MEASURE')
    await verify_daily_measure_identity(page, dict(document, _daily_production_date=production_date), progress)
    verified = []
    for item, slot_no, value in expected:
        await _wait_control(control)
        fieldset = page.locator(f'.fieldset[data-item="{item}"]').first
        if await fieldset.count() != 1:
            raise RuntimeError(f'DAILY BATCH VERIFY ITEM MISSING | item={item}')
        # QAC only populates authoritative results when the item is selected.
        # Activation is read-only and must never issue Enter/Save.
        await _activate_daily_item(page, fieldset, str(item), progress, control=control)
        deadline = asyncio.get_running_loop().time() + 8.0
        row = None
        while True:
            await _wait_control(control)
            field = await extract_daily_item_schema(page, str(item))
            row = next((x for x in field['slots'] if int(x['number']) == slot_no), None) if field else None
            if row and row['status'] == 'SAVED':
                break
            if asyncio.get_running_loop().time() >= deadline:
                observed = row['status'] if row else 'MISSING'
                raise RuntimeError(f'DAILY SAVE UNVERIFIED | item={item} slot={slot_no} '
                                   f'| same Measure readback state={observed}; no repeat write')
            await asyncio.sleep(0.2)
        actual = str(row.get('value') or '')
        if not qac_numeric_values_equal(value, actual):
            raise RuntimeError(f'DAILY READBACK VALUE CONFLICT | item={item} slot={slot_no} expected={value} actual={actual}')
        verified.append((item, slot_no, value, str(row.get('result_id') or '')))
        progress(f'DAILY NUMERIC BATCH VERIFIED | item={item} slot={slot_no} value={actual}')
    progress(f'DAILY NUMERIC BATCH VERIFY DONE | verified={len(verified)} mode=SAME_MEASURE')
    return verified


async def _activate_daily_item(page, fieldset, item_id: str, progress, *,
                               expected_action: str | None = None, control=None) -> None:
    """Activate an item and check its actual actionable control, not only its frame.

    QAC's fieldset can be visible while the outgoing/incoming item controls are
    display:none. This guard never clicks or changes the QAC form while waiting.
    """
    active = await _qac_active_item_id(page)
    mode = decide_daily_navigation(active, str(item_id))
    if mode != 'AUTO_NEXT':
        step = page.locator(f'.f1-step[data-item="{item_id}"]').first
        await step.click(timeout=12000)
    if progress:
        progress(f'DAILY NAVIGATION | expected={item_id} observed={active or "UNKNOWN"} mode={mode} click={int(mode != "AUTO_NEXT")}')
    await fieldset.wait_for(state='visible', timeout=12000)
    if expected_action:
        deadline = asyncio.get_running_loop().time() + 12.0
        while True:
            await _wait_control(control)
            state = await fieldset.evaluate("""(root, selector) => {
              const shown = el => {
                if (!el || !el.isConnected || el.disabled) return false;
                const css = getComputedStyle(el), rect = el.getBoundingClientRect();
                return css.display !== 'none' && css.visibility !== 'hidden' &&
                  Number(css.opacity) > 0 && rect.width > 0 && rect.height > 0;
              };
              const visible = shown(root);
              const buttons = [...root.querySelectorAll(selector)].filter(shown);
              return {item:root.getAttribute('data-item'), visible, actionCount:buttons.length};
            }""", expected_action)
            if str(state.get('item')) != str(item_id):
                raise RuntimeError(f'DAILY ITEM IDENTITY CHANGED | expected={item_id} actual={state.get("item")}')
            if state.get('visible') and state.get('actionCount') == 1:
                break
            if state.get('actionCount', 0) > 1:
                raise RuntimeError(f'DAILY ITEM ACTION AMBIGUOUS | item={item_id}')
            if asyncio.get_running_loop().time() >= deadline:
                if progress:
                    progress(await _daily_click_diagnostics(page, fieldset, item_id, 1,
                        expected_action, 'activate item action not visible after 12s'))
                raise RuntimeError(f'DAILY ITEM NOT READY | item={item_id} action not visible; STOP without writing')
            await asyncio.sleep(0.15)
    if progress: progress(f'DAILY ITEM ACTIVE | item={item_id} | action controls ready')


async def _register_ok_on_measure_page(
    page, *, document=None, production_date='', settings=None, dry_run=False,
    progress, control=None,
):
    """Read current QAC slots; skip existing; stage all selections for one item then save once."""
    from .daily_slot_schema import extract_daily_slot_schema, validate_daily_slot_plan
    plan = (document or {}).get('_daily_slot_plan')
    if not isinstance(plan, dict):
        raise RuntimeError('DAILY SLOT PLAN MISSING | ต้องอ่าน HTML และเลือก Slot ก่อน Register')
    from .daily_slot_schema import verify_daily_measure_identity
    await verify_daily_measure_identity(page, dict(document or {}, _daily_production_date=production_date), progress)
    schema = await extract_daily_slot_schema(page)
    validate_daily_slot_plan(schema, plan)
    by_item = {str(field['item']): field for field in schema}
    requested = [(str(item), int(slot), str(value)) for item, slots in plan.items()
                 for slot, value in slots.items() if str(value or '').strip()]
    uncertain = [(item, slot) for item, slot, _ in requested
                 if next(s for s in by_item[item]['slots'] if int(s['number']) == slot)['status'] == 'UNKNOWN']
    if uncertain:
        raise RuntimeError(f'DAILY PREFLIGHT UNKNOWN | cannot safely write slots {uncertain[:12]}')
    existing = [(item, slot) for item, slot, _ in requested
                if next(s for s in by_item[item]['slots'] if int(s['number']) == slot)['saved']]
    # Native HTML min/step can disagree with QAC's own measurement limits.
    # Validate number syntax before writing, but let the authorized QAC UI
    # decide whether a staged value is accepted after its blur/change handler.
    from .daily_slot_schema import validate_qac_numeric_choice
    for item, slot, value in requested:
        if by_item[item]['format'] == '1' and (item, slot) not in existing:
            validate_qac_numeric_choice(value)
    progress('DAILY NUMERIC PREFLIGHT | syntax verified; QAC UI acceptance checked after Enter/Inspector trigger')
    progress(f'DAILY REGISTER PREFLIGHT | planned={len(requested)} already_saved={len(existing)} pending={len(requested)-len(existing)}')
    if len(existing) == len(requested):
        progress('DAILY REGISTER EXIT | all requested slots already saved; no QAC write')
        return {'fields':len(schema),'done':0,'skipped':len(existing),'would_fill':0,
                'saved':0,'errors':0,'numeric_missing':0,'history_references':0}

    done = skipped = saved = 0
    deferred_numeric = []
    for item_id, choices in plan.items():
        await _wait_control(control)
        field = by_item.get(str(item_id))
        if field is None:
            raise RuntimeError(f'DAILY HTML CHANGED | item={item_id} not found')
        item_started = perf_counter()
        fieldset = page.locator(f'.fieldset[data-item="{item_id}"]').first
        # Item-level preflight, never trust a stale dialog schema.
        from .daily_slot_schema import extract_daily_item_schema
        current = await extract_daily_item_schema(page, str(item_id))
        if current is None or current['format'] != field['format']:
            raise RuntimeError(f'DAILY PREFLIGHT CHANGED | item={item_id}')
        selected = sorted(((int(n), str(v or '').strip()) for n, v in choices.items() if str(v or '').strip()))
        slots = {int(s['number']):s for s in current['slots']}
        if any(n not in slots for n, _ in selected):
            raise RuntimeError(f'DAILY PREFLIGHT CHANGED | item={item_id} slot count changed')
        if any(slots[n]['status'] == 'UNKNOWN' for n,_ in selected):
            raise RuntimeError(f'DAILY ITEM UNKNOWN | item={item_id}; STOP rather than overwrite')
        pending = [(n,v) for n,v in selected if not slots[n]['saved']]
        for n, _ in selected:
            if slots[n]['saved']:
                skipped += 1
                progress(f'DAILY ALREADY SAVED | item={item_id} slot={n} result={slots[n].get("result_id")}; skip write')
        if not pending:
            progress(f'DAILY ITEM PERF | item={item_id} action=SKIP elapsed_ms={int((perf_counter()-item_started)*1000)}')
            continue
        empty = [int(s['number']) for s in current['slots'] if not s['saved']]
        if [n for n, _ in pending] != empty[:len(pending)]:
            raise RuntimeError(f'DAILY SLOT ORDER | item={item_id} requested={[n for n,_ in pending]} next={empty[:len(pending)]}')
        progress(f'DAILY ITEM STAGE | item={item_id} slots={len(pending)} format={field["format"]}')
        if dry_run:
            continue
        first_selection = pending[0][1]
        expected_action = (
            ('.btn-ok, .btn-ok-pd' if first_selection == 'OK' else '.btn-ng, .btn-ng-pd')
            if field['format'] == '4' else
            {'Initial':'.btn-initial', 'Middle':'.btn-middle', 'Final':'.btn-final'}.get(first_selection)
            if field['format'] == '3' else None
        )
        await _activate_daily_item(page, fieldset, str(item_id), progress,
                                   expected_action=expected_action, control=control)
        numeric_enter_confirmed = False
        for position, (number, selection) in enumerate(pending):
            await _wait_control(control)
            if selection not in field['options'] and not (field['format']=='1' and selection.startswith('VALUE:')):
                raise RuntimeError(f'DAILY TYPE INVALID | item={item_id} slot={number} choice={selection}')
            progress(f'DAILY SLOT SELECT | item={item_id} slot={number} choice={selection}')
            if field['format'] == '4':
                selector = '.btn-ok, .btn-ok-pd' if selection == 'OK' else '.btn-ng, .btn-ng-pd'
                await _daily_click_or_raise(page, fieldset, selector, str(item_id), number, progress)
            elif field['format'] == '3':
                selector = {'Initial':'.btn-initial', 'Middle':'.btn-middle', 'Final':'.btn-final'}[selection]
                await _daily_click_or_raise(page, fieldset, selector, str(item_id), number, progress)
            elif field['format'] == '1':
                from .daily_slot_schema import validate_qac_numeric_choice
                validate_qac_numeric_choice(selection)
                target = fieldset.locator(f'input[data-result-no="{number}"]:not([disabled])').first
                # User-observed QAC workflow: enter numeric value, then leave
                # the textbox; QAC's event handlers expose Save afterwards.
                # Never alter min/max/step attributes or click a hidden Save.
                await target.click()
                await target.fill(selection[6:])
                # Enter must be dispatched while the actual QAC numeric textbox
                # owns focus. Do not blur immediately: a blur handler may alter
                # the field before QAC's keyup/keypress processing completes.
                await target.focus()
                focus_state = await target.evaluate('el => document.activeElement === el')
                if not focus_state:
                    raise RuntimeError(f'DAILY NUMERIC FOCUS LOST | item={item_id} slot={number}')
                await page.keyboard.press('Enter')
                progress(f'DAILY NUMERIC ENTER | item={item_id} slot={number} | focus_verified=1')
                # Observe the popup/control transition before doing anything else.
                # An Enter-triggered confirmation is a QAC operation: it must
                # not be followed by another Save click.
                from .qac_interaction import inspect_visible_qac_modal
                enter_deadline = asyncio.get_running_loop().time() + 5.0
                live_after_enter = {'save': 0}
                while True:
                    modal_after_enter = await inspect_visible_qac_modal(page)
                    if modal_after_enter.kind != 'NONE':
                        break
                    live_after_enter = await _read_live_item_controls(fieldset)
                    if live_after_enter['save']:
                        break
                    if asyncio.get_running_loop().time() >= enter_deadline:
                        break
                    await asyncio.sleep(0.1)
                progress(f'DAILY NUMERIC ENTER RESULT | item={item_id} slot={number} '
                         f'modal={modal_after_enter.kind} save={live_after_enter["save"]}')
                # Some QAC documents wire the change handler to the inspector
                # text box receiving focus rather than to Enter. Only use this
                # fallback when Enter did not create any modal OR Save state.
                # Never trigger it after an ACK, unknown popup or navigation.
                if modal_after_enter.kind == 'NONE' and not live_after_enter['save']:
                    active_before_fallback = await _qac_active_item_id(page)
                    if active_before_fallback != str(item_id):
                        raise RuntimeError(
                            f'DAILY NUMERIC NAVIGATED WITHOUT ACK | item={item_id} '
                            f'active={active_before_fallback}; STOP, no repeat trigger')
                    inspector = fieldset.locator('input.textbox-inspector:visible:not([disabled])')
                    inspector_count = await inspector.count()
                    if inspector_count != 1:
                        raise RuntimeError(
                            f'DAILY NUMERIC INSPECTOR UNAVAILABLE | item={item_id} '
                            f'inspectors={inspector_count}; STOP')
                    progress(f'DAILY NUMERIC INSPECTOR FALLBACK | item={item_id} slot={number} | Enter produced no modal/save')
                    await inspector.first.click(timeout=5000)
                    fallback_deadline = asyncio.get_running_loop().time() + 5.0
                    while True:
                        modal_after_enter = await inspect_visible_qac_modal(page)
                        if modal_after_enter.kind != 'NONE':
                            break
                        live_after_enter = await _read_live_item_controls(fieldset)
                        if live_after_enter['save']:
                            break
                        if asyncio.get_running_loop().time() >= fallback_deadline:
                            raise RuntimeError(
                                f'DAILY NUMERIC NO CONFIRM AFTER INSPECTOR | item={item_id} '
                                f'slot={number}; STOP without re-triggering')
                        await asyncio.sleep(0.1)
                    progress(f'DAILY NUMERIC INSPECTOR RESULT | item={item_id} slot={number} '
                             f'modal={modal_after_enter.kind} save={live_after_enter["save"]}')
                browser_check = await target.evaluate("""el => ({
                  value:el.value, valid:el.checkValidity(),
                  badInput:el.validity.badInput, rangeUnderflow:el.validity.rangeUnderflow,
                  rangeOverflow:el.validity.rangeOverflow,
                  stepMismatch:el.validity.stepMismatch,
                  min:el.getAttribute('min'), max:el.getAttribute('max'),
                  step:el.getAttribute('step')
                })""")
                if not qac_numeric_values_equal(selection[6:], browser_check['value']) or browser_check['badInput']:
                    raise RuntimeError(f'DAILY NUMERIC INPUT MISMATCH | item={item_id} '
                                       f'slot={number} value={selection[6:]} input={browser_check}')
                if browser_check['value'] != selection[6:]:
                    progress(f'DAILY NUMERIC NORMALIZED | item={item_id} slot={number} requested={selection[6:]} displayed={browser_check["value"]}')
                if not browser_check['valid']:
                    progress(f'DAILY NUMERIC NATIVE CONSTRAINT | item={item_id} '
                             f'slot={number} browser={browser_check} | '
                             'observe QAC Save state; do not modify input attributes')
            else:
                raise RuntimeError(f'DAILY UNSUPPORTED FORMAT | item={item_id}')
            # Some QAC Numeric builds open the Save confirmation directly on
            # Enter. Never click Save a second time after such a confirmation.
            if field['format'] == '1':
                from .qac_interaction import inspect_visible_qac_modal, acknowledge_visible_modal
                modal = await inspect_visible_qac_modal(page)
                # The QAC SweetAlert may briefly replace CONFIRM with an empty
                # transition shell between browser requests. If Enter already
                # observed CONFIRM, recheck the dialog (read-only) rather than
                # treating a single UNKNOWN sample as a failed submission.
                if modal_after_enter.kind == 'CONFIRM' and modal.kind in ('UNKNOWN', 'NONE', 'BUSY'):
                    deadline = asyncio.get_running_loop().time() + 2.0
                    while modal.kind in ('UNKNOWN', 'NONE', 'BUSY') and asyncio.get_running_loop().time() < deadline:
                        await asyncio.sleep(0.10)
                        modal = await inspect_visible_qac_modal(page)
                    progress(f'DAILY NUMERIC CONFIRM RESAMPLE | item={item_id} slot={number} '
                             f'initial={modal_after_enter.kind} current={modal.kind}')
                    if modal.kind != 'CONFIRM':
                        raise RuntimeError(f'DAILY NUMERIC CONFIRM LOST | item={item_id} slot={number} '
                                           f'current={modal.kind}; STOP on Measure, do not trigger another Save')
                if modal.kind == 'CONFIRM':
                    label = (modal.title or modal.content or '').casefold()
                    if 'save' not in label and 'บันทึก' not in label:
                        raise RuntimeError(f'DAILY NUMERIC UNEXPECTED CONFIRM | item={item_id} slot={number} title={label[:120]}')
                    if position != len(pending) - 1:
                        raise RuntimeError(f'DAILY NUMERIC EARLY CONFIRM | item={item_id} slot={number}; multiple slots pending; STOP without confirming')
                    progress(f'DAILY NUMERIC ENTER CONFIRM | item={item_id} slot={number} | confirming QAC Save dialog')
                    await acknowledge_visible_modal(page, progress, wait_ms=450, max_rounds=4)
                    numeric_enter_confirmed = True
                    break
                if modal.kind in ('ERROR', 'WARNING', 'UNKNOWN'):
                    raise RuntimeError(f'DAILY NUMERIC MODAL {modal.kind} | item={item_id} slot={number}; STOP')
            live_action = await _inspect_after_slot(
                fieldset, item_id=str(item_id), slot_no=number,
                remaining=len(pending)-position-1, progress=progress, control=control,
                numeric=field['format'] == '1')
            if field['format'] == '1':
                matching = [r for r in live_action['results'] if r['slot'] == number]
                if len(matching) != 1 or not qac_numeric_values_equal(selection[6:], matching[0]['input']):
                    raise RuntimeError(f'DAILY NUMERIC INPUT MISMATCH | item={item_id} slot={number}')
        # Save once per item ONLY when QAC exposes Save after the final selection.
        progress(f'DAILY ITEM SAVE | item={item_id} staged={len(pending)}')
        if not numeric_enter_confirmed:
            if not await _click_save(page, fieldset, progress):
                raise RuntimeError(f'DAILY SAVE CLICK UNKNOWN | item={item_id}; STOP, do not retry')
        # Enter may advance the active QAC item automatically. For Numeric,
        # defer server confirmation to ONE read-only batch at the end rather
        # than navigating away from QAC after each successful ACK.
        if field['format'] == '1' and numeric_enter_confirmed:
            for number, selection in pending:
                deferred_numeric.append((str(item_id), number, selection[6:]))
                progress(f'DAILY NUMERIC PENDING READBACK | item={item_id} slot={number} | QAC ACK received, server state not yet verified')
            progress(f'DAILY ITEM PERF | item={item_id} action=CONFIRM elapsed_ms={int((perf_counter()-item_started)*1000)} staged={len(pending)}')
            continue
        # Confirm ALL non-deferred slots in the item before proceeding.
        for number, selection in pending:
            try:
                result_id = await _wait_daily_slot_persisted(
                    page, str(item_id), number, progress=progress, control=control,
                    timeout_seconds=5 if field['format'] == '1' else 25)
                if field['format'] == '1':
                    fresh = await extract_daily_item_schema(page, str(item_id))
                    observed = next((x for x in fresh['slots'] if int(x['number']) == number), None) if fresh else None
                    if not observed or not qac_numeric_values_equal(selection[6:], str(observed.get('value') or '')):
                        raise RuntimeError(f'DAILY READBACK VALUE CONFLICT | item={item_id} slot={number}')
            except RuntimeError as exc:
                if field['format'] != '1' or 'DAILY SAVE UNVERIFIED' not in str(exc):
                    raise
                # No further write is attempted. Reopen the *same* Task and
                # verify persistence from newly loaded server state instead.
                result_id = await _fresh_qac_numeric_readback(
                    page, document or {}, production_date, str(item_id), number,
                    selection[6:], progress, control=control)
            try:
                from .daily_latest_memory import DailyLatestMemory
                from pathlib import Path
                if result_id:
                    DailyLatestMemory(Path(__file__).resolve().parents[1] / 'database' / 'daily_latest.sqlite3').confirmed(
                        document or {}, str(item_id), number,
                        selection[6:] if selection.startswith('VALUE:') else selection, result_id)
            except Exception as exc:
                progress(f'DAILY LATEST CACHE ERROR | {type(exc).__name__}: {exc}')
            saved += 1
            done += 1
            progress(f'DAILY SLOT SAVED | item={item_id} slot={number} choice={selection}')
        progress(f'DAILY ITEM PERF | item={item_id} action=SAVE elapsed_ms={int((perf_counter()-item_started)*1000)} staged={len(pending)}')
    if deferred_numeric:
        progress(f'DAILY NUMERIC WORKFLOW COMPLETE | acked={len(deferred_numeric)} | starting read-only final verification')
        verified = await _verify_numeric_batch_readonly(page, document or {}, production_date,
                                                        deferred_numeric, progress, control=control)
        saved += len(verified)
        done += len(verified)
        for item, number, value, result_id in verified:
            if result_id:
                try:
                    from .daily_latest_memory import DailyLatestMemory
                    from pathlib import Path
                    DailyLatestMemory(Path(__file__).resolve().parents[1] / 'database' / 'daily_latest.sqlite3').confirmed(
                        document or {}, item, number, value, result_id)
                except Exception as exc:
                    progress(f'DAILY LATEST CACHE ERROR | {type(exc).__name__}: {exc}')
            progress(f'DAILY SLOT SAVED | item={item} slot={number} choice=VALUE:{value} | verified=server')
    return {'fields':len(schema),'done':done,'skipped':skipped,'would_fill':0,'saved':saved,
            'errors':0,'numeric_missing':0,'history_references':0}


async def execute_daily_ok_register_async(
    cdp_url: str,
    production_date: str,
    documents: list[dict],
    *,
    settings: dict | None = None,
    dry_run: bool = False,
    progress: Callable[[str], None] | None = None,
    control=None,
) -> dict:
    """Write only operator-confirmed Daily HTML item/slot selections."""
    from playwright.async_api import async_playwright

    def log(message: str) -> None:
        if progress:
            progress(str(message))

    targets = [dict(doc) for doc in documents if str(doc.get("task_id") or "").strip()]
    result = {
        "documents": 0,
        "done": 0,
        "skipped": 0,
        "would_fill": 0,
        "saved": 0,
        "errors": 0,
        "numeric_missing": 0,
        "history_references": 0,
        "details": [],
    }
    if not targets:
        return result

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            if not browser.contexts:
                raise RuntimeError("ไม่พบ QAC Browser Context")
            context = browser.contexts[0]
            from .qac_session import require_owned_qac_page, is_trusted_qac_url
            module_page = None
            for candidate in context.pages:
                if candidate.is_closed() or not is_trusted_qac_url(candidate.url):
                    continue
                try:
                    if (await candidate.evaluate("window.name || ''")) == 'QAC_DAILY_DOCUMENT_MODULE':
                        module_page = candidate
                        break
                except Exception:
                    continue
            if module_page is None:
                raise RuntimeError('QAC DAILY PAGE NOT FOUND | เปิดหน้า Daily Document ของโปรแกรมก่อน')
            await require_owned_qac_page(module_page, tag='QAC_DAILY_DOCUMENT_MODULE',
                                         ready_selector='.calendar-monitor, tr[data-task]')

            await module_page.bring_to_front()
            await install_native_dialog_guard(module_page, log)
            await interaction_checkpoint(module_page, log, name="Daily Document module ready", wait_ms=220)
            await _wait_qac_complete(
                module_page,
                log,
                "Production Check Sheet",
                ready_selector=".calendar-monitor, tr[data-task]",
            )

            for index, document in enumerate(targets, start=1):
                await _wait_control(control)
                await require_owned_qac_page(module_page, tag='QAC_DAILY_DOCUMENT_MODULE',
                                             ready_selector='.calendar-monitor, tr[data-task]')
                name = str(document.get("document_name") or "").strip()
                task_id = str(document.get("task_id") or "").strip()
                task_date = str(document.get("found_date") or production_date).strip()
                # Scan has already resolved the exact task id. The QAC monitor
                # may show next-day lots in its 08:00-08:00 production window;
                # do not navigate the calendar if that task is already visible.
                from .qac_html_collector import _task_rows, _visible_task_rows
                current_rows = _visible_task_rows(await _task_rows(module_page))
                if any(str(row.get("task_id") or "") == task_id for row in current_rows):
                    log(f"DAILY TASK REUSE | task={task_id} | found_date={task_date} | skip calendar")
                else:
                    await _reuse_or_restore_task_list(module_page, task_date, log)
                    current_rows = _visible_task_rows(await _task_rows(module_page))
                    if not any(str(row.get("task_id") or "") == task_id for row in current_rows):
                        raise RuntimeError(f"Task {task_id} not found in current QAC list; rescan required")
                log(f"[{index}/{len(targets)}] DAILY REGISTER | date={task_date} | task={task_id} | {name}")
                measure_page = module_page
                pages_before = set(context.pages)
                register_completed = False
                try:
                    await _click_measure_action(module_page, task_id, log)
                    await module_page.wait_for_timeout(200)
                    new_pages = [page for page in context.pages if page not in pages_before]
                    if new_pages:
                        measure_page = new_pages[-1]
                        await measure_page.bring_to_front()
                    await install_native_dialog_guard(measure_page, log)
                    await interaction_checkpoint(measure_page, log, name=f"Measure page task={task_id}", wait_ms=300)
                    detail = await _register_ok_on_measure_page(
                        measure_page,
                        document=document,
                        production_date=task_date,
                        settings=settings,
                        dry_run=dry_run,
                        progress=log,
                        control=control,
                    )
                    detail.update({"task_id": task_id, "document_name": name})
                    result["details"].append(detail)
                    result["documents"] += 1
                    register_completed = True
                    for key in (
                        "done", "skipped", "would_fill", "saved", "errors",
                        "numeric_missing", "history_references",
                    ):
                        result[key] += int(detail.get(key) or 0)
                except Exception as exc:
                    result["errors"] += 1
                    result["details"].append({
                        "task_id": task_id,
                        "document_name": name,
                        "error": str(exc),
                    })
                    log(f"ERROR DOCUMENT | task={task_id} | {name} | {exc}")
                    # The browser state after any failure may contain an
                    # unconfirmed or already-submitted write. Preserve the
                    # Measure view and stop all further writes until reviewed.
                    log('DAILY REGISTER HALT | uncertain QAC state; keep Measure open, no further writes')
                    break
                finally:
                    if register_completed:
                        if measure_page is not module_page:
                            try:
                                await measure_page.close()
                            except Exception:
                                pass
                            await module_page.bring_to_front()
                        else:
                            await _return_to_check_sheet(module_page, log, task_id)
                    else:
                        log(f'DAILY MEASURE PRESERVED ON ERROR | task={task_id} | no Back/close; inspect QAC before retry')
                    # Do not navigate calendar after each document: retain the scanned task list.
                    # Next document verifies its own task ID and restores only if absent.

            return result
        finally:
            # connect_over_cdp disconnect only; it does not close the user's Edge process.
            await browser.close()

"""Read Sample results without activating panels or changing QAC's DOM.

The endpoint and field names match getItemContent in the captured QAC page.
Unsupported/ambiguous responses require the existing live-panel reader.
"""
from copy import deepcopy


def merge_results(field, rows, task_id):
    frequency = int(field.get('frequency') or 0)
    kind = str(field.get('type') or '')
    fmt = str(field.get('input_format') or '')
    if not field.get('fieldset_found') or not 0 < frequency <= 1000:
        raise ValueError('missing fieldset/frequency')
    if (kind, fmt) not in {('1', '3'), ('1', '4'), ('2', '1'), ('7', '1')}:
        raise ValueError('unsupported result format')
    if not isinstance(rows, list):
        raise ValueError('result list missing')
    old = {int(s['index']): s for s in field.get('slots', [])}
    if set(old) != set(range(1, frequency + 1)):
        raise ValueError('incomplete slot structure')
    slots = {i: {'index': i, 'empty': True, 'value': '', 'persisted': False,
                 'disabled': bool(old[i].get('disabled')), 'editable': bool(old[i].get('editable'))}
             for i in old}
    seen = set()
    for row in rows:
        if not isinstance(row, dict) or str(row.get('task_id')) != str(task_id):
            raise ValueError('wrong task')
        if str(row.get('item_type')) != kind or int(row.get('result_id') or 0) <= 0:
            raise ValueError('invalid result identity')
        if row.get('item_id') is not None and str(row['item_id']) != str(field['item']):
            raise ValueError('wrong item')
        no = int(row['result_no'])
        if no not in slots or no in seen:
            raise ValueError('ambiguous result slot')
        seen.add(no)
        if kind == '1':
            labels = {'2': 'Initial', '3': 'Middle', '4': 'Final'} if fmt == '3' else {'1': 'OK', '0': 'NG'}
            value = labels.get(str(row.get('result_okng')))
        else:
            raw = row.get('result_text' if kind == '7' else 'result_input')
            value = str(raw).strip() if raw is not None else None
        if value is None or not value:
            raise ValueError('missing saved value')
        slots[no] = {'index': no, 'empty': False, 'value': value, 'persisted': True,
                     'disabled': True, 'editable': False, 'result_id': str(row['result_id'])}
    # A server response contradicting an already persisted DOM row is unknown,
    # never evidence that an occupied slot can be reused.
    for no, slot in old.items():
        if slot.get('persisted') and no not in seen:
            raise ValueError('server/DOM occupancy conflict')
    result = deepcopy(field)
    result['slots'] = [slots[i] for i in sorted(slots)]
    return result


async def read_sample_results(page, fields, task_id):
    """One browser evaluation, at most three concurrent read-only requests.

    This is not one server request: QAC's observed API accepts one item at a
    time. Fetch locally in the existing authenticated browser session.
    """
    return await page.evaluate('''async ({fields, task}) => {
        const originalURL = location.href;
        const sameTask = () => location.href === originalURL &&
            String(sessionStorage.getItem('qac-task') || '') === task;
        if (!sameTask()) throw new Error('SAMPLE SNAPSHOT TASK CHANGED');
        const endpoint = new URL('../controller/measurementController.asmx/getItemContent', location.href);
        if (endpoint.origin !== location.origin) throw new Error('SAMPLE SNAPSHOT ORIGIN');
        const results = {};
        let next = 0;
        async function worker() {
            while (next < fields.length) {
                const field = fields[next++];
                const controller = new AbortController();
                const timer = setTimeout(() => controller.abort(), 15000);
                try {
                    if (!sameTask()) throw new Error('task changed');
                    const response = await fetch(endpoint.href, {
                        method:'POST', credentials:'same-origin', cache:'no-store',
                        headers:{'Content-Type':'application/json; charset=utf-8'},
                        body:JSON.stringify({task_id:task, item_id:field.item,
                            item_type:field.type, item_frequency:field.frequency}),
                        signal:controller.signal
                    });
                    if (!response.ok) throw new Error('HTTP ' + response.status);
                    const data = await response.json();
                    if (!Array.isArray(data.d)) throw new Error('unsupported response');
                    results[field.item] = {rows:data.d};
                } catch (error) {
                    results[field.item] = {error:String(error)};
                } finally { clearTimeout(timer); }
            }
        }
        await Promise.all(Array.from({length:Math.min(3, fields.length)}, worker));
        if (!sameTask()) throw new Error('SAMPLE SNAPSHOT TASK CHANGED');
        return results;
    }''', {'fields': [{'item': str(f['item']), 'type': str(f.get('type') or ''),
                      'frequency': int(f.get('frequency') or 0)} for f in fields],
           'task': str(task_id)})

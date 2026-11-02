from app.daily_slot_schema import can_reuse_batch_item


def item(value='0.5530', status='SAVED', result_id='46928473', fmt='1'):
    return {'item': '411398', 'format': fmt, 'slots': [{'number': 1, 'saved': status == 'SAVED',
            'status': status, 'value': value, 'result_id': result_id}]}


def test_numeric_reference_with_explicit_result_can_batch():
    assert can_reuse_batch_item(item())
    assert can_reuse_batch_item(item('-36.8'))


def test_empty_unknown_not_skipped():
    assert not can_reuse_batch_item(item('', 'EMPTY', ''))
    assert not can_reuse_batch_item(item('', 'UNKNOWN', ''))


def test_unverified_result_not_skipped():
    assert not can_reuse_batch_item(item(result_id=''))
    assert not can_reuse_batch_item(item(value=''))


def test_partial_results_never_skip_entire_item():
    x=item()
    x['slots'].append({'number': 2, 'saved': False, 'status': 'EMPTY', 'value': '', 'result_id': ''})
    assert not can_reuse_batch_item(x)


def test_duplicate_slot_rejected():
    x=item()
    x['slots'].append(dict(x['slots'][0]))
    assert not can_reuse_batch_item(x)


def test_choice_needs_expected_format():
    assert can_reuse_batch_item(item('OK', fmt='4'))
    assert not can_reuse_batch_item(item('FAIL', fmt='4'))
    assert can_reuse_batch_item(item('MIDDLE', fmt='3'))

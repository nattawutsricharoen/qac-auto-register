from app.daily_slot_schema import can_reuse_verified_empty_target


def item(**changes):
    value = {'item':'411398','format':'1', 'batch_empty_evidence':True,
             'slots':[{'number':1,'status':'EMPTY','saved':False,'result_id':'','value':''},
                      {'number':2,'status':'EMPTY','saved':False,'result_id':'','value':''}]}
    value.update(changes)
    return value


def test_batch_accepts_explicit_empty_target():
    assert can_reuse_verified_empty_target(item())


def test_never_accepts_missing_html_evidence():
    assert not can_reuse_verified_empty_target(item(batch_empty_evidence=False))


def test_never_accepts_saved_or_unknown_slot():
    a=item(); a['slots'][0]['status']='UNKNOWN'
    assert not can_reuse_verified_empty_target(a)
    b=item(); b['slots'][1]['saved']=True
    assert not can_reuse_verified_empty_target(b)


def test_never_accepts_duplicate_slot_or_value():
    a=item(); a['slots'][1]['number']=1
    assert not can_reuse_verified_empty_target(a)
    b=item(); b['slots'][0]['value']='0.51'
    assert not can_reuse_verified_empty_target(b)

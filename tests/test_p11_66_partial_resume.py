import pytest
from app.sample_register import authorize_partial_slot_resume, _validate_registration_slot


def plan(occupied='123', requested='123'):
    fields=[]
    for item, val, old in [('a',requested,occupied),('b','5',None)]:
        fields.append(dict(item=item,label=item,value=val,input_format='2',slots=[
            dict(index=8,empty=old is None,disabled=old is not None,value=old or ''),
            dict(index=9,empty=True,disabled=False,value='')]))
    return dict(serial_2d='S50U6158432',master_slot=9,documents=[dict(document_name='DOC',next_slot=9,schema=fields)],
                partial_slot_warnings=[dict(document_name='DOC',slot=8,saved_count=1,total_count=2)])

def test_resume_only_after_operator_confirmation():
    with pytest.raises(RuntimeError):
        authorize_partial_slot_resume(plan(),8,False)

def test_resume_selects_same_slot_and_preserves_old_rows():
    p=plan(); updated=authorize_partial_slot_resume(p,8,True)
    assert updated['master_slot']==8
    assert updated['documents'][0]['next_slot']==8
    assert updated['documents'][0]['schema'][0]['slots'][0]['value']=='123'
    assert _validate_registration_slot(updated['documents'][0]['schema'],updated['documents'][0]['schema'],8)=={'a':'SKIP','b':'WRITE'}

def test_resume_conflict_does_not_write():
    p=authorize_partial_slot_resume(plan(occupied='WRONG'),8,True)
    with pytest.raises(RuntimeError, match='ห้ามเขียนทับ'):
        _validate_registration_slot(p['documents'][0]['schema'],p['documents'][0]['schema'],8)

def test_resume_rejects_unknown_slot():
    with pytest.raises(RuntimeError):
        authorize_partial_slot_resume(plan(),7,True)

def test_resume_rejects_disabled_empty():
    p=plan();p['documents'][0]['schema'][1]['slots'][0]['disabled']=True
    with pytest.raises(RuntimeError):
        authorize_partial_slot_resume(p,8,True)

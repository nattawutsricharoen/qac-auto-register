import pytest
from app.electrode_issue_return import IssueReturnStore, ElectrodeLedgerError, normalize_barcode

@pytest.fixture
def db(tmp_path):
    s=IssueReturnStore(tmp_path/'local.db')
    s.set_type('749C',60000)
    s.add_destination('749C','TS1','Machine 1','Station 1','Upper')
    s.add_destination('749C','TS1','Machine 2','Station 2','Upper')
    return s

def test_scan_first_issue_second_return_and_snapshot(db):
    out=db.scan('749c-03250225');assert out['action']=='ISSUE' and len(out['options'])==2
    db.issue('749C-03250225',out['options'][0]['id'])
    assert db.scan('749C-03250225')['action']=='RETURN'
    db.set_type('749C',70000)
    with pytest.raises(ElectrodeLedgerError): db.return_electrode('749C-03250225',50000)
    assert db.return_electrode('749C-03250225',60000)=='Full counter'
    row=db.history()[0]
    assert row['target_shots_at_issue']==60000 and row['final_counter']==60000
    assert db.pending_count()==2
    with pytest.raises(ElectrodeLedgerError):db.issue('749C-03250225',out['options'][0]['id'])

def test_regrind_sequence_and_early_reason(db):
    d=db.destinations('749C')[0]['id']
    with pytest.raises(ElectrodeLedgerError):db.issue('749C-03250225-R1',d)
    db.issue('749C-03250225',d);db.return_electrode('749C-03250225',20000,'Broken')
    for n in range(1,6):
        barcode=f'749C-03250225-R{n}'
        db.issue(barcode,d)
        assert db.return_electrode(barcode,20000,'Damaged')=='Damaged'
    assert len(db.history('749C-03250225'))==6
    with pytest.raises(ElectrodeLedgerError):normalize_barcode('749C-03250225-R6')

def test_wrong_destination_rollback_and_concurrency(db):
    db.set_type('ZZZ',100)
    other=db.destinations('749C')[0]['id']
    with pytest.raises(ElectrodeLedgerError):db.issue('ZZZ-123456',other)
    db.issue('749C-03250225',other)
    with pytest.raises(ElectrodeLedgerError):db.issue('749C-03250225',other)
    assert db.pending_count()==1

def test_return_requires_counter_and_reason(db):
    d=db.destinations('749C')[0]['id'];db.issue('749C-03250225',d)
    for val in ('-1','1.5','abc'):
        with pytest.raises(ElectrodeLedgerError):db.return_electrode('749C-03250225',val)
    with pytest.raises(ElectrodeLedgerError):db.return_electrode('749C-03250225',59999,'')
    assert db.return_electrode('749C-03250225',59999,'Wear')=='Wear'

import pytest
from app.electrode_issue_return import IssueReturnStore, ElectrodeLedgerError

@pytest.fixture
def store(tmp_path):
    store=IssueReturnStore(tmp_path/'electrode.db')
    store.save_master_mapping('749C',60000,'TS2','GF','S1','Upper')
    return store

def test_regrind_interlock_defaults_strict_and_can_toggle(store):
    destination=store.destinations('749C')[0]['id']
    assert store.regrind_interlock_enabled()
    with pytest.raises(ElectrodeLedgerError):store.issue('749C-03250225-R3',destination)
    store.set_regrind_interlock(False)
    assert not store.regrind_interlock_enabled()
    store.issue('749C-03250225-R3',destination)
    assert store.scan('749C-03250225-R3')['action']=='RETURN'
    with pytest.raises(ElectrodeLedgerError):store.issue('749C-03250225-R3',destination)
    store.return_electrode('749C-03250225-R3',50000,'Broken')
    store.set_regrind_interlock(True)
    assert store.regrind_interlock_enabled()
    with pytest.raises(ElectrodeLedgerError):store.issue('749C-03250225-R5',destination)

def test_master_save_atomic_upsert_refresh_and_target_snapshot(store):
    before=store.master_summary();assert len(before)==1
    d=before[0]['id']
    store.issue('749C-03250225',d)
    store.save_master_mapping('749C',70000,'TS2','GF','S1','Upper')
    summary=store.master_summary()
    assert len(summary)==1 and summary[0]['target_shots']==70000
    assert store.history()[0]['target_shots_at_issue']==60000
    with pytest.raises(ElectrodeLedgerError):store.save_master_mapping('ZZZ',100,'','GF')
    assert len(store.master_summary())==1

def test_issue_allows_r5_without_legacy_history_only_when_disabled(store):
    store.set_regrind_interlock(False)
    d=store.destinations('749C')[0]['id']
    store.issue('749C-03250225-R5',d)
    assert store.history()[0]['regrind']==5
    assert store.pending_count()==1

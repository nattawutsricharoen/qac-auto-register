from app.sample_register import _validate_registration_slot
from app.sample_mapping_store import save_override, load_overrides


def item(id, kind, val, empty):
    return {"item":id, "input_format":kind,"label":id,"slots":[{"index":1,"empty":empty,"value":val,"disabled":False}]}


def test_retry_skips_exact_existing_and_writes_missing_in_same_slot():
    live=[item("a","3","#1 INITIAL 2026-10-24",False),item("b","7","08.00",False),item("c","2","",True)]
    planned=[{"item":"a","value":"INITIAL"},{"item":"b","value":"08.00"},{"item":"c","value":"23.5"}]
    assert _validate_registration_slot(live,planned,1)=={"a":"SKIP","b":"SKIP","c":"WRITE"}


def test_retry_fails_closed_on_conflicting_value():
    live=[item("a","3","#1 INITIAL",False),item("b","7","08.30",False)]
    planned=[{"item":"a","value":"INITIAL"},{"item":"b","value":"08.00"}]
    try:
        _validate_registration_slot(live,planned,1)
        assert False
    except RuntimeError as exc:
        assert "08.30" in str(exc)


def test_retry_fails_closed_if_saved_result_has_no_proven_value():
    live=[item("a","3","#1 John",False)]
    try:
        _validate_registration_slot(live,[{"item":"a","value":"INITIAL"}],1)
        assert False
    except RuntimeError as exc:
        assert "ไม่ตรงหรืออ่านค่าไม่แน่ชัด" in str(exc)


def test_station_mapping_persisted(tmp_path, monkeypatch):
    import app.sample_mapping_store as store
    monkeypatch.setattr(store,"mapping_db_path",lambda:tmp_path/'map.sqlite3')
    store.save_override("doc","1-2","Upper electrode No.",source_type="ELECTRODE_NO",source_machine="Gas Filling",source_position="Contacting",source_station="Station 2")
    found=store.load_overrides()[("doc","1-2","upper electrode no.")]
    assert found['source_station']=="Station 2"

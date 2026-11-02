from pathlib import Path


def test_sqlite_mapping_store_roundtrip(tmp_path, monkeypatch):
    import app.sample_mapping_store as store
    db = tmp_path / 'mapping.sqlite3'
    monkeypatch.setattr(store, 'mapping_db_path', lambda: db)
    store.save_override('DOC-A', '1-2', 'Pressure', 'GASS', 'Gas Pressure')
    loaded = store.load_overrides()
    assert loaded[('doc-a','1-2','pressure')]['source_column'] == 'Gas Pressure'
    store.save_override('DOC-A', '1-2', 'Pressure', 'GASS', 'Gas Pressure New')
    loaded = store.load_overrides()
    assert loaded[('doc-a','1-2','pressure')]['source_column'] == 'Gas Pressure New'
    store.delete_override('DOC-A', '1-2', 'Pressure')
    assert ('doc-a','1-2','pressure') not in store.load_overrides()


def test_mapping_store_supports_source_types(tmp_path, monkeypatch):
    import app.sample_mapping_store as store
    db = tmp_path / 'mapping_types.sqlite3'
    monkeypatch.setattr(store, 'mapping_db_path', lambda: db)
    store._SCHEMA_READY.clear()
    store.save_override('DOC-E', '1-1', 'Electrode No.', source_type='ELECTRODE_NO', source_machine='Housing Bottle Welding', source_position='Lower')
    store.save_override('DOC-E', '1-2', 'Shot', source_type='ELECTRODE_SHOT', source_machine='Housing Bottle Welding', source_position='Lower')
    store.save_override('DOC-E', '1-3', 'Judge', source_type='MANUAL')
    store.save_override('DOC-E', '1-4', 'Model', source_type='FIXED', source_value='S50')
    loaded = store.load_overrides()
    assert loaded[('doc-e','1-1','electrode no.')]['source_type'] == 'ELECTRODE_NO'
    assert loaded[('doc-e','1-1','electrode no.')]['source_machine'] == 'Housing Bottle Welding'
    assert loaded[('doc-e','1-2','shot')]['source_type'] == 'ELECTRODE_SHOT'
    assert loaded[('doc-e','1-3','judge')]['source_type'] == 'MANUAL'
    assert loaded[('doc-e','1-4','model')]['source_value'] == 'S50'


def test_mapping_store_rejects_electrode_source_without_position(tmp_path, monkeypatch):
    import pytest
    import app.sample_mapping_store as store
    db = tmp_path / 'mapping_invalid.sqlite3'
    monkeypatch.setattr(store, 'mapping_db_path', lambda: db)
    store._SCHEMA_READY.clear()
    with pytest.raises(ValueError, match='Machine'):
        store.save_override('DOC', '1', 'Electrode', source_type='ELECTRODE_NO')

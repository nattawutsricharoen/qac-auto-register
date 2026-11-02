from app import sample_register as sr
from app.electrode_issue_return import IssueReturnStore


def test_excel_electrode_requires_position_and_preserves_csv_mapping():
    master = sr._load_sample_mapping_master()
    row = master['map_by_identity'][('ts2-sub_sc1_housing disc-production sample initial-final','1-2','upper electrode no.')]
    assert row['Source Type (EDIT)'] == 'ELECTRODE_NO'
    assert row['Electrode Machine (EDIT)'] == 'Housing Disc Welding'
    assert not row['Electrode Position (EDIT)']
    row_counter = master['map_by_identity'][('ts2-sub_sc1_housing disc-production sample initial-final','1-3','upper electrode counter')]
    assert row_counter['Source Type (EDIT)'] == 'CSV'
    assert row_counter['CSV Column (EDIT)'] == 'HD E-rode (U)'
    kind, desc, value = sr._mapped_value_from_verified_master(master, {'item':'389499','section':'1-2','label':'Upper electrode No.'}, [],'INITIAL',line='TS2-Sub')
    assert kind == 'MANUAL_ELECTRODE_MAPPING_INCOMPLETE' and value == ''


def test_excel_electrode_resolves_exact_open_issue(tmp_path, monkeypatch):
    from app import runtime_paths
    monkeypatch.setattr(runtime_paths,'program_dir',lambda:tmp_path)
    store=IssueReturnStore(tmp_path/'database'/'electrode_issue_return_local.sqlite3')
    store.save_master_mapping('739D',60000,'TS2-Sub','Housing Disc Welding','','Upper')
    dest=store.destinations('739D')[0]
    store.issue('739D-05230111', dest['id'])
    result=sr._electrode_source_value('ELECTRODE_NO',machine='Housing Disc Welding',station='',position='Upper',line='TS2-Sub')
    assert result[0]=='ELECTRODE_NO' and result[2]=='739D-05230111'
    assert sr._electrode_source_value('ELECTRODE_NO',machine='Housing Disc Welding',station='',position='Lower',line='TS2-Sub')[0]=='MANUAL_ELECTRODE_NOT_UNIQUE'
    assert sr._electrode_source_value('ELECTRODE_NO',machine='Housing Disc Welding',station='',position='Upper',line='TS3-Sub')[0]=='MANUAL_ELECTRODE_NOT_UNIQUE'
    store.return_electrode('739D-05230111',60000)
    assert sr._electrode_source_value('ELECTRODE_NO',machine='Housing Disc Welding',station='',position='Upper',line='TS2-Sub')[0]=='MANUAL_ELECTRODE_NOT_UNIQUE'

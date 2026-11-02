from pathlib import Path
from openpyxl import Workbook

from app.sample_register import (
    load_sample_excel, find_sample_row, guess_2d_column,
    _doc_next_slot, apply_manual_values,
)


def test_excel_header_detect_and_exact_2d(tmp_path: Path):
    p = tmp_path / 'sample.xlsx'
    wb = Workbook()
    ws = wb.active
    ws.append(['Report title', None, None])
    ws.append(['2D Serial', 'Weld Current', 'Force'])
    ws.append(['ABC001', 10.5, 100])
    ws.append(['ABC002', 11.0, 101])
    wb.save(p)
    data = load_sample_excel(str(p))
    assert data.header_row == 2
    assert guess_2d_column(data.headers) == '2D Serial'
    row = find_sample_row(data, '2D Serial', 'ABC002')
    assert row['source_row'] == 4
    assert row['values']['Force'] == '101'


def test_duplicate_2d_rejected(tmp_path: Path):
    p = tmp_path / 'dup.xlsx'
    wb = Workbook(); ws = wb.active
    ws.append(['2D', 'Value']); ws.append(['X1', 1]); ws.append(['X1', 2]); wb.save(p)
    data = load_sample_excel(str(p))
    try:
        find_sample_row(data, '2D', 'X1')
        assert False, 'duplicate must fail'
    except RuntimeError as exc:
        assert 'ซ้ำ' in str(exc)


def test_slot_must_be_same_for_every_active_field():
    schema = [
        {'input_format':'1', 'slots':[{'index':1,'empty':False},{'index':2,'empty':True}]},
        {'input_format':'4', 'slots':[{'index':1,'empty':False},{'index':2,'empty':True}]},
    ]
    slot, _ = _doc_next_slot(schema)
    assert slot == 2
    schema[1]['slots'][0]['empty'] = True
    slot, _ = _doc_next_slot(schema)
    assert slot == -1


def test_manual_values_support_more_than_two_fields():
    plan = {'documents':[{'schema':[
        {'key':'a','value':''},{'key':'b','value':''},{'key':'c','value':''},{'key':'d','value':''}
    ]}]}
    out = apply_manual_values(plan, {'a':'1','b':'2','c':'3','d':'4'})
    assert [x['value'] for x in out['documents'][0]['schema']] == ['1','2','3','4']


def test_reserved_slot_skips_prepared_sample():
    schema = [
        {'input_format':'1', 'slots':[{'index':1,'empty':False},{'index':2,'empty':True},{'index':3,'empty':True}]},
        {'input_format':'4', 'slots':[{'index':1,'empty':False},{'index':2,'empty':True},{'index':3,'empty':True}]},
    ]
    slot, _ = _doc_next_slot(schema, {2})
    assert slot == 3


def test_verified_mapping_master_exact_csv_column():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    # data-item 389504 is verified in the user's master as HSNG / HD Current, physical column 61.
    raw = [''] * 80
    raw[60] = '123.45'
    field = {'item':'389504', 'section':'1-6', 'label':'Weld Current'}
    source, source_name, value = _mapped_value_from_verified_master(master, field, raw, 'INITIAL')
    assert source == 'CSV'
    assert 'column 61' in source_name
    assert value == '123.45'


def test_verified_mapping_master_sample_type_is_system_value():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    field = {'item':'389496', 'section':'1-0', 'label':'Initial / Middle / Final'}
    source, source_name, value = _mapped_value_from_verified_master(master, field, [], 'FINAL')
    assert source == 'SYSTEM'
    assert source_name == 'Sample Type'
    assert value == 'FINAL'


def test_unmapped_live_qac_item_never_guesses():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    source, source_name, value = _mapped_value_from_verified_master(
        master, {'item':'999999999', 'section':'X', 'label':'Unknown Real QAC Field'}, ['abc'], 'INITIAL'
    )
    assert source == 'MANUAL_UNMAPPED'
    assert source_name == ''
    assert value == ''


def test_real_style_two_header_csv_import(tmp_path: Path):
    from app.sample_register import load_sample_excel, guess_2d_column, find_sample_row
    p = tmp_path / 'sample.csv'
    p.write_text(
        ',,2,Result,,HSNG,,GASS,\n'
        'Date/Time,Kanban,Serial(Temporary),HSNG,DFSR,Housing Lot,HD Current,Gas Pressure,Gas Total Sink\n'
        '01/10/2026 08:00:00,S921,S92TEST001,1,1,LOT001,23.7,0.42,0.03\n',
        encoding='utf-8-sig'
    )
    data = load_sample_excel(str(p))
    assert data.source_type == 'CSV'
    assert data.header_row == 2
    assert guess_2d_column(data.headers) == 'Serial(Temporary)'
    assert data.column_profile[7] == ('HSNG', 'HD Current')
    assert data.column_profile[9] == ('GASS', 'Gas Total Sink')
    row = find_sample_row(data, 'Serial(Temporary)', 'S92TEST001')
    assert row['source_row'] == 3
    assert row['raw_values'][6] == '23.7'


def test_verified_mapping_uses_imported_csv_identity_not_old_physical_column():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    raw = [''] * 220
    # Deliberately move HSNG/HD Current away from historical column 61.
    raw[199] = '88.8'
    profile = {200: ('HSNG', 'HD Current')}
    source, source_name, value = _mapped_value_from_verified_master(
        master, {'item':'389504'}, raw, 'INITIAL', profile
    )
    assert source == 'CSV'
    assert source_name.startswith('column 200 ')
    assert value == '88.8'


def test_verified_mapping_never_uses_nearby_csv_header():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    raw = [''] * 200
    raw[60] = '999'
    # Similar but not exact name: must become manual, never read col 61.
    profile = {61: ('HSNG', 'HD Current Actual')}
    source, source_name, value = _mapped_value_from_verified_master(
        master, {'item':'389504'}, raw, 'INITIAL', profile
    )
    assert source == 'MANUAL_HEADER_MISMATCH'
    assert value == ''


def test_process_master_resolves_s92_gas_station1_exact_document_name():
    from app.sample_register import load_sample_process_options, resolve_sample_document_name
    opts = load_sample_process_options()
    gas = [x for x in opts if x.get('process_master') == 'GASS_GAS_FILLING' and str(x.get('station')) == '1']
    assert len(gas) == 1
    name = resolve_sample_document_name('TS1-Sub', 'S92', gas[0])
    assert name == 'TS1-Sub_S92_Seal pin & Gas filling ST#1 Initial-Final'


def test_s92_live_item_can_map_by_exact_process_and_field_without_data_item_guess():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    raw = [''] * 199
    # Real S92 sample CSV identity: GASS / Pin Current1. Physical location is irrelevant here.
    raw[161] = '17.25'
    profile = {162: ('GASS', 'Pin Current1')}
    source, source_name, value = _mapped_value_from_verified_master(
        master,
        {'item':'S92_DIFFERENT_LIVE_ID', 'section':'8-6', 'label':'Weld1 Current primary'},
        raw, 'INITIAL', profile,
        model='S92', process_master='GASS_GAS_FILLING', station='1'
    )
    assert source == 'CSV'
    assert source_name.startswith('column 162 ')
    assert value == '17.25'


def test_model_system_value_only_for_exact_live_model_field():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    source, source_name, value = _mapped_value_from_verified_master(
        master, {'item':'whatever', 'section':'X', 'label':'Model'}, [], 'INITIAL', {},
        model='S92', process_master='GASS_GAS_FILLING', station='1'
    )
    assert source == 'SYSTEM_MODEL'
    assert source_name == 'Model'
    assert value == 'S92'


def test_daily_document_is_authority_for_target_process_options():
    from app.sample_register import build_daily_sample_targets
    rows = [
        {'line':'TS1-Sub','model':'S92','document_kind':'AUTO_CSV','document_name':'TS1-Sub_S92_Seal pin & Gas filling ST#1 Initial-Final'},
        {'line':'TS1-Sub','model':'S92','document_kind':'AUTO_CSV','document_name':'TS1-Sub_S92_Housing disc-Production Sample Initial-Final'},
        {'line':'TS2-Sub','model':'S92','document_kind':'AUTO_CSV','document_name':'TS2-Sub_S92_Other Initial-Final'},
        {'line':'TS1-Sub','model':'SC1','document_kind':'AUTO_CSV','document_name':'TS1-Sub_SC1_Other Initial-Final'},
    ]
    opts = [
        {'process_master':'GASS_GAS_FILLING','station':'1','document_suffix':'Seal pin & Gas filling ST#1 Initial-Final'},
    ]
    out = build_daily_sample_targets(rows, 'TS1-Sub', 'S92', opts)
    assert [x['document_name'] for x in out] == [
        'TS1-Sub_S92_Seal pin & Gas filling ST#1 Initial-Final',
        'TS1-Sub_S92_Housing disc-Production Sample Initial-Final',
    ]
    assert out[0]['process_master'] == 'GASS_GAS_FILLING'
    assert out[0]['station'] == '1'
    assert out[0]['display'] == 'Seal pin & Gas filling ST#1'
    assert out[1]['process_master'] == ''


def test_daily_target_label_is_display_only_and_keeps_exact_document():
    from app.sample_register import build_daily_sample_targets
    row = {'line':'TS1-Sub','model':'S92','document_kind':'AUTO_CSV','document_name':'TS1-Sub_S92_Housing Bottle-Production Sample Initial-Final'}
    out = build_daily_sample_targets([row], 'TS1-Sub', 'S92', [])
    assert len(out) == 1
    assert out[0]['display'] == 'Housing Bottle'
    assert out[0]['document']['document_name'] == row['document_name']


def test_full_field_blocks_master_slot_instead_of_being_silently_skipped():
    schema = [
        {'input_format':'3', 'slots':[{'index':1,'empty':False},{'index':2,'empty':False}]},
        {'input_format':'1', 'slots':[{'index':1,'empty':False},{'index':2,'empty':True}]},
    ]
    slot, active = _doc_next_slot(schema)
    # A real QAC field that has no free result slot makes the document unusable.
    # It must not be skipped while another field chooses a slot.
    assert slot is None
    assert len(active) == 2


def test_sample_type_row_style_slots_can_resolve_slot_8():
    # Real QAC behavior: Initial/Middle/Final already has #1..#7 results,
    # while another field can still show #1..#30 as empty.  Slot #8 from the
    # sample-type field is the master and must be used on every page.
    schema = [
        {'input_format':'3', 'label':'Initial / Middle / Final', 'slots':[
            *[{'index':i,'empty':False} for i in range(1,8)],
            {'index':8,'empty':True}, {'index':9,'empty':True}
        ]},
        {'input_format':'1', 'label':'Time', 'slots':[
            *[{'index':i,'empty':True} for i in range(1,10)]
        ]},
    ]
    slot, _ = _doc_next_slot(schema)
    assert slot == 8


def test_master_slot_must_be_empty_on_every_field():
    schema = [
        {'input_format':'3', 'label':'Initial / Middle / Final', 'slots':[
            {'index':1,'empty':False}, {'index':2,'empty':True}
        ]},
        {'input_format':'1', 'label':'Time', 'slots':[
            {'index':1,'empty':True}, {'index':2,'empty':False}
        ]},
    ]
    slot, _ = _doc_next_slot(schema)
    assert slot is None


def test_s92_gas_mapping_prefers_exact_process_station_section_over_label():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    raw = [''] * 199
    profile = {
        164: ('GASS', 'Pin Time1'),
        168: ('GASS', 'Gas Pressure'),
        173: ('GASS', 'Gas Total Sink'),
    }
    raw[163] = '3'
    raw[167] = '59.9'
    raw[172] = '1.14'

    cases = [
        ({'item':'S92_LIVE_8_8','section':'8-8','label':'Weld1 time primary'}, 'Pin Time1', '3'),
        ({'item':'S92_LIVE_8_12','section':'8-12','label':'Gas Proof Pressure'}, 'Gas Pressure', '59.9'),
        ({'item':'S92_LIVE_8_14','section':'8-14','label':'Total sink'}, 'Gas Total Sink', '1.14'),
    ]
    for field, expected_col, expected_value in cases:
        source, source_name, value = _mapped_value_from_verified_master(
            master, field, raw, 'INITIAL', profile,
            model='S92', process_master='GASS_GAS_FILLING', station='1'
        )
        assert source == 'CSV'
        assert expected_col in source_name
        assert value == expected_value


def test_section_mapping_does_not_guess_when_section_unknown():
    from app.sample_register import _load_sample_mapping_master, _mapped_value_from_verified_master
    master = _load_sample_mapping_master()
    source, source_name, value = _mapped_value_from_verified_master(
        master,
        {'item':'S92_UNKNOWN','section':'8-99','label':'Total sink'},
        [''] * 199,
        'INITIAL',
        {173: ('GASS', 'Gas Total Sink')},
        model='S92', process_master='GASS_GAS_FILLING', station='1'
    )
    # Unknown section cannot inherit 8-14 just because the label looks similar.
    assert source in {'MANUAL_UNMAPPED', 'MANUAL_MAPPING_AMBIGUOUS'}
    assert value == ''


def test_local_mapping_override_has_priority_and_uses_exact_current_profile():
    from app.sample_register import _mapped_value_from_verified_master
    master = {
        'local_overrides': {
            ('ts1-sub_s92_demo initial-final', '8-12', 'gas proof pressure'): {
                'source_group': 'GASS', 'source_column': 'Gas Pressure'
            }
        },
        'tech_by_item': {}, 'map_by_identity': {}, 'process_section_map': {},
        'process_field_map': {}, 'csv_colno': {},
    }
    raw = [''] * 20
    raw[8] = '59.9'
    source, source_name, value = _mapped_value_from_verified_master(
        master,
        {'item':'LIVE','section':'8-12','label':'Gas Proof Pressure'},
        raw, 'INITIAL', {9: ('GASS','Gas Pressure')},
        document_name='TS1-Sub_S92_Demo Initial-Final'
    )
    assert source == 'LOCAL_MAP'
    assert 'Gas Pressure' in source_name
    assert value == '59.9'


def test_local_mapping_override_fails_safe_when_source_schema_changed():
    from app.sample_register import _mapped_value_from_verified_master
    master = {
        'local_overrides': {
            ('doc', '1-1', 'current'): {'source_group': 'GASS', 'source_column': 'Current1'}
        },
        'tech_by_item': {}, 'map_by_identity': {}, 'process_section_map': {},
        'process_field_map': {}, 'csv_colno': {},
    }
    source, source_name, value = _mapped_value_from_verified_master(
        master, {'item':'LIVE','section':'1-1','label':'Current'}, ['12'], 'INITIAL',
        {1: ('GASS','Different Column')}, document_name='DOC'
    )
    assert source == 'MANUAL_HEADER_MISMATCH'
    assert value == ''


def test_local_mapping_fixed_manual_ignore_sources():
    from app.sample_register import _mapped_value_from_verified_master
    field = {'section': '9-1', 'label': 'X', 'item': 'x'}
    key = ('doc-x', '9-1', 'x')
    for source_type, expected_source, expected_value in [
        ('FIXED', 'FIXED', 'ABC'),
        ('MANUAL', 'MANUAL', ''),
        ('IGNORE', 'IGNORE', ''),
    ]:
        master = {'local_overrides': {key: {
            'source_type': source_type, 'source_value': 'ABC',
            'source_group': '', 'source_column': '', 'source_machine': '', 'source_position': ''
        }}}
        source, detail, value = _mapped_value_from_verified_master(
            master, field, [], 'FINAL', document_name='DOC-X'
        )
        assert source == expected_source
        assert value == expected_value


def test_local_mapping_electrode_no_resolves_active_issue(tmp_path, monkeypatch):
    from app.electrode_issue_return import IssueReturnStore
    import app.runtime_paths as runtime_paths
    from app.sample_register import _mapped_value_from_verified_master

    db = tmp_path / 'database' / 'electrode_issue_return_local.sqlite3'
    store = IssueReturnStore(db)
    store.save_master_mapping('731C', 60000, 'TS1-Sub', 'Housing Bottle Welding', position='Lower')
    dest = store.destinations('731C')[0]
    no = '731C-08260086'
    store.issue(no, dest['id'])
    monkeypatch.setattr(runtime_paths, 'program_dir', lambda: tmp_path)
    field = {'section': '1-1', 'label': 'Electrode No.', 'item': 'e1'}
    master = {'local_overrides': {('doc-e', '1-1', 'electrode no.'): {
        'source_type': 'ELECTRODE_NO', 'source_machine': 'Housing Bottle Welding',
        'source_position': 'Lower', 'source_group': '', 'source_column': '', 'source_value': ''
    }}}
    source, detail, value = _mapped_value_from_verified_master(
        master, field, [], 'FINAL', document_name='DOC-E', line='TS1-Sub'
    )
    assert source == 'ELECTRODE_NO'
    assert value == no
    store.return_electrode(no, 60000)
    source, _, value = _mapped_value_from_verified_master(
        master, field, [], 'FINAL', document_name='DOC-E', line='TS1-Sub'
    )
    assert source == 'MANUAL_ELECTRODE_NOT_UNIQUE'
    assert value == ''


def test_edit_existing_csv_time_and_trace_value():
    from app.sample_register import apply_manual_values, sample_time_from_plan
    plan = {'csv_trace_time':'08.14', 'documents':[{'schema':[{'key':'time','label':'Time','value':'08.14','source':'CSV'}]}]}
    out = apply_manual_values(plan, {'time':'09.32'})
    assert out['documents'][0]['schema'][0]['value'] == '09.32'
    assert sample_time_from_plan(out) == '08.14'
    assert out['documents'][0]['schema'][0]['source'] == 'CSV'


def test_sample_text_input_presses_enter_before_save(monkeypatch):
    """Text/numeric sample fields commit Enter before clicking Save."""
    import asyncio
    from app import sample_register as sr
    calls = []

    class Target:
        async def count(self): return 1
        async def get_attribute(self, name): return 'true'
        async def input_value(self): return ''
        async def scroll_into_view_if_needed(self): calls.append('scroll')
        async def fill(self, value): calls.append('fill:' + value)
        async def press(self, key): calls.append('press:' + key)
        async def dispatch_event(self, event): calls.append('event:' + event)

    class Inputs:
        @property
        def first(self): return Target()
        async def count(self): return 1

    class Fieldset:
        def locator(self, selector):
            assert 'data-result-no="2"' in selector
            return Inputs()

    class StopAfterSave(Exception): pass

    async def fake_result_state(fieldset): return {}
    async def fake_click_save(page, fieldset, item, slot, log):
        calls.append('save')
        raise StopAfterSave

    monkeypatch.setattr(sr, '_result_state', fake_result_state)
    monkeypatch.setattr(sr, '_sample_save_until_complete', fake_click_save)
    field = {'input_format': '1', 'value': '564', 'section': '1-3',
             'label': 'Upper electrode Counter', 'source': 'CSV'}
    try:
        asyncio.run(sr._fill_field_at_master_slot(None, Fieldset(), field, 2, lambda msg: None))
    except StopAfterSave:
        pass
    else:
        assert False, 'Save boundary not reached'
    assert calls == ['scroll', 'fill:564', 'press:Enter', 'save']


def test_snapshot_each_item_while_active(monkeypatch):
    """QAC invalidates a previous panel when next left item is selected."""
    import asyncio
    import app.sample_register as sr
    state = {'active': None}
    async def activate(page, item, log):
        state['active'] = item
    async def snapshot(page):
        return [{'item': item, 'fieldset_found': True,
                 'slots': [{'index': 1, 'empty': item != 'a'}, {'index': 2, 'empty': False}]}
                for item in ('a', 'b') if item == state['active']]
    monkeypatch.setattr(sr, '_activate_sample_item', activate)
    monkeypatch.setattr(sr, '_live_schema', snapshot)
    captured = asyncio.run(sr._read_each_sample_item(None, [{'item':'a'}, {'item':'b'}], lambda _:None))
    assert [x['item'] for x in captured] == ['a','b']
    assert len(captured[0]['slots']) == 2 and len(captured[1]['slots']) == 2


def test_existing_partial_slot_two_not_rejected_as_missing():
    import app.sample_register as sr
    schema = [
        {'item':'a','label':'Time','input_format':'1','slots':[{'index':1,'empty':False,'value':'08.00'}, {'index':2,'empty':False,'value':'10.00'}]},
        {'item':'b','label':'Upper electrode Counter','input_format':'2','slots':[{'index':1,'empty':False,'value':'1'}, {'index':2,'empty':True,'value':''}]},
    ]
    planned = [{'item':'a','label':'Time','value':'10.00'}, {'item':'b','label':'Upper electrode Counter','value':'564'}]
    assert sr._validate_registration_slot(schema,planned,2) == {'a':'SKIP','b':'WRITE'}


def test_saved_numeric_result_row_slot_two_is_not_missing():
    """QAC replaces numeric inputs with green saved rows; slot 2 must survive."""
    from app import sample_register as sr
    field = {'item':'389500','input_format':'1','label':'Upper electrode Counter',
             'slots':[{'index':1,'empty':False,'value':'1','disabled':False},
                      {'index':2,'empty':False,'value':'564','disabled':False},
                      {'index':3,'empty':True,'value':'','disabled':False}]}
    plan = [{'item':'389500','label':'Upper electrode Counter','value':'564'}]
    assert sr._validate_registration_slot([field],plan,2) == {'389500':'SKIP'}
    assert sr._slot_state(field,2)['value'] == '564'


def test_numeric_result_row_selector_uses_row_and_explicit_input_slot():
    """Guard against reverting to input-only snapshot or nth index shift."""
    import inspect
    from app import sample_register as sr
    source = inspect.getsource(sr._live_schema)
    assert "querySelectorAll('tbody tr[data-result-no]')" in source
    assert 'rowSlots.length' in source
    assert ': rowSlots' in source
    fill = inspect.getsource(sr._fill_field_at_master_slot)
    assert 'data-result-no="{slot}"' in fill
    assert 'inputs.nth(slot - 1)' not in fill


def test_resume_disabled_persisted_numeric_slot_two():
    """Disabled saved QAC result is readable, not an unavailable slot."""
    from app import sample_register as sr
    field = {'item': '389500', 'input_format': '1', 'label': 'Upper electrode Counter',
             'slots': [{'index': 1, 'empty': False, 'value': '1', 'disabled': True, 'persisted': True},
                       {'index': 2, 'empty': False, 'value': '564', 'disabled': True, 'persisted': True},
                       {'index': 3, 'empty': True, 'value': '', 'disabled': False}]}
    planned = [{'item': '389500', 'label': 'Upper electrode Counter', 'value': '564'}]
    assert sr._validate_registration_slot([field], planned, 2) == {'389500': 'SKIP'}


def test_resume_disabled_empty_slot_never_written():
    from app import sample_register as sr
    field = {'item': '389500', 'input_format': '1', 'label': 'Upper electrode Counter',
             'slots': [{'index': 2, 'empty': True, 'value': '', 'disabled': True}]}
    planned = [{'item': '389500', 'label': 'Upper electrode Counter', 'value': '564'}]
    import pytest
    with pytest.raises(RuntimeError, match='ปิดใช้งาน'):
        sr._validate_registration_slot([field], planned, 2)


def test_saved_result_marker_precedes_outer_row_empty():
    import inspect
    from app.sample_register import _live_schema
    source = inspect.getsource(_live_schema)
    assert 'const persisted = Boolean(resultId)' in source
    assert 'entryEmpty === \'false\'' in source


def test_partial_slot_is_not_proof_of_2d():
    from app.sample_register import _partial_sample_slots
    schema = [
        {'label': 'Type', 'slots': [{'index': 8, 'empty': True}, {'index': 9, 'empty': True}]},
        {'label': 'Upper electrode No.', 'slots': [{'index': 8, 'empty': False, 'value': 'XYZ'}, {'index': 9, 'empty': True}]},
        {'label': 'Counter', 'slots': [{'index': 8, 'empty': True}, {'index': 9, 'empty': True}]},
    ]
    assert _partial_sample_slots(schema) == [
        {'slot': 8, 'saved_count': 1, 'total_count': 3, 'saved_fields': ['Upper electrode No.']}
    ]
    assert _partial_sample_slots([dict(f, slots=[{'index': 8, 'empty': True}]) for f in schema]) == []


def test_partial_slot_8_is_never_used_and_slot_9_remains_available():
    from app.sample_register import _partial_sample_slots
    schema = [
        {'input_format': '3', 'label': 'Initial / Middle / Final', 'slots':
            [{'index': 8, 'empty': True}, {'index': 9, 'empty': True}, {'index': 10, 'empty': True}]},
        {'input_format': '1', 'label': 'Upper electrode No.', 'slots':
            [{'index': 8, 'empty': False, 'value': 'E-1', 'disabled': True},
             {'index': 9, 'empty': True}, {'index': 10, 'empty': True}]},
        {'input_format': '1', 'label': 'Counter', 'slots':
            [{'index': 8, 'empty': True}, {'index': 9, 'empty': True}, {'index': 10, 'empty': True}]},
    ]
    assert _doc_next_slot(schema)[0] == 9
    assert _doc_next_slot(schema, {9})[0] == 10
    assert _partial_sample_slots(schema)[0]['slot'] == 8


def test_disabled_empty_row_cannot_be_written():
    schema = [
        {'input_format': '3', 'slots': [{'index': 8, 'empty': True}, {'index': 9, 'empty': True}]},
        {'input_format': '1', 'slots': [{'index': 8, 'empty': True, 'disabled': True}, {'index': 9, 'empty': True}]},
    ]
    assert _doc_next_slot(schema)[0] == 9

"""Static wiring regressions for a GUI requiring PySide6 on Windows."""
import ast
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[1] / 'main.py'


def _dialog_source():
    source = SOURCE.read_text(encoding='utf-8')
    tree=ast.parse(source)
    for cls in ast.walk(tree):
        if isinstance(cls, ast.FunctionDef) and cls.name == '_prompt_daily_slot_plan':
            return ast.get_source_segment(source,cls)
    raise AssertionError('Daily dialog handler missing')


def test_filter_based_on_live_slot_status_not_preset():
    text=_dialog_source()
    assert 'filter_rows.append((row_widget,slot_status,group))' in text
    assert "slot_status=('SAVED' if slot.get('saved') else raw_status)" in text
    assert "current=='ALL' or qac_status==current" in text


def test_exist_not_editable_and_real_value_visible():
    text=_dialog_source()
    assert "elif slot_status=='SAVED':" in text
    assert "slot.get('current_value') or slot.get('value')" in text
    assert "edits.append((item,num,'NUMBER'" in text
    assert "edits.append((item,num,'CHOICE'" in text
    # No editable widget is appended in the saved branch.
    saved_branch=text.split("elif slot_status=='SAVED':",1)[1].split("elif str(field.get('format'))",1)[0]
    assert 'edits.append' not in saved_branch


def test_filter_not_used_as_shortcut_to_confirmation():
    text=_dialog_source()
    assert "qac_filter.currentData() == 'ALL'" in text
    assert "qac_filter.currentIndexChanged.connect(on_qac_filter_changed)" in text
    assert "review_box.setChecked(False)" in text

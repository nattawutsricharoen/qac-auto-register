from app.daily_slot_schema import _reference_candidates
from app.qac_html_collector import _norm

NAME='TS1-Sub_All Model_Machine condition check'
def row(task,day,name=NAME):
    return dict(task_id=task,lot=day,document_name=name,can_view=True,can_measure=True,visible=True)

def test_cannot_reuse_target_when_monitor_is_previous_day():
    assert _reference_candidates([row('1330240','2026-10-21')], _norm(NAME),'2026-10-20','1330240') == []

def test_exact_date_candidate_from_previous_monitor():
    matches=_reference_candidates([row('1330240','2026-10-21'),row('1330100','2026-10-20')],_norm(NAME),'2026-10-20','1330240')
    assert [x['task_id'] for x in matches]==['1330100']

def test_ambiguous_same_day_remains_ambiguous():
    assert len(_reference_candidates([row('A','2026-10-20'),row('B','2026-10-20')],_norm(NAME),'2026-10-20','T'))==2

def test_different_name_cannot_be_reference():
    assert _reference_candidates([row('A','2026-10-20','Other')],_norm(NAME),'2026-10-20','T')==[]


def test_reference_rejects_view_only_task():
    r=row("R", "2026-10-20");r["can_measure"]=False
    assert _reference_candidates([r],_norm(NAME),"2026-10-20","T")==[]

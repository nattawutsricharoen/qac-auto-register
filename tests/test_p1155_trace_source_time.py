from app.sample_register import sample_time_from_plan, apply_manual_values
import pytest


def test_csv_trace_snapshot_survives_manual_time_edit():
    plan={"csv_trace_time":"08.00", "documents":[{"schema":[{"key":"t", "label":"Time", "value":"08.00", "source":"CSV"}]}]}
    revised=apply_manual_values(plan,{"t":"10.30"})
    assert revised["documents"][0]["schema"][0]["value"]=="10.30"
    assert sample_time_from_plan(revised)=="08.00"


def test_trace_refuses_manual_time_without_original():
    plan={"documents":[{"schema":[{"label":"Time", "value":"10.30", "source":"MANUAL"}]}]}
    with pytest.raises(RuntimeError, match="CSV"):
        sample_time_from_plan(plan)


def test_legacy_untouched_csv_provenance():
    plan={"documents":[{"schema":[{"label":"Time", "value":"08.00", "source":"CSV"}]}]}
    assert sample_time_from_plan(plan)=="08.00"

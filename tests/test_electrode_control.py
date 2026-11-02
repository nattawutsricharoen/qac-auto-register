from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from app.electrode_control import (
    ACTIVE_STATES,
    ElectrodeIdentityError,
    ElectrodePermissionError,
    ElectrodeSampleResolver,
    ElectrodeStateError,
    SQLiteElectrodeRepository,
    parse_electrode_no,
)


def setup_repo(tmp_path: Path):
    repo = SQLiteElectrodeRepository(tmp_path / "electrode.db")
    repo.upsert_type("731C", description="Bottle Lower")
    hb = repo.add_position("TS1-Sub", "Housing Bottle Welding", "Lower")
    db = repo.add_position("TS1-Sub", "Diffuser Bottle Welding", "Lower")
    wrong = repo.add_position("TS1-Sub", "Housing Disc Welding", "Upper")
    repo.allow_compatibility("731C", hb)
    repo.allow_compatibility("731C", db)
    return repo, hb, db, wrong


def test_parse_base_and_reuse():
    a = parse_electrode_no("731C-08260086")
    assert a.electrode_code == "731C"
    assert a.serial == "08260086"
    assert a.reuse_cycle == 0
    assert a.base_no == "731C-08260086"
    assert a.display_no == "731C-08260086"
    b = parse_electrode_no("737d-08230032-r2")
    assert b.electrode_code == "737D"
    assert b.reuse_cycle == 2
    assert b.base_no == "737D-08230032"
    assert b.display_no == "737D-08230032-R2"


@pytest.mark.parametrize("bad", ["", "731C", "731C-", "731C-123-R0", "731C-123-R", "731C-123-RX"])
def test_invalid_identity_rejected(bad):
    with pytest.raises(ElectrodeIdentityError):
        parse_electrode_no(bad)


def test_master_write_is_sparepart_only(tmp_path):
    repo = SQLiteElectrodeRepository(tmp_path / "e.db")
    with pytest.raises(ElectrodePermissionError):
        repo.upsert_type("731C", actor_department="PD")


def test_complete_lifecycle_disappears_from_active_but_history_remains(tmp_path):
    repo, hb, _, _ = setup_repo(tmp_path)
    no = "731C-08260086"
    repo.spare_issue(no, "TS1-Sub", actor_id="SP1")
    assert {x["lifecycle_status"] for x in repo.get_active_cycles()} == {"SPARE_ISSUED"}
    repo.pd_receive(no, "TS1-Sub", actor_id="PD1")
    repo.pd_withdraw_to_line_stock(no, "TS1-Sub", actor_id="PD1")
    repo.install(no, hb, initial_shot=0, actor_id="PD1")
    repo.snapshot(no, 100, actor_id="PD1")
    repo.remove_for_return(no, 120, actor_id="PD1")
    repo.pd_return(no, "TS1-Sub", actor_id="PD1")
    assert repo.get_active_cycles() == []
    history = repo.get_history(no)
    assert len(history) == 1
    assert history[0]["lifecycle_status"] == "COMPLETE"
    assert history[0]["final_shot"] == 120
    tx = [x["event_type"] for x in repo.transactions_for(no)]
    assert tx == ["SPARE_ISSUE", "PD_RECEIVE", "PD_WITHDRAW", "INSTALL", "SNAPSHOT", "REMOVE", "PD_RETURN"]


def test_return_must_be_same_serial(tmp_path):
    repo, *_ = setup_repo(tmp_path)
    repo.spare_issue("731C-08260086", "TS1-Sub")
    repo.pd_receive("731C-08260086", "TS1-Sub")
    repo.spare_issue("731C-08260091", "TS1-Sub")
    repo.pd_receive("731C-08260091", "TS1-Sub")
    # A different serialized item cannot satisfy the first item's lifecycle.
    repo.pd_return("731C-08260091", "TS1-Sub")
    active = {x["display_no"] for x in repo.get_active_cycles()}
    assert "731C-08260086" in active
    assert "731C-08260091" not in active


def test_wrong_line_blocked(tmp_path):
    repo, *_ = setup_repo(tmp_path)
    repo.spare_issue("731C-08260086", "TS1-Sub")
    with pytest.raises(ElectrodeStateError, match="TS1-Sub"):
        repo.pd_receive("731C-08260086", "TS2-Sub")


def test_machine_position_compatibility_and_shared_code(tmp_path):
    repo, hb, db, wrong = setup_repo(tmp_path)
    a = "731C-08260086"
    b = "731C-08260087"
    for no in (a, b):
        repo.spare_issue(no, "TS1-Sub")
        repo.pd_receive(no, "TS1-Sub")
        repo.pd_withdraw_to_line_stock(no, "TS1-Sub")
    repo.install(a, hb)
    repo.install(b, db)
    assert repo.current_installed("TS1-Sub", "Housing Bottle Welding", "Lower")["display_no"] == a
    assert repo.current_installed("TS1-Sub", "Diffuser Bottle Welding", "Lower")["display_no"] == b

    c = "731C-08260088"
    repo.spare_issue(c, "TS1-Sub")
    repo.pd_receive(c, "TS1-Sub")
    repo.pd_withdraw_to_line_stock(c, "TS1-Sub")
    with pytest.raises(ElectrodeStateError, match="ใช้กับ"):
        repo.install(c, wrong)


def test_position_cannot_have_two_installed(tmp_path):
    repo, hb, *_ = setup_repo(tmp_path)
    for no in ("731C-08260086", "731C-08260087"):
        repo.spare_issue(no, "TS1-Sub")
        repo.pd_receive(no, "TS1-Sub")
        repo.pd_withdraw_to_line_stock(no, "TS1-Sub")
    repo.install("731C-08260086", hb)
    with pytest.raises(ElectrodeStateError, match="ติดตั้งอยู่แล้ว"):
        repo.install("731C-08260087", hb)


def test_reuse_is_same_unit_new_cycle_and_sequential(tmp_path):
    repo, hb, *_ = setup_repo(tmp_path)
    base = "731C-08260086"
    repo.spare_issue(base, "TS1-Sub")
    repo.pd_receive(base, "TS1-Sub")
    repo.pd_withdraw_to_line_stock(base, "TS1-Sub")
    repo.install(base, hb)
    repo.remove_for_return(base, 1000)
    repo.pd_return(base, "TS1-Sub")
    r1 = repo.create_reuse_cycle(base, "TS1-Sub")
    assert r1 == "731C-08260086-R1"
    hist = repo.get_history(base)
    assert [x["reuse_cycle"] for x in hist] == [0, 1]
    assert hist[0]["lifecycle_status"] == "COMPLETE"
    assert hist[1]["lifecycle_status"] == "SPARE_ISSUED"
    with pytest.raises(ElectrodeStateError):
        repo.create_reuse_cycle(base, "TS1-Sub")


def test_cannot_create_r2_as_new_stock(tmp_path):
    repo, *_ = setup_repo(tmp_path)
    with pytest.raises(ElectrodeStateError, match="Base"):
        repo.spare_issue("731C-08260086-R2", "TS1-Sub")


def test_sample_resolver_is_read_only_current_installation(tmp_path):
    repo, hb, *_ = setup_repo(tmp_path)
    no = "731C-08260086"
    repo.spare_issue(no, "TS1-Sub")
    repo.pd_receive(no, "TS1-Sub")
    repo.pd_withdraw_to_line_stock(no, "TS1-Sub")
    repo.install(no, hb, initial_shot=20)
    repo.snapshot(no, 25)
    resolver = ElectrodeSampleResolver(repo)
    assert resolver.resolve_electrode_no("TS1-Sub", "Housing Bottle Welding", "Lower") == no
    assert resolver.resolve_shot("TS1-Sub", "Housing Bottle Welding", "Lower") == 25
    with pytest.raises(ElectrodeStateError):
        resolver.resolve_electrode_no("TS1-Sub", "Diffuser Bottle Welding", "Lower")


def test_shot_cannot_go_backwards(tmp_path):
    repo, hb, *_ = setup_repo(tmp_path)
    no = "731C-08260086"
    repo.spare_issue(no, "TS1-Sub")
    repo.pd_receive(no, "TS1-Sub")
    repo.pd_withdraw_to_line_stock(no, "TS1-Sub")
    repo.install(no, hb, initial_shot=100)
    with pytest.raises(ElectrodeStateError, match="ย้อนกลับ"):
        repo.snapshot(no, 99)


def test_balance_excludes_complete_cycles(tmp_path):
    repo, hb, *_ = setup_repo(tmp_path)
    for no in ("731C-08260086", "731C-08260087"):
        repo.spare_issue(no, "TS1-Sub")
        repo.pd_receive(no, "TS1-Sub")
    repo.pd_return("731C-08260086", "TS1-Sub")
    rows = repo.balance_summary()
    total = sum(r["qty"] for r in rows)
    assert total == 1
    assert rows[0]["electrode_code"] == "731C"


def test_concurrent_reads_and_spare_issues_are_stable(tmp_path):
    repo, *_ = setup_repo(tmp_path)

    def issue(i: int):
        no = f"731C-{i:08d}"
        repo.spare_issue(no, "TS1-Sub", actor_id="SP")
        return no

    with ThreadPoolExecutor(max_workers=8) as ex:
        created = list(ex.map(issue, range(1, 201)))
    assert len(created) == 200
    active = repo.get_active_cycles(line="TS1-Sub")
    assert len(active) == 200
    assert all(x["lifecycle_status"] in ACTIVE_STATES for x in active)


def test_position_listing_and_compatibility_are_read_only_helpers(tmp_path):
    repo, hb, db, wrong = setup_repo(tmp_path)
    positions = repo.list_positions(line='TS1-Sub')
    assert {p['id'] for p in positions} == {hb, db, wrong}
    assert repo.position_compatibility(hb) == ['731C']
    assert repo.position_compatibility(wrong) == []

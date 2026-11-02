from pathlib import Path

from app import access_control as ac


def _write(path: Path, header: str, row: str):
    path.write_text(header + "\n" + row + "\n", encoding="utf-8")


def test_v6_loads_sample_register_permission(tmp_path, monkeypatch):
    p = tmp_path / "access_control.csv"
    _write(
        p,
        "ip,name,status,tab1_enable,tab1_show,tab2_enable,tab2_show,tab3_enable,tab3_show,tab4_enable,tab4_show,tab5_enable,tab5_show,tab6_enable,tab6_show,settings_show",
        "10.0.0.5,PC1,active,1,1,1,1,1,1,1,1,1,1,1,1,1",
    )
    monkeypatch.setattr(ac, "local_ipv4_addresses", lambda: ["10.0.0.5"])
    record, _, _ = ac._load_access_record_lan(str(p), tmp_path)
    assert record is not None
    assert record.tab6_enable is True
    assert record.tab6_show is True


def test_v5_is_backward_compatible_but_sample_register_fail_closed(tmp_path, monkeypatch):
    p = tmp_path / "access_control.csv"
    _write(
        p,
        "ip,name,status,tab1_enable,tab1_show,tab2_enable,tab2_show,tab3_enable,tab3_show,tab4_enable,tab4_show,tab5_enable,tab5_show,settings_show",
        "10.0.0.5,PC1,active,1,1,1,1,1,1,1,1,1,1,1",
    )
    monkeypatch.setattr(ac, "local_ipv4_addresses", lambda: ["10.0.0.5"])
    record, _, _ = ac._load_access_record_lan(str(p), tmp_path)
    assert record is not None
    assert record.tab5_enable is True
    assert record.tab5_show is True
    assert record.tab6_enable is False
    assert record.tab6_show is False


def test_v6_pending_enrollment_sets_sample_permission_zero(tmp_path, monkeypatch):
    p = tmp_path / "access_control.csv"
    p.write_text(
        "ip,name,status,tab1_enable,tab1_show,tab2_enable,tab2_show,tab3_enable,tab3_show,tab4_enable,tab4_show,tab5_enable,tab5_show,tab6_enable,tab6_show,settings_show\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(ac, "computer_name", lambda: "NEW-PC")
    added, ip, _, _ = ac.enroll_pending_access(str(p), tmp_path, ["10.0.0.7"])
    assert added is True
    text = p.read_text(encoding="utf-8")
    assert "10.0.0.7,NEW-PC,pending" in text
    # all permission columns, including tab6, are fail-closed for new machines
    assert ",0,0,0\n" in text or text.rstrip().endswith(",0,0,0")

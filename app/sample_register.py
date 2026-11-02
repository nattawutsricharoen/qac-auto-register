from __future__ import annotations

import asyncio
import csv
import json
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from openpyxl import load_workbook

from .qac_task_scan import scan_qac_documents_async
from .qac_html_collector import (
    _click_measure_action, _return_to_check_sheet, _reuse_or_restore_task_list,
    _wait_qac_complete,
)
from .qac_measure_actions import _click_save, _wait_saved_state, _result_state
from .qac_interaction import (interaction_checkpoint, install_native_dialog_guard,
    inspect_visible_qac_modal, _find_affirmative_button)
from .runtime_paths import program_dir
from .sample_mapping_store import load_overrides
from .sample_qac_navigation import select_sample_item, reselect_after_sample_save, assert_sample_item_context


def _clean(value) -> str:
    if value is None:
        return ""
    if hasattr(value, "isoformat") and not isinstance(value, str):
        try:
            return value.isoformat(sep=" ")
        except TypeError:
            return value.isoformat()
    return str(value).strip()


def _canon(value: str) -> str:
    return "".join(ch.casefold() for ch in _clean(value) if ch.isalnum())


def _unique_headers(values) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for idx, raw in enumerate(values, start=1):
        base = _clean(raw) or f"Column_{idx}"
        key = base.casefold()
        seen[key] = seen.get(key, 0) + 1
        out.append(base if seen[key] == 1 else f"{base}_{seen[key]}")
    return out


def _detect_header_row(ws, max_rows: int = 30) -> int:
    best_row = 1
    best_score = -1
    for row_no, row in enumerate(ws.iter_rows(min_row=1, max_row=min(max_rows, ws.max_row), values_only=True), start=1):
        vals = [_clean(v) for v in row]
        non_empty = [v for v in vals if v]
        if not non_empty:
            continue
        stringish = sum(1 for v in non_empty if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?", v))
        unique = len({v.casefold() for v in non_empty})
        score = len(non_empty) * 3 + stringish + unique
        if score > best_score:
            best_score = score
            best_row = row_no
    return best_row


@dataclass
class SampleExcelData:
    path: str
    sheet_name: str
    header_row: int
    headers: list[str]
    rows: list[dict]
    source_type: str = "EXCEL"
    header_groups: list[str] | None = None
    header_names: list[str] | None = None
    column_profile: dict[int, tuple[str, str]] | None = None


def _csv_header_profile(row1: list[str], row2: list[str]) -> tuple[list[str], list[str], dict[int, tuple[str, str]]]:
    """Build the exact two-row header identity used by real QAC sample CSV files.

    The first three columns are ordinary fields. From column 4 onward the first
    header row is a merged-style group label (Result, HSNG, GASS, ...), so blank
    cells inherit the most recent non-empty group. No fuzzy name matching is used.
    """
    width = max(len(row1), len(row2))
    top = list(row1) + [""] * (width - len(row1))
    names = list(row2) + [""] * (width - len(row2))
    groups: list[str] = []
    current = ""
    profile: dict[int, tuple[str, str]] = {}
    for idx in range(width):
        raw_group = _clean(top[idx])
        name = _clean(names[idx])
        if idx < 3:
            group = ""
        else:
            if raw_group:
                current = raw_group
            group = current
        groups.append(group)
        profile[idx + 1] = (group, name)
    return groups, [_clean(x) for x in names], profile


def _display_headers_from_profile(groups: list[str], names: list[str]) -> list[str]:
    raw = []
    for group, name in zip(groups, names):
        if group and name:
            raw.append(f"{group} / {name}")
        else:
            raw.append(name or group)
    return _unique_headers(raw)


def _load_sample_csv(path: Path) -> SampleExcelData:
    # Production sample files supplied by the user are UTF-8 BOM CSV with two
    # header rows. We still try UTF-8 without BOM as a safe equivalent encoding.
    last_error = None
    parsed = None
    for encoding in ("utf-8-sig", "utf-8"):
        try:
            with path.open("r", encoding=encoding, newline="") as fh:
                parsed = list(csv.reader(fh))
            break
        except UnicodeDecodeError as exc:
            last_error = exc
    if parsed is None:
        raise RuntimeError(f"อ่าน Sample CSV ไม่สำเร็จ: {last_error}")
    if len(parsed) < 3:
        raise RuntimeError("Sample CSV ต้องมี header 2 แถวและข้อมูลอย่างน้อย 1 row")

    row1, row2 = parsed[0], parsed[1]
    groups, names, profile = _csv_header_profile(row1, row2)
    headers = _display_headers_from_profile(groups, names)
    width = len(headers)
    rows: list[dict] = []
    for source_row, values in enumerate(parsed[2:], start=3):
        vals = list(values) + [""] * max(0, width - len(values))
        vals = vals[:width]
        cleaned = [_clean(v) for v in vals]
        if not any(cleaned):
            continue
        raw = {headers[i]: cleaned[i] for i in range(width)}
        rows.append({"source_row": source_row, "values": raw, "raw_values": cleaned})

    return SampleExcelData(
        path=str(path), sheet_name="CSV", header_row=2, headers=headers, rows=rows,
        source_type="CSV", header_groups=groups, header_names=names, column_profile=profile,
    )


def load_sample_excel(path_value: str, sheet_name: str | None = None) -> SampleExcelData:
    """Load an actual sample source file.

    Kept under the historical function name for backward compatibility. Real
    production CSV is supported natively and its two-row header structure is
    preserved so exact mapping can be validated against the imported file itself.
    """
    path = Path(path_value)
    if not path.exists():
        raise RuntimeError(f"ไม่พบ Sample File: {path}")
    if path.suffix.lower() == ".csv":
        return _load_sample_csv(path)
    if path.suffix.lower() not in {".xlsx", ".xlsm"}:
        raise RuntimeError("Sample Register รองรับ .csv / .xlsx / .xlsm")

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        sheet = sheet_name if sheet_name and sheet_name in wb.sheetnames else wb.sheetnames[0]
        ws = wb[sheet]
        header_row = _detect_header_row(ws)
        values = next(ws.iter_rows(min_row=header_row, max_row=header_row, values_only=True))
        headers = _unique_headers(values)
        rows: list[dict] = []
        for row_no, vals in enumerate(ws.iter_rows(min_row=header_row + 1, values_only=True), start=header_row + 1):
            raw = {headers[i]: _clean(vals[i]) if i < len(vals) else "" for i in range(len(headers))}
            if not any(raw.values()):
                continue
            rows.append({"source_row": row_no, "values": raw, "raw_values": [_clean(v) for v in vals]})
        profile = {i + 1: ("", headers[i]) for i in range(len(headers))}
        return SampleExcelData(
            str(path), sheet, header_row, headers, rows, source_type="EXCEL",
            header_groups=[""] * len(headers), header_names=list(headers), column_profile=profile,
        )
    finally:
        wb.close()

def find_sample_row(data: SampleExcelData, column_name: str, serial_2d: str) -> dict:
    wanted = _clean(serial_2d).casefold()
    if not wanted:
        raise RuntimeError("2D Serial ว่าง")
    if column_name not in data.headers:
        raise RuntimeError(f"ไม่พบคอลัมน์ 2D: {column_name}")
    matched = [r for r in data.rows if _clean(r["values"].get(column_name)).casefold() == wanted]
    if not matched:
        raise RuntimeError(f"ไม่พบ 2D {serial_2d} ใน Excel")
    if len(matched) > 1:
        rows = ", ".join(str(r.get("source_row")) for r in matched[:10])
        raise RuntimeError(f"พบ 2D {serial_2d} ซ้ำ {len(matched)} row (rows: {rows})")
    return matched[0]


def guess_2d_column(headers: list[str]) -> str:
    preferred = (
        "2d", "2dcode", "2dserial", "serial2d", "serial", "barcode", "serialtemporary",
    )
    canon = {_canon(h): h for h in headers}
    for key in preferred:
        if key in canon:
            return canon[key]
    for header in headers:
        c = _canon(header)
        if "2d" in c or "serial" in c:
            return header
    return headers[0] if headers else ""


def _sample_mapping_path() -> Path:
    return program_dir() / "config" / "QAC_Sample_Mapping_Master_SC1_MAPPED.xlsx"


def _load_sample_mapping_master() -> dict:
    """Load the user's verified QAC sample mapping workbook.

    No inferred/fuzzy mapping is created here. Live QAC data-item is matched to
    HTML Technical exactly, then to Mapping exactly, then CSV Group/Column is
    resolved to the stored physical Column No. from CSV Headers.
    """
    path = _sample_mapping_path()
    if not path.exists():
        raise RuntimeError(f"ไม่พบ Sample Mapping Master: {path}")
    wb = load_workbook(path, read_only=False, data_only=True)
    try:
        def table(sheet):
            ws = wb[sheet]
            rows = list(ws.iter_rows(values_only=True))
            if not rows:
                return []
            heads = [_clean(v) for v in rows[0]]
            return [dict(zip(heads, row)) for row in rows[1:] if any(v is not None and _clean(v) for v in row)]
        mapping = table("Mapping")
        technical = table("HTML Technical")
        headers = table("CSV Headers")

        tech_by_item = {}
        for row in technical:
            item = _clean(row.get("data-item"))
            if item:
                tech_by_item[item] = row

        map_by_identity = {}
        process_field_map: dict[tuple[str, str, str], list[dict]] = {}
        process_section_map: dict[tuple[str, str, str], list[dict]] = {}
        process_options: dict[tuple[str, str], dict] = {}
        for row in mapping:
            key = (
                _clean(row.get("Document Name")).casefold(),
                _clean(row.get("QAC Section")).casefold(),
                _clean(row.get("QAC Field")).casefold(),
            )
            map_by_identity[key] = row

            process_master = _clean(row.get("Process Master"))
            station = _clean(row.get("Station/Head"))
            qac_field = _clean(row.get("QAC Field"))
            qac_section = _clean(row.get("QAC Section"))
            if process_master and qac_field:
                pkey = (process_master.casefold(), station.casefold(), qac_field.casefold())
                process_field_map.setdefault(pkey, []).append(row)
            if process_master and qac_section:
                skey = (process_master.casefold(), station.casefold(), qac_section.casefold())
                process_section_map.setdefault(skey, []).append(row)

            if process_master:
                okey = (process_master.casefold(), station.casefold())
                if okey not in process_options:
                    example_line = _clean(row.get("Example Line"))
                    example_model = _clean(row.get("Example Model"))
                    example_document = _clean(row.get("Document Name"))
                    prefix = f"{example_line}_{example_model}_" if example_line and example_model else ""
                    suffix = example_document[len(prefix):] if prefix and example_document.startswith(prefix) else example_document
                    display = suffix
                    for tail in (" Initial-Final", "-Production Sample Initial-Final"):
                        if display.endswith(tail):
                            display = display[:-len(tail)]
                            break
                    process_options[okey] = {
                        "process_master": process_master,
                        "station": station,
                        "example_line": example_line,
                        "example_model": example_model,
                        "example_document": example_document,
                        "document_suffix": suffix,
                        "display": display or process_master,
                    }

        csv_colno = {}
        for row in headers:
            group = _clean(row.get("Header Group"))
            name = _clean(row.get("Header Name"))
            colno = row.get("Column No.")
            try:
                colno = int(colno)
            except Exception:
                continue
            csv_colno[(group.casefold(), name.casefold())] = colno

        return {
            "path": str(path),
            "tech_by_item": tech_by_item,
            "map_by_identity": map_by_identity,
            "process_field_map": process_field_map,
            "process_section_map": process_section_map,
            "process_options": list(process_options.values()),
            "csv_colno": csv_colno,
            "local_overrides": load_overrides(),
        }
    finally:
        wb.close()


def load_sample_process_options() -> list[dict]:
    """Return process/document templates from the user's verified mapping master.

    The UI uses these exact templates to resolve a model/line-specific QAC document.
    No free-form process name guessing is performed.
    """
    master = _load_sample_mapping_master()
    return [dict(x) for x in master.get("process_options", [])]


def resolve_sample_document_name(line: str, model: str, process_option: dict) -> str:
    suffix = _clean((process_option or {}).get("document_suffix"))
    line = _clean(line)
    model = _clean(model)
    if not line or not model or not suffix:
        return ""
    return f"{line}_{model}_{suffix}"




def sample_target_label(document_name: str, line: str, model: str) -> str:
    """Human-readable Target Process label derived from an exact Daily Document row.

    The exact document name remains authoritative; this only shortens the text
    shown in the combobox. No document/process guessing is performed.
    """
    name = _clean(document_name)
    prefix = f"{_clean(line)}_{_clean(model)}_"
    if prefix and name.casefold().startswith(prefix.casefold()):
        name = name[len(prefix):]
    for tail in (
        "-Production Sample Initial-Final",
        " Production Sample Initial-Final",
        " Initial-Final",
    ):
        if name.casefold().endswith(tail.casefold()):
            name = name[:-len(tail)]
            break
    return name.strip(" _-") or _clean(document_name)


def build_daily_sample_targets(
    daily_rows: list[dict], line: str, model: str, process_options: list[dict] | None = None
) -> list[dict]:
    """Return exact Sample targets from Daily Document master for line+model.

    Daily Document is the authority for which QAC documents are selectable.
    Mapping-master process metadata is attached only when it resolves exactly to
    the same document name; otherwise the target is still selectable and any
    unmapped live QAC field will correctly fall back to manual input.
    """
    line_key = _clean(line).casefold()
    model_key = _clean(model).casefold()
    if not line_key or not model_key:
        return []
    opts = [dict(x) for x in (process_options or [])]
    out = []
    seen = set()
    for row in daily_rows or []:
        if _clean(row.get("line")).casefold() != line_key:
            continue
        if _clean(row.get("model")).casefold() != model_key:
            continue
        if _clean(row.get("document_kind")) != "AUTO_CSV":
            continue
        doc_name = _clean(row.get("document_name"))
        if not doc_name or "initial" not in doc_name.casefold():
            continue
        key = doc_name.casefold()
        if key in seen:
            continue
        seen.add(key)
        exact_opts = [
            opt for opt in opts
            if resolve_sample_document_name(line, model, opt).casefold() == key
        ]
        opt = exact_opts[0] if len(exact_opts) == 1 else {}
        out.append({
            "display": sample_target_label(doc_name, line, model),
            "document": dict(row),
            "document_name": doc_name,
            "process_master": _clean(opt.get("process_master")),
            "station": _clean(opt.get("station")),
        })
    return out


def _electrode_source_value(source_type: str, *, machine: str, station: str, position: str, line: str) -> tuple[str, str, str]:
    """Resolve one open ISSUE using exact destination identity, never fuzzy/first-hit."""
    machine, station, position, line = map(_clean, (machine, station, position, line))
    if not line or not machine or not position:
        return "MANUAL_ELECTRODE_MAPPING_INCOMPLETE", f"line={line!r} machine={machine!r} station={station!r} position={position!r}", ""
    from .runtime_paths import program_dir
    from .electrode_issue_return import IssueReturnStore
    store = IssueReturnStore(program_dir() / "database" / "electrode_issue_return_local.sqlite3")
    candidates = [r for r in store.history() if
                  r.get("state") == "ISSUED" and
                  _clean(r.get("line")).casefold() == line.casefold() and
                  _clean(r.get("machine")).casefold() == machine.casefold() and
                  _clean(r.get("position")).casefold() == position.casefold() and
                  _clean(r.get("station")).casefold() == station.casefold()]
    if len(candidates) != 1:
        return "MANUAL_ELECTRODE_NOT_UNIQUE", f"{line}/{machine}/{station}/{position}: active={len(candidates)}", ""
    if source_type == "ELECTRODE_NO":
        return "ELECTRODE_NO", f"ISSUE {candidates[0]['id']} | {machine}/{station}/{position}", candidates[0]["barcode"]
    return "MANUAL_ELECTRODE_SHOT", "Issue/Return ledger does not collect live shot counts", ""

def _mapped_value_from_verified_master(
    master: dict, field: dict, raw_values: list[str], sample_type: str,
    source_profile: dict[int, tuple[str, str]] | None = None,
    *, model: str = "", process_master: str = "", station: str = "", document_name: str = "", line: str = "",
) -> tuple[str, str, str]:
    """Return (source, source_name, value) using exact verified mapping only.

    For CSV sources the imported file is authoritative. The configured mapping
    gives the expected Header Group/Header Name, and the value is used only when
    that exact identity exists uniquely in the current file. This prevents an old
    SC1 physical column number from silently reading a different S92 field.
    """
    # User explicitly supplies Model and Sample Type. They are system values,
    # but only when the live QAC field name is an exact supported identity.
    label_key = _canon(field.get("label") or "")
    if label_key in {"model", "modelname"} and _clean(model):
        return "SYSTEM_MODEL", "Model", _clean(model)

    # Local SQLite mapping has priority over the legacy workbook. It is loaded
    # once per Prepare into memory, so field resolution does not perform DB I/O.
    override_key = (
        _clean(document_name).casefold(),
        _clean(field.get("section")).casefold(),
        _clean(field.get("label")).casefold(),
    )
    override = master.get("local_overrides", {}).get(override_key)
    if override:
        override_type = _clean(override.get("source_type") or "SMP_COLUMN").upper()
        if override_type == "SMP_COLUMN":
            group = _clean(override.get("source_group"))
            column = _clean(override.get("source_column"))
            expected = (group.casefold(), column.casefold())
            exact = [
                no for no, pair in (source_profile or {}).items()
                if (_clean(pair[0]).casefold(), _clean(pair[1]).casefold()) == expected
            ]
            if len(exact) == 1:
                colno = int(exact[0])
                idx = colno - 1
                value = _clean(raw_values[idx]) if 0 <= idx < len(raw_values) else ""
                return "LOCAL_MAP", f"column {colno} {group}/{column}".strip(), value
            if len(exact) > 1:
                return "MANUAL_HEADER_AMBIGUOUS", f"{group}/{column}".strip("/"), ""
            return "MANUAL_HEADER_MISMATCH", f"{group}/{column}".strip("/"), ""
        if override_type == "FIXED":
            return "FIXED", "Local fixed value", _clean(override.get("source_value"))
        if override_type == "MANUAL":
            return "MANUAL", "", ""
        if override_type == "IGNORE":
            return "IGNORE", "", ""
        if override_type in {"ELECTRODE_NO", "ELECTRODE_SHOT"}:
            machine = _clean(override.get("source_machine"))
            position = _clean(override.get("source_position"))
            station = _clean(override.get("source_station"))
            return _electrode_source_value(override_type, machine=machine, station=station, position=position, line=line)

    item = _clean(field.get("item"))
    tech = master.get("tech_by_item", {}).get(item)
    mapping = None
    if tech:
        identity = (
            _clean(tech.get("Document Name")).casefold(),
            _clean(tech.get("QAC Section")).casefold(),
            _clean(tech.get("QAC Field")).casefold(),
        )
        mapping = master.get("map_by_identity", {}).get(identity)

    # Live S92/S91 documents can use different data-item IDs and slightly
    # different labels from the SC1 reference.  For a verified Process Master +
    # Station, QAC Section is the stable functional identity (for example 8-14
    # is Total sink in S92 and Weld total sink (mm) in SC1).  Therefore resolve
    # by EXACT process + station + section first.  Field-name fallback remains
    # only for legacy rows that do not carry a section.  Ambiguous matches never
    # auto-map.
    if mapping is None and _clean(process_master):
        section = _clean(field.get("section"))
        if section:
            skey = (
                _clean(process_master).casefold(),
                _clean(station).casefold(),
                section.casefold(),
            )
            candidates = master.get("process_section_map", {}).get(skey, [])
            if len(candidates) == 1:
                mapping = candidates[0]
            elif len(candidates) > 1:
                return "MANUAL_MAPPING_AMBIGUOUS", "", ""

    if mapping is None and _clean(process_master):
        pkey = (
            _clean(process_master).casefold(),
            _clean(station).casefold(),
            _clean(field.get("label")).casefold(),
        )
        candidates = master.get("process_field_map", {}).get(pkey, [])
        if len(candidates) == 1:
            mapping = candidates[0]
        elif len(candidates) > 1:
            return "MANUAL_MAPPING_AMBIGUOUS", "", ""

    if not mapping:
        return "MANUAL_UNMAPPED", "", ""

    source_type = _clean(mapping.get("Source Type (EDIT)")).upper()
    if source_type == "SYSTEM" and _clean(mapping.get("Input Type")).upper() == "SAMPLE_TYPE":
        return "SYSTEM", "Sample Type", _clean(sample_type)
    if source_type in {"MANUAL", "MANUAL_OK_NG"}:
        return source_type, "", ""
    if source_type == "IGNORE":
        return "IGNORE", "", ""
    if source_type in {"ELECTRODE_NO", "ELECTRODE_SHOT"}:
        return _electrode_source_value(
            source_type,
            machine=_clean(mapping.get("Electrode Machine (EDIT)")),
            station=_clean(mapping.get("Electrode Station (EDIT)")),
            position=_clean(mapping.get("Electrode Position (EDIT)")),
            line=line,
        )
    if source_type != "CSV":
        return "MANUAL_UNMAPPED", "", ""

    group = _clean(mapping.get("CSV Group (EDIT)"))
    column = _clean(mapping.get("CSV Column (EDIT)"))
    expected = (group.casefold(), column.casefold())

    colno = None
    if source_profile:
        exact = [
            no for no, pair in source_profile.items()
            if (_clean(pair[0]).casefold(), _clean(pair[1]).casefold()) == expected
        ]
        if len(exact) == 1:
            colno = exact[0]
        elif len(exact) > 1:
            return "MANUAL_HEADER_AMBIGUOUS", f"{group}/{column}", ""
        else:
            # The imported source does not contain the exact field named by the
            # verified mapping. Never fall back to a nearby name or old col no.
            return "MANUAL_HEADER_MISMATCH", f"{group}/{column}", ""
    else:
        # Compatibility path for historical tests/files without a two-row profile.
        colno = master.get("csv_colno", {}).get(expected)

    if not colno:
        return "MANUAL_UNMAPPED", f"{group}/{column}", ""
    idx = int(colno) - 1
    value = _clean(raw_values[idx]) if 0 <= idx < len(raw_values) else ""

    fmt = _clean(mapping.get("Format (EDIT)")).upper()
    if value and fmt == "HH.MM":
        m = re.search(r"(\d{1,2})[:.](\d{2})", value)
        if m:
            value = f"{int(m.group(1)):02d}.{m.group(2)}"
    return "CSV", f"column {colno} {group}/{column}".strip(), value

def _reserved_slots_from_plans(plans: list[dict]) -> dict[str, set[int]]:
    out: dict[str, set[int]] = {}
    for plan in plans or []:
        slot = int(plan.get("master_slot") or 0)
        if slot < 1:
            continue
        for doc in plan.get("documents") or []:
            name = _clean(doc.get("document_name"))
            if name:
                out.setdefault(name.casefold(), set()).add(slot)
    return out

async def _live_schema(page) -> list[dict]:
    """Read the live Production Check Sheet schema from the real Measure page.

    QAC renders each inspection item twice:
    - `.f1-step[data-item]` is only the left navigation/index.
    - `.fieldset[data-item]` is the real working panel containing result rows/inputs.

    Slot state MUST therefore be read from the matching fieldset, not from the
    navigation step.  This is important for SAMPLE_TYPE / OK-NG items where the
    slot is represented by `tr[data-result-no][data-empty]` rather than an input.
    """
    await _wait_qac_complete(page, lambda _m: None, "Sample Measure", ready_selector=".f1-step[data-item]")
    return await page.locator(".f1-step[data-item]").evaluate_all("""steps => steps.map(step => {
        const item = String(step.getAttribute('data-item') || '');
        if (!item) return null;

        // The f1-step is navigation only.  Result slots live in the matching
        // fieldset with the same data-item on the real QAC Measure page.
        const fieldset = document.querySelector('.fieldset[data-item="' + item + '"]');
        const root = fieldset || step;

        const inputs = Array.from(root.querySelectorAll('input[data-result-no], textarea[data-result-no]'));
        const slots = inputs.map((node, idx) => {
            const no = Number(node.getAttribute('data-result-no') || (idx + 1));
            const rawEmpty = String(node.getAttribute('data-empty') || '').toLowerCase();
            return {
                index: no > 0 ? no : (idx + 1),
                empty: rawEmpty === 'true' || (rawEmpty !== 'false' && !String(node.value || '').trim()),
                value: String(node.value || '').trim(),
                disabled: Boolean(node.disabled)
            };
        });

        // Saved QAC result rows often replace their input with a green result
        // element. Read ALL result rows, including saved slots, rather than
        // only remaining editable inputs. Preserve the actual data-result-no.
        const rows = Array.from(root.querySelectorAll('tbody tr[data-result-no]'));
        const rowSlots = rows.map((row, idx) => {
            const no = Number(row.getAttribute('data-result-no') || (idx + 1));
            const cells = Array.from(row.querySelectorAll(':scope > td'));
            const resultCell = cells.length >= 2 ? cells[1] : row;
            const entry = resultCell.querySelector('input[data-result-no], textarea[data-result-no]');
            const displayValue = (resultCell.innerText || resultCell.textContent || '').trim();
            const rowEmpty = String(row.getAttribute('data-empty') || '').toLowerCase();
            const entryEmpty = String(entry?.getAttribute('data-empty') || '').toLowerCase();
            const resultId = String(entry?.getAttribute('data-result') || row.getAttribute('data-result') || '').trim();
            const value = entry ? String(entry.value || '').trim() : displayValue;
            // QAC can leave tr[data-empty=true] after saving and mark the
            // disabled input itself data-empty=false with a result identifier.
            // This is SAVED, not an unavailable edit control.
            const persisted = Boolean(resultId) || (entry ? entryEmpty === 'false' && Boolean(value)
                                                     : rowEmpty === 'false' && Boolean(value));
            const empty = !persisted && (entry ? (entryEmpty === 'true' || !value)
                                                : (rowEmpty === 'true' || !value));
            return {
                index: no > 0 ? no : (idx + 1),
                empty,
                value,
                persisted,
                disabled: Boolean(entry && entry.disabled),
                editable: Boolean(entry && !entry.disabled)
            };
        });

        const inputFormat = String(
            step.getAttribute('data-input') ||
            fieldset?.getAttribute('data-input-format') ||
            ''
        );
        const section = (step.querySelector('.f1-step-icon')?.innerText || '').trim();
        const label = (step.querySelector('.f1-step-p')?.innerText || '').trim();
        const isSampleType = inputFormat === '3' ||
            label.toLowerCase().replace(/\\s+/g, ' ').trim() === 'initial / middle / final';

        // On the real Production Check Sheet, the sample-type field can contain
        // hidden/auxiliary inputs while the authoritative occupied/empty state is
        // on tbody tr[data-result-no].  Prefer rows for this master field so a
        // hidden empty input can never reset Master Slot back to #1.
        const resolvedSlots = rowSlots.length
            ? (isSampleType ? rowSlots.map((slot, i) => ({
                ...slot,
                value: (rows[i]?.innerText || rows[i]?.textContent || '').trim(),
                empty: String(rows[i]?.getAttribute('data-empty') || '').toLowerCase() === 'true'
            })) : rowSlots)
            : slots;

        return {
            item,
            input_format: inputFormat,
            type: String(step.getAttribute('data-type') || fieldset?.getAttribute('data-type') || ''),
            required: String(step.getAttribute('data-required') || fieldset?.getAttribute('data-required') || '') === '1',
            frequency: Number(step.getAttribute('data-frequency') || fieldset?.getAttribute('data-frequency') || '0'),
            section,
            label,
            slots: resolvedSlots,
            okVisible: Boolean(root.querySelector('.btn-ok:not([disabled]), .btn-ok-pd:not([disabled])')),
            ngVisible: Boolean(root.querySelector('.btn-ng:not([disabled]), .btn-ng-pd:not([disabled])')),
            fieldset_found: Boolean(fieldset)
        };
    }).filter(x => x && x.item)""")



async def _read_each_sample_item(page, planned: list[dict], log) -> list[dict]:
    """Snapshot the Result of EACH active item, not the last-visible QAC panel.

    QAC may refresh/reset hidden panels when navigating left-side items; a final
    whole-page snapshot is not evidence of all earlier items' result states.
    """
    collected: list[dict] = []
    for planned_field in planned:
        item = str(planned_field.get("item") or "")
        if not item:
            raise RuntimeError("SAMPLE RESULT READ: missing item id")
        await _activate_sample_item(page, item, log)
        field = next((x for x in await _live_schema(page) if str(x.get("item")) == item), None)
        if field is None or not field.get("fieldset_found"):
            raise RuntimeError(f"SAMPLE RESULT READ: item={item} fieldset not loaded")
        if not field.get("slots"):
            # A missing result table is UNKNOWN, not an empty slot.
            await _activate_sample_item_force(page, item, log)
            field = next((x for x in await _live_schema(page) if str(x.get("item")) == item), None)
            if field is None or not field.get("slots"):
                raise RuntimeError(f"SAMPLE RESULT READ: item={item} no result slots after reopen")
        collected.append(field)
        log(f"SAMPLE RESULT SNAPSHOT | item={item} | slots={len(field['slots'])} | used={sum(not x.get('empty') for x in field['slots'])}")
    return collected


async def _read_sample_snapshot(page, planned: list[dict], task_id: str, log) -> list[dict]:
    """Read initial DOM once, then fetch results without per-item navigation."""
    from .sample_result_snapshot import read_sample_results, merge_results
    started = asyncio.get_running_loop().time()
    responses = await read_sample_results(page, planned, task_id)
    collected = []
    fallback = 0
    for field in planned:
        item = str(field['item'])
        try:
            response = responses[item]
            if 'error' in response:
                raise ValueError('read request failed')
            snapshot = merge_results(field, response['rows'], task_id)
        except (KeyError, ValueError, TypeError, OverflowError):
            fallback += 1
            log(f'SAMPLE SNAPSHOT FALLBACK | item={item} | verify live panel')
            snapshot = (await _read_each_sample_item(page, [field], log))[0]
        collected.append(snapshot)
    log(f'SAMPLE BULK SNAPSHOT | items={len(collected)} panel_fallbacks={fallback} '
        f'elapsed_ms={int((asyncio.get_running_loop().time()-started)*1000)}')
    return collected


async def _activate_sample_item_force(page, item: str, log):
    return await select_sample_item(page, item, log, force=True)


def _first_empty_slot(field: dict) -> int | None:
    slots = [s for s in (field.get("slots") or []) if not bool(s.get("disabled"))]
    for slot in slots:
        if bool(slot.get("empty")):
            return int(slot.get("index") or 0) or None
    return None


def _first_available_slot(field: dict, reserved: set[int] | None = None) -> int | None:
    reserved = set(reserved or set())
    slots = [s for s in (field.get("slots") or []) if not bool(s.get("disabled"))]
    for slot in slots:
        idx = int(slot.get("index") or 0)
        if idx > 0 and bool(slot.get("empty")) and idx not in reserved:
            return idx
    return None


def _slot_state(field: dict, slot_no: int) -> dict | None:
    for slot in field.get("slots") or []:
        if int(slot.get("index") or 0) == int(slot_no):
            return slot
    return None


def _is_sample_type_field(field: dict) -> bool:
    if str(field.get("input_format") or "") == "3":
        return True
    label = _canon(field.get("label"))
    return label == _canon("Initial / Middle / Final")


def _partial_sample_slots(schema: list[dict]) -> list[dict]:
    """Report mixed occupancy per absolute slot; never infer a matching 2D.

    A value in one field is evidence of a saved result, NOT evidence of ownership.
    """
    active = [f for f in schema if f.get("slots")]
    if not active:
        return []
    indexes = sorted({int(s.get("index") or 0) for f in active for s in f["slots"]} - {0})
    out = []
    for idx in indexes:
        states = [_slot_state(f, idx) for f in active]
        if any(state is None for state in states):
            continue
        used = [(f, state) for f, state in zip(active, states) if not state.get("empty")]
        if 0 < len(used) < len(active):
            out.append({"slot": idx, "saved_count": len(used),
                        "total_count": len(active),
                        "saved_fields": [str(f.get("label") or f.get("item") or "") for f, _ in used]})
    return out


def _doc_next_slot(schema: list[dict], reserved: set[int] | None = None) -> tuple[int | None, list[dict]]:
    """Resolve the master sample slot from live QAC.

    Production Check Sheet does NOT require every field's *first* empty row to be
    the same.  The Initial/Middle/Final item is the master sequence.  For example,
    it can have results #1..#7 while Time/current/pressure pages still visually
    expose empty rows from #1.  The next sample belongs to #8 on every page.

    Therefore:
      1) derive the next slot from the live Initial/Middle/Final field;
      2) verify that exact slot exists and is empty on every participating field;
      3) never shift another field to its own first-empty slot.
    """
    reserved = set(reserved or set())
    active_fields = [field for field in schema if (field.get("slots") or [])]
    if not active_fields:
        return None, active_fields

    masters = [field for field in active_fields if _is_sample_type_field(field)]
    if masters:
        master_field = masters[0]
        # A partly populated row is not an available slot and is NOT proof of
        # ownership by the current 2D. Seek the next slot empty on every item.
        for candidate in sorted(master_field.get("slots") or [], key=lambda x: int(x.get("index") or 0)):
            slot_no = int(candidate.get("index") or 0)
            if slot_no <= 0 or slot_no in reserved or not candidate.get("empty") or candidate.get("disabled"):
                continue
            states = [_slot_state(field, slot_no) for field in active_fields]
            if any(state is None for state in states):
                continue
            if all(state.get("empty") and not state.get("disabled") for state in states):
                return slot_no, active_fields
        return None, active_fields

    # Compatibility fallback for non-sample schemas: all fields must still agree
    # on their own next available slot.
    candidates: list[int] = []
    for field in active_fields:
        nxt = _first_available_slot(field, reserved)
        if nxt is None:
            return None, active_fields
        candidates.append(nxt)
    unique = sorted(set(candidates))
    if len(unique) != 1:
        return -1, active_fields
    return unique[0], active_fields


def _slot_matches_expected(field: dict, slot: int, expected: str) -> bool:
    """Fail closed: a populated result can be skipped only if its value is provably equal."""
    state = _slot_state(field, slot)
    if state is None or state.get("empty"):
        return False
    raw = _clean(state.get("value"))
    if not raw:
        return False
    kind = str(field.get("input_format") or "")
    if kind == "3":
        # The QAC result row may contain employee/time metadata: require a word token.
        return bool(re.search(r"(?<![A-Za-z])" + re.escape(_clean(expected)) + r"(?![A-Za-z])", raw, re.I))
    if kind == "4":
        # QAC judgement row may include many columns; match only an explicit token.
        want = _clean(expected).upper()
        if want not in {"OK", "NG"}:
            return False
        return bool(re.search(r"(?<![A-Za-z])" + want + r"(?![A-Za-z])", raw, re.I))
    # QAC numeric results may format a stored number with extra trailing
    # fractional zeroes (21.60) while the CSV provides 21.6. Compare numeric
    # values ONLY for numeric input fields, never serials, time or identifiers.
    if str(field.get("type") or "") == "2" and kind not in {"3", "4"}:
        number_pattern = r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)"
        actual = raw.strip()
        wanted = _clean(expected).strip()
        if re.fullmatch(number_pattern, actual) and re.fullmatch(number_pattern, wanted):
            try:
                return Decimal(actual) == Decimal(wanted)
            except InvalidOperation:
                return False
        return False
    return _clean(raw) == _clean(expected)


def _validate_registration_slot(schema: list[dict], planned: list[dict], slot: int) -> dict[str, str]:
    """Determine SKIP or WRITE per field, preserving a single master slot on retry.

    An occupied sample-type row is not enough proof of identity when previous
    registration stopped before the 2D trace comment: never silently claim that
    an unrelated sample belongs to this 2D.
    """
    live = {str(x.get("item") or ""): x for x in schema}
    actions = {}
    for field in planned:
        item = str(field.get("item") or "")
        current = live.get(item)
        if current is None:
            raise RuntimeError(f"Sample slot {slot}: QAC field หาย item={item}")
        state = _slot_state(current, slot)
        if state is None:
            raise RuntimeError(f"Sample slot {slot}: field={field.get('label')} ไม่พบ Result Row ของ Slot")
        if state.get("empty"):
            if state.get("disabled"):
                raise RuntimeError(f"Sample slot {slot}: field={field.get('label')} ช่องว่างถูกปิดใช้งาน")
            actions[item] = "WRITE"
        elif _slot_matches_expected(current, slot, _clean(field.get("value"))):
            actions[item] = "SKIP"
        else:
            raise RuntimeError(
                f"Sample slot {slot}: {field.get('label')} มีค่าใน QAC แล้วแต่ไม่ตรงหรืออ่านค่าไม่แน่ชัด "
                f"(QAC={_clean(state.get('value'))[:120]!r}, requested={_clean(field.get('value'))!r}); "
                "ห้ามเขียนทับและห้ามเลื่อน Slot อัตโนมัติ"
            )
    return actions


def authorize_partial_slot_resume(plan: dict, slot: int, operator_confirmed: bool) -> dict:
    """Select an existing partial slot without changing any QAC result.

    The operator attests to slot ownership; live values are checked again at
    registration. This is not automatic proof of the originating 2D.
    """
    if not operator_confirmed:
        raise RuntimeError("Resume Partial Slot ต้องได้รับการยืนยันจากผู้ปฏิบัติงาน")
    docs = list(plan.get("documents") or [])
    if not docs:
        raise RuntimeError("Resume: ไม่พบเอกสาร")
    warnings = list(plan.get("partial_slot_warnings") or [])
    slot = int(slot)
    if slot < 1:
        raise RuntimeError("Resume: Slot ไม่ถูกต้อง")
    revised_docs = []
    for doc in docs:
        name = str(doc.get("document_name") or "")
        match = [w for w in warnings if int(w.get("slot") or 0) == slot and
                 str(w.get("document_name") or "").casefold() == name.casefold()]
        if len(match) != 1:
            raise RuntimeError(f"Resume: Slot {slot} ไม่ใช่ Partial Slot ที่อ่านได้ใน {name}")
        fields = list(doc.get("schema") or [])
        if not fields:
            raise RuntimeError("Resume: ไม่มีข้อมูล Item")
        for field in fields:
            state = _slot_state(field, slot)
            if state is None:
                raise RuntimeError(f"Resume: ไม่มี Result Row {slot} ใน {field.get('label')}")
            if state.get("empty") and state.get("disabled"):
                raise RuntimeError(f"Resume: Slot {slot} ช่องว่างถูกปิดใช้งาน {field.get('label')}")
        revised_docs.append({**doc, "next_slot": slot})
    return {**plan, "master_slot": slot, "documents": revised_docs,
            "operator_confirmed_partial_slot": slot,
            "partial_slot_owner_attestation": str(plan.get("serial_2d") or "")}


async def _find_module_page(context):
    for page in context.pages:
        try:
            if (await page.evaluate("window.name || ''")) == "QAC_SAMPLE_REGISTER_MODULE":
                return page
        except Exception:
            pass
    return None


async def prepare_sample_registration_async(
    cdp_url: str,
    production_date: str,
    documents: list[dict],
    excel_headers: list[str],
    excel_row_values: dict,
    serial_2d: str,
    sample_type: str,
    progress: Callable[[str], None] | None = None,
    excel_raw_values: list[str] | None = None,
    reserved_plans: list[dict] | None = None,
    source_profile: dict[int, tuple[str, str]] | None = None,
    model: str = "",
    process_master: str = "",
    station: str = "",
    target_process: str = "",
    line: str = "",
) -> dict:
    """Read only from the live QAC UI and build a registration plan.

    QAC field/slot structure is never inferred from cached HTML. Every field and slot
    in the returned plan came from the live Measure page opened from the live task row.
    """
    from playwright.async_api import async_playwright

    def log(msg: str):
        if progress:
            progress(str(msg))

    if not documents:
        raise RuntimeError("ยังไม่ได้เลือก QAC document")

    mapping_master = _load_sample_mapping_master()
    reserved_by_doc = _reserved_slots_from_plans(list(reserved_plans or []))
    raw_values = list(excel_raw_values or [])
    log(f"SAMPLE MAPPING MASTER | {mapping_master['path']} | mode=EXACT_ONLY")
    log(
        f"SAMPLE PREPARE | 2D={serial_2d} | model={model or '-'} | target={target_process or process_master or '-'} | "
        f"sample={sample_type} | documents={len(documents)} | queued={len(reserved_plans or [])}"
    )
    scans = await scan_qac_documents_async(cdp_url, production_date, documents, progress=log, module_tag="QAC_SAMPLE_REGISTER_MODULE")
    missing_docs = [r for r in scans if str(r.get("scan_status") or "") != "FOUND"]
    if missing_docs:
        names = "; ".join(str(r.get("document_name") or "") for r in missing_docs[:10])
        raise RuntimeError(f"QAC document ยังไม่พบ: {names}")

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            if not browser.contexts:
                raise RuntimeError("ไม่พบ QAC Browser Context")
            context = browser.contexts[0]
            module_page = await _find_module_page(context)
            if module_page is None:
                raise RuntimeError("ไม่พบหน้า Production Check Sheet ที่เปิดอยู่")
            await module_page.bring_to_front()
            await install_native_dialog_guard(module_page, log)

            plan_docs: list[dict] = []
            all_next_slots: list[int] = []
            partial_slot_warnings: list[dict] = []
            manual_fields: list[dict] = []
            csv_trace_times: list[str] = []

            for index, result in enumerate(scans, start=1):
                task_id = str(result.get("task_id") or "")
                found_date = str(result.get("found_date") or production_date)
                name = str(result.get("document_name") or "")
                await _reuse_or_restore_task_list(module_page, found_date, log)
                log(f"[{index}/{len(scans)}] SAMPLE SCHEMA | task={task_id} | {name}")

                measure_page = module_page
                pages_before = set(context.pages)
                await _click_measure_action(module_page, task_id, log)
                await module_page.wait_for_timeout(250)
                new_pages = [p for p in context.pages if p not in pages_before]
                if new_pages:
                    measure_page = new_pages[-1]
                    await measure_page.bring_to_front()
                await install_native_dialog_guard(measure_page, log)
                await interaction_checkpoint(measure_page, log, name=f"Sample schema task={task_id}", wait_ms=220)
                schema = await _live_schema(measure_page)
                # Hidden panels can be placeholders. Read actual server results
                # in a bounded batch without opening each item for charts/UI.
                schema = await _read_sample_snapshot(measure_page, schema, task_id, log)
                master_fields = [f for f in schema if _is_sample_type_field(f)]
                if master_fields:
                    live_master = master_fields[0]
                    if live_master is None or not live_master.get("slots"):
                        raise RuntimeError(f"{name}: อ่าน Master Slot จริงไม่ได้หลังเปิด Item")
                    log(f"SAMPLE MASTER OCCUPANCY | {name} | " + ", ".join(
                        f"#{x.get('index')}={'EMPTY' if x.get('empty') else 'USED'}"
                        for x in live_master.get('slots') or []
                    ))
                reserved_slots = reserved_by_doc.get(name.casefold(), set())
                partial_slots = _partial_sample_slots(schema)
                for partial in partial_slots:
                    log(f"SAMPLE PARTIAL SLOT UNVERIFIED | document={name} | "
                        f"slot={partial['slot']} | saved={partial['saved_count']}/{partial['total_count']} | "
                        f"fields={partial['saved_fields']} | owner_2d=UNKNOWN")
                next_slot, active_fields = _doc_next_slot(schema, reserved_slots)
                # Preserve partial slots as blocked; defer operator confirmation
                # until AFTER the one live scan has completed. Never call them
                # owned by the requested 2D based on an electrode number alone.
                for partial in partial_slots:
                    partial_slot_warnings.append({**partial, "document_name": name,
                                                  "owner_2d": "UNKNOWN"})
                log(f"SAMPLE SLOT ALLOCATE | document={name} | next={next_slot} | reserved={sorted(reserved_slots)}")
                if next_slot is None:
                    raise RuntimeError(f"{name}: ไม่พบ slot ว่างใน QAC จริง")
                if next_slot == -1:
                    details = ", ".join(
                        f"{f.get('section')}/{f.get('label')}=>{_first_available_slot(f, reserved_by_doc.get(name.casefold(), set()))}" for f in active_fields[:10]
                    )
                    raise RuntimeError(f"{name}: slot ถัดไปของแต่ละ field ไม่ตรงกัน ({details})")
                all_next_slots.append(next_slot)

                fields_out = []
                for field in active_fields:
                    source_type, source_name, value = _mapped_value_from_verified_master(
                        mapping_master, field, raw_values, sample_type, source_profile,
                        model=model, process_master=process_master, station=station, document_name=name, line=line,
                    )
                    key = f"{_clean(field.get('item'))}|{_canon(field.get('section'))}|{_canon(field.get('label'))}"
                    entry = dict(field)
                    entry.update({
                        "key": key,
                        "excel_column": source_name,
                        "value": value,
                        "source": source_type,
                    })
                    if source_type == "IGNORE":
                        continue
                    # Preserve the original source-file Time independently of
                    # any editable QAC Time value in the review dialog.
                    if _canon(field.get("label")) == "time" and source_type == "CSV" and _clean(value):
                        csv_trace_times.append(_clean(value))
                    fields_out.append(entry)
                    if not value:
                        manual_fields.append({
                            "key": key,
                            "section": field.get("section") or "",
                            "label": field.get("label") or "",
                            "input_format": field.get("input_format") or "",
                            "document_name": name,
                            "source": source_type,
                            "data_item": field.get("item") or "",
                        })

                plan_docs.append({
                    **result,
                    "schema": fields_out,
                    "next_slot": next_slot,
                })

                if measure_page is not module_page:
                    try:
                        await measure_page.close()
                    except Exception:
                        pass
                    await module_page.bring_to_front()
                else:
                    await _return_to_check_sheet(module_page, log, task_id)
                await _reuse_or_restore_task_list(module_page, found_date, log)

            common = sorted(set(all_next_slots))
            if len(common) != 1:
                detail = ", ".join(f"{d.get('document_name')}=>slot {d.get('next_slot')}" for d in plan_docs)
                raise RuntimeError(
                    "QAC จริงไม่มี next empty slot เดียวกันในทุกหน้า; หยุดเพื่อป้องกันข้อมูลเหลื่อม slot: " + detail
                )
            master_slot = common[0]

            # De-duplicate manual prompts by QAC section/label. Unlimited count.
            unique_manual: dict[str, dict] = {}
            for item in manual_fields:
                if item["key"] not in unique_manual:
                    unique_manual[item["key"]] = item
                else:
                    names = unique_manual[item["key"]].setdefault("documents", [])
                    if not names:
                        names.append(str(unique_manual[item["key"]].get("document_name") or ""))
                    names.append(str(item.get("document_name") or ""))

            log(f"SAMPLE SLOT MASTER | slot={master_slot} | pages={len(plan_docs)} | reserved_against={len(reserved_plans or [])}")
            log(f"SAMPLE MISSING | fields={len(unique_manual)}")
            return {
                "serial_2d": serial_2d,
                "model": _clean(model),
                "process_master": _clean(process_master),
                "station": _clean(station),
                "target_process": _clean(target_process),
                "sample_type": sample_type,
                "production_date": production_date,
                "master_slot": master_slot,
                "partial_slot_warnings": partial_slot_warnings,
                "documents": plan_docs,
                "manual_fields": list(unique_manual.values()),
                "excel_row_values": dict(excel_row_values),
                "csv_trace_time": (csv_trace_times[0] if csv_trace_times and len(set(csv_trace_times)) == 1 else ""),
                "source_profile": dict(source_profile or {}),
            }
        finally:
            await browser.close()


def apply_manual_values(plan: dict, manual_values: dict[str, str]) -> dict:
    result = dict(plan)
    docs = []
    for doc in plan.get("documents", []):
        new_doc = dict(doc)
        fields = []
        for field in doc.get("schema", []):
            item = dict(field)
            key = str(item.get("key") or "")
            if key in manual_values:
                # Includes an explicit Time override when CSV supplied the original value.
                item["value"] = _clean(manual_values[key])
                if not _clean(field.get("value")):
                    item["source"] = "MANUAL"
            fields.append(item)
        new_doc["schema"] = fields
        docs.append(new_doc)
    result["documents"] = docs
    result["manual_values"] = dict(manual_values)
    return result


async def _activate_sample_item(page, item: str, log) -> object:
    """Sample-specific navigation; QAC does not auto-advance after Save."""
    return await select_sample_item(page, item, log)


async def _fill_field_at_master_slot(page, fieldset, field: dict, slot: int, log) -> None:
    input_format = str(field.get("input_format") or "")
    value = _clean(field.get("value"))
    label = f"{field.get('section')}/{field.get('label')}"
    if not value:
        raise RuntimeError(f"{label}: ไม่มีค่าก่อน Register")

    await assert_sample_item_context(page, str(field.get("item") or ""), log)
    before = await _result_state(fieldset)
    if input_format == "3":
        # Production Check Sheet actual HTML uses three human-operated buttons
        # for Initial / Middle / Final and result rows carry data-result-no.
        normalized = value.strip().casefold()
        selectors = {
            "initial": ".btn-initial:visible:not([disabled])",
            "middle": ".btn-middle:visible:not([disabled])",
            "final": ".btn-final:visible:not([disabled])",
        }
        selector = selectors.get(normalized)
        if not selector:
            raise RuntimeError(f"{label}: Sample Type ไม่รู้จัก '{value}'")
        button = fieldset.locator(selector).first
        if await button.count() < 1 or not await button.is_visible():
            raise RuntimeError(f"{label}: ไม่พบปุ่ม {value} ที่มองเห็นใน QAC จริง")
        await button.scroll_into_view_if_needed()
        await button.click()
        await page.wait_for_timeout(250)
        log(f"SAMPLE TYPE | slot={slot} | {label} | value={value}")
    elif input_format != "4":
        # Numeric/text/time-like QAC fields expose data-result-no inputs in live QAC.
        # QAC removes saved rows from the editable input list. An ordinal
        # index would write slot 2 into slot 4 once earlier rows are saved.
        target = fieldset.locator(
            f'input[data-result-no="{slot}"]:not([disabled]), '
            f'textarea[data-result-no="{slot}"]:not([disabled])'
        ).first
        if await target.count() != 1:
            raise RuntimeError(f"{label}: slot {slot} ไม่มีช่องกรอกที่แก้ไขได้; ต้องอ่าน Result ก่อน ห้ามเลื่อนไป slot อื่น")
        empty = str(await target.get_attribute("data-empty") or "").lower() == "true"
        current = _clean(await target.input_value())
        if not empty and current:
            if current == value:
                log(f"SAMPLE SLOT SKIP | slot={slot} | {label} | already={current}")
                return
            raise RuntimeError(f"{label}: slot {slot} มีค่าไม่ตรง ({current} != {value})")
        await target.scroll_into_view_if_needed()
        await assert_sample_item_context(page, str(field.get("item") or ""), log)
        await target.fill(value)
        # Use real keyboard events so QAC's own commit handler receives them.
        # QAC's Text handler runs on BOTH Enter and focusout. Enter leaves
        # focus in the input: clicking Save then runs focusout, which hides
        # the button during mousedown and can swallow the subsequent click.
        # Commit Text once by moving focus away before locating Save. Numeric
        # fields retain their existing Enter/chart handling.
        commit_key = "Tab" if await target.get_attribute("type") == "text" else "Enter"
        if commit_key == "Tab":
            await target.press("Tab")
        else:
            await target.press("Enter")
        log(f"SAMPLE INPUT COMMIT | slot={slot} | {label} | key={commit_key}")
        # Do not dispatch synthetic input/change/blur or commit a second time.
        log(f"SAMPLE FILL | slot={slot} | {label} | value={value} | source={field.get('source')}")
    elif input_format == "4":
        # QAC OK/NG controls append to the next empty slot. The preparation phase
        # proves that the next empty slot is identical on every field/page.
        normalized = value.strip().casefold()
        if normalized in {"ok", "o", "pass", "1", "true", "good"}:
            button = fieldset.locator('.btn-ok:visible:not([disabled]), .btn-ok-pd:visible:not([disabled])').first
        elif normalized in {"ng", "x", "fail", "0", "false", "bad"}:
            button = fieldset.locator('.btn-ng:visible:not([disabled]), .btn-ng-pd:visible:not([disabled])').first
        else:
            raise RuntimeError(f"{label}: ค่า OK/NG ไม่รู้จัก '{value}'")
        if await button.count() < 1 or not await button.is_visible():
            raise RuntimeError(f"{label}: ไม่พบปุ่ม OK/NG ที่มองเห็น")
        await button.scroll_into_view_if_needed()
        await button.click()
        await page.wait_for_timeout(250)
        log(f"SAMPLE JUDGE | slot={slot} | {label} | value={value}")
    await assert_sample_item_context(page, str(field.get("item") or ""), log)
    # Sample-only 7-step flow: choose visible fieldset Save, click once, then
    # observe QAC's actual confirm/complete transitions. Never use a fixed short
    # modal sampling window to infer failure or issue a second Save.
    await _sample_save_until_complete(page, fieldset, str(field.get("item") or ""), slot, log)


def _sample_save_diagnostic(item_id: str, slot: int, phase: str, snapshot: dict, log) -> None:
    """Durable read-only diagnostic of the *same* Playwright page; never store inputs."""
    record = {"utc": datetime.now(timezone.utc).isoformat(), "item": item_id,
              "slot": slot, "phase": phase, "dom": snapshot}
    try:
        root = Path(program_dir()) / "logs"
        root.mkdir(parents=True, exist_ok=True)
        filename = root / f"sample_save_dom_{datetime.now().strftime('%Y%m%d')}.jsonl"
        with filename.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        log(f"SAMPLE SAVE DIAGNOSTIC | item={item_id} slot={slot} phase={phase} file={filename}")
    except Exception as exc:
        log(f"SAMPLE SAVE DIAGNOSTIC WRITE ERROR | item={item_id} slot={slot} {type(exc).__name__}: {exc}")


async def _sample_save_until_complete(page, fieldset, item_id: str, slot: int, log) -> None:
    """Complete is the final acknowledgement; do not re-open or read back the item.

    A Save click is NOT success. Timeouts after the click are UNCERTAIN and
    intentionally never retried automatically (avoids a duplicate QAC result).
    """
    await install_native_dialog_guard(page, log)
    await assert_sample_item_context(page, item_id, log)
    # Do not auto-acknowledge here: committing the last input can itself open
    # QAC's Save confirmation. The state machine below must own that popup.
    # Committing an input enables/shows Save asynchronously. Wait for that
    # *actual DOM state*, not an immediate snapshot after the keypress.
    # Keep this selector scoped to the verified item panel.
    # QAC ships both .btn-save and .btn-save-text in the same panel, often
    # hiding one with display:none. Query BOTH from the current fieldset and
    # evaluate computed visibility in the *live DOM* after Enter.
    # Never click a hidden button or reuse a locator from a previous item.
    # Reacquire the panel in the *same browser page* every poll.  The user DOM
    # capture proved the active Time item 460918 exposes exactly one visible
    # .btn-save about 300 ms after Enter, while .btn-save-text remains hidden.
    # A previously captured fieldset locator can refer to a detached/replaced
    # QAC panel; resolve it by data-item and the active sidebar on every read.
    selector = f'.fieldsets > .fieldset[data-item="{item_id}"]'
    save_candidates = page.locator(f'{selector} button.btn-save, {selector} button.btn-save-text')
    deadline_ready = asyncio.get_running_loop().time() + 20.0
    last_snapshot = {}
    previous_signature = None
    ready_index = None
    qac_started_save = False
    poll = 0
    _sample_save_diagnostic(item_id, slot, "BEFORE_POLL", {"selector": selector}, log)
    while asyncio.get_running_loop().time() < deadline_ready:
        poll += 1
        modal = await inspect_visible_qac_modal(page)
        if modal.kind in ("CONFIRM", "BUSY", "INFO"):
            qac_started_save = True
            log(f"SAMPLE SAVE QAC STARTED | item={item_id} slot={slot} state={modal.kind}; no extra Save click")
            break
        if modal.kind in ("ERROR", "WARNING", "UNKNOWN"):
            raise RuntimeError(f"SAMPLE SAVE UNSAFE MODAL | item={item_id} slot={slot} kind={modal.kind}")
        # Read the DOM from the exact browser page that executes registration.
        # There are two save buttons in Text items, and the QAC 'visible'
        # state is defined by computed visibility INCLUDING ancestors.
        last_snapshot = await page.evaluate("""expected => {
          const activeStep = document.querySelector('.f1-step.active[data-item]');
          const panels = Array.from(document.querySelectorAll('.fieldsets > .fieldset[data-item]'));
          const matches = panels.filter(p => p.getAttribute('data-item') === expected);
          const visible = element => {
            if (!element || !element.isConnected) return false;
            const style = getComputedStyle(element), rect = element.getBoundingClientRect();
            if (style.display === 'none' || ['hidden','collapse'].includes(style.visibility) ||
                rect.width <= 0 || rect.height <= 0) return false;
            for (let parent = element.parentElement; parent; parent = parent.parentElement) {
              const ps = getComputedStyle(parent);
              if (ps.display === 'none' || ['hidden','collapse'].includes(ps.visibility)) return false;
            }
            return true;
          };
          const panel = matches.find(visible);
          const buttons = panel ? Array.from(panel.querySelectorAll('button.btn-save, button.btn-save-text')) : [];
          const states = buttons.map((b, index) => {
            const st = getComputedStyle(b), rect = b.getBoundingClientRect();
            const shown = visible(b);
            return {index, cls:b.className, inline:b.getAttribute('style') || '',
              display:st.display, visibility:st.visibility,
              width:Math.round(rect.width), height:Math.round(rect.height),
              disabled:b.disabled, ancestorHidden:!shown && st.display !== 'none',
              ready:shown && !b.disabled};
          });
          const focus = document.activeElement;
          return {activeItem:activeStep?.getAttribute('data-item') || '', target:expected,
            panels:matches.length, panelVisible:!!panel,
            focusTag:focus?.tagName || '', focusSlot:focus?.getAttribute?.('data-result-no') || '',
            buttons:states};
        }""", item_id)
        if last_snapshot['activeItem'] != item_id:
            _sample_save_diagnostic(item_id, slot, "FOCUS_DRIFT", last_snapshot, log)
            raise RuntimeError(f"SAMPLE SAVE FOCUS DRIFT | item={item_id} slot={slot} dom={last_snapshot}")
        ready = [entry for entry in last_snapshot['buttons'] if entry['ready']]
        # Log every change of visibility and heartbeat at 1.5s; the file
        # persists even when QAC never shows a Save button.
        signature = json.dumps(last_snapshot, sort_keys=True)
        if signature != previous_signature or poll % 10 == 0:
            previous_signature = signature
            _sample_save_diagnostic(item_id, slot, "DOM_WAIT", last_snapshot, log)
        if len(ready) == 1 and last_snapshot['panelVisible']:
            ready_index = ready[0]['index']
            break
        if len(ready) > 1:
            _sample_save_diagnostic(item_id, slot, "AMBIGUOUS", last_snapshot, log)
            raise RuntimeError(f"SAMPLE SAVE AMBIGUOUS | item={item_id} slot={slot} dom={last_snapshot}")
        if poll == 1 or poll % 10 == 0:
            log(f"SAMPLE SAVE DOM WAIT | item={item_id} slot={slot} poll={poll} state={last_snapshot}")
        await page.wait_for_timeout(150)
    if ready_index is None and not qac_started_save:
        _sample_save_diagnostic(item_id, slot, "NOT_READY", last_snapshot, log)
        raise RuntimeError(f"SAMPLE SAVE NOT READY | item={item_id} slot={slot} dom={last_snapshot} | waited_for_dom=20s")
    # Item-specific fresh locator; do not select a hidden Text button or a
    # Save belonging to another result panel.
    if not qac_started_save:
        _sample_save_diagnostic(item_id, slot, "READY", last_snapshot, log)
        log(f"SAMPLE SAVE READY | item={item_id} slot={slot} poll={poll} dom={last_snapshot}")
        save = save_candidates.nth(ready_index)
        await assert_sample_item_context(page, item_id, log)
        if not await save.is_visible() or not await save.is_enabled():
            _sample_save_diagnostic(item_id, slot, "CHANGED_BEFORE_CLICK", last_snapshot, log)
            raise RuntimeError(f"SAMPLE SAVE CHANGED BEFORE CLICK | item={item_id} slot={slot} dom={last_snapshot}; no save issued")
        await save.scroll_into_view_if_needed()
        _sample_save_diagnostic(item_id, slot, "CLICK_ATTEMPT", last_snapshot, log)
        await save.click(timeout=10000, no_wait_after=True)
        _sample_save_diagnostic(item_id, slot, "CLICKED", last_snapshot, log)
        log(f"SAMPLE SAVE CLICK | item={item_id} slot={slot}")
    deadline = asyncio.get_running_loop().time() + 25.0
    confirmed = False
    completed = False
    last_kind = "NONE"
    while asyncio.get_running_loop().time() < deadline:
        state = await inspect_visible_qac_modal(page)
        kind = state.kind
        label = str(state.title or state.content or state.text or "")
        if kind != last_kind:
            log(f"SAMPLE SAVE MODAL | item={item_id} slot={slot} state={kind} text={label[:160]}")
            last_kind = kind
        if kind in ("ERROR", "WARNING", "UNKNOWN"):
            raise RuntimeError(f"SAMPLE SAVE UNSAFE MODAL | item={item_id} slot={slot} kind={kind} {label[:200]}")
        if kind in ("NONE", "BUSY"):
            await page.wait_for_timeout(120)
            continue
        if kind == "CONFIRM":
            if confirmed:
                raise RuntimeError(f"SAMPLE SAVE REPEATED CONFIRM | item={item_id} slot={slot}")
            button = await _find_affirmative_button(state, page)
            if button is None:
                raise RuntimeError(f"SAMPLE CONFIRM BUTTON MISSING | item={item_id} slot={slot}")
            await button.click(timeout=10000, no_wait_after=True)
            confirmed = True
            log(f"SAMPLE SAVE CONFIRM | item={item_id} slot={slot}")
            await page.wait_for_timeout(100)
            continue
        if kind == "INFO":
            normalized = label.casefold()
            if not any(word in normalized for word in ("complete", "completed", "บันทึกสำเร็จ")):
                raise RuntimeError(f"SAMPLE SAVE UNEXPECTED INFO | item={item_id} slot={slot} {label[:200]}")
            completed = True
            log(f"SAMPLE SAVE COMPLETE ACK | item={item_id} slot={slot} confirmed={int(confirmed)}")
            button = await _find_affirmative_button(state, page)
            if button is not None:
                try:
                    await button.click(timeout=4000, no_wait_after=True)
                    log(f"SAMPLE COMPLETE DISMISSED | item={item_id} slot={slot}")
                except Exception:
                    # QAC sometimes auto-removes Complete! during the click.
                    # It was already observed; never click Save again.
                    log(f"SAMPLE COMPLETE AUTO DISMISSED | item={item_id} slot={slot}")
            break
    if not completed:
        raise RuntimeError(
            f"SAMPLE SAVE ACK UNKNOWN | item={item_id} slot={slot} "
            f"confirmed={int(confirmed)} complete=0 | ห้ามกด Save ซ้ำอัตโนมัติ"
        )
    log(f"SAMPLE SAVE COMPLETE | item={item_id} slot={slot} | QAC Complete! | no readback")


async def execute_sample_batch_registration_async(
    cdp_url: str,
    plans: list[dict],
    progress: Callable[[str], None] | None = None,
) -> dict:
    """Execute already prepared samples sequentially.

    Each plan is revalidated against live QAC by execute_sample_registration_async.
    If any sample fails, the batch stops immediately; later samples are not touched.
    """
    def log(msg: str):
        if progress:
            progress(str(msg))
    plans = list(plans or [])
    if not plans:
        raise RuntimeError("ไม่มี Sample ที่เตรียมไว้")
    completed = []
    for idx, plan in enumerate(plans, start=1):
        log(f"BATCH SAMPLE START | {idx}/{len(plans)} | 2D={plan.get('serial_2d')} | sample={plan.get('sample_type')} | slot={plan.get('master_slot')}")
        result = await execute_sample_registration_async(cdp_url, plan, progress=log)
        completed.append({"plan": plan, "result": result})
        log(f"BATCH SAMPLE COMPLETE | {idx}/{len(plans)} | 2D={plan.get('serial_2d')} | slot={plan.get('master_slot')}")
    log(f"BATCH REGISTER DONE | samples={len(completed)}")
    return {"samples": len(completed), "completed": completed}


async def _post_sample_trace_comment(page, serial_2d: str, sample_time: str, log) -> None:
    """Post trace once, only after all QAC field saves succeeded; check for existing comment.

    Failure is explicit: caller must not treat the document as fully registered.
    """
    serial = _clean(serial_2d)
    sample_time = _clean(sample_time)
    if not serial or not sample_time:
        raise RuntimeError("SAMPLE TRACE requires 2D and editable sample time")
    # Stable marker allows retry without posting a duplicate.
    marker = f"[QAC-SAMPLE-TRACE] 2D={serial} | Time={sample_time}"
    info = page.locator('.f1-step.active .fa-info').first
    if await info.count() == 0:
        info = page.locator('.f1-step .fa-info').first
    if await info.count() != 1:
        raise RuntimeError("SAMPLE TRACE: task information navigation missing")
    await info.click()
    panel = page.locator('.task-infomation.fieldset').first
    await panel.wait_for(state='visible', timeout=5000)
    # Only the comment thread in Task Information, not inspection fieldset comments.
    existing = await panel.locator('.box-comments').all_text_contents()
    if any(marker in text for text in existing):
        log(f"SAMPLE TRACE ALREADY POSTED | {marker}")
        return
    textarea = panel.locator('textarea[placeholder="Press enter to post comment"]').first
    post = panel.locator('.box-comment .btn.btn-primary:has(.fa-envelope-o)').first
    if await textarea.count() != 1 or await post.count() != 1:
        raise RuntimeError("SAMPLE TRACE: comment editor or Post missing")
    await textarea.fill(marker)
    await post.click()
    # Re-read server-rendered comments to confirm persistence; don't post twice on uncertain state.
    for _ in range(12):
        await page.wait_for_timeout(250)
        comments = await panel.locator('.box-comments').all_text_contents()
        if any(marker in txt for txt in comments):
            log(f"SAMPLE TRACE POST VERIFIED | {marker}")
            return
    raise RuntimeError(f"SAMPLE TRACE POST UNVERIFIED | {marker} | do not retry Post automatically")


def sample_time_from_plan(plan: dict) -> str:
    """Return original source-file Time for QAC trace comment, not edited QAC Time.

    New prepares carry a protected CSV snapshot. Legacy pending prepares may be
    accepted only if their Time field still explicitly has CSV provenance.
    """
    original = _clean(plan.get("csv_trace_time"))
    if original:
        return original
    values = [str(f.get("value") or "").strip() for d in plan.get("documents", [])
              for f in d.get("schema", [])
              if _canon(f.get("label", "")) == "time" and f.get("source") == "CSV"]
    if values and all(values) and len(set(values)) == 1 and not plan.get("manual_values"):
        return values[0]
    raise RuntimeError("SAMPLE TRACE: ไม่พบเวลาในไฟล์ CSV ที่ยืนยันได้; ไม่ใช้เวลาที่แก้ใน QAC แทน")


async def execute_sample_registration_async(
    cdp_url: str,
    plan: dict,
    progress: Callable[[str], None] | None = None,
) -> dict:
    from playwright.async_api import async_playwright

    def log(msg: str):
        if progress:
            progress(str(msg))

    master_slot = int(plan.get("master_slot") or 0)
    if master_slot < 1:
        raise RuntimeError("Master slot ไม่ถูกต้อง")
    documents = list(plan.get("documents") or [])
    if not documents:
        raise RuntimeError("Registration plan ไม่มี document")
    csv_trace_time = sample_time_from_plan(plan)  # fail before QAC writes if provenance is absent
    authorized_slot = int(plan.get("operator_confirmed_partial_slot") or 0)
    if authorized_slot and (authorized_slot != master_slot or
            str(plan.get("partial_slot_owner_attestation") or "") != str(plan.get("serial_2d") or "")):
        raise RuntimeError("Resume Partial Slot: การยืนยันผู้ปฏิบัติงานไม่ตรงกับ 2D/Slot")

    async with async_playwright() as pw:
        browser = await pw.chromium.connect_over_cdp(cdp_url)
        try:
            context = browser.contexts[0]
            module_page = await _find_module_page(context)
            if module_page is None:
                raise RuntimeError("ไม่พบหน้า Production Check Sheet")
            await module_page.bring_to_front()
            await install_native_dialog_guard(module_page, log)

            completed = []
            for idx, doc in enumerate(documents, start=1):
                task_id = str(doc.get("task_id") or "")
                name = str(doc.get("document_name") or "")
                task_date = str(doc.get("found_date") or plan.get("production_date") or "")
                if int(doc.get("next_slot") or 0) != master_slot:
                    raise RuntimeError(f"{name}: slot plan เปลี่ยนจาก master slot")
                # A prior partial run may leave the same module session on Measure.
                # Restore only when URL + visible Measure fieldsets prove the page.
                if await module_page.locator("i.calendar-monitor:visible").count() == 0:
                    url = str(getattr(module_page, "url", "") or "")
                    if "measure.html" in url.casefold() and await module_page.locator(".fieldset[data-item]:visible").count() > 0:
                        log(f"SAMPLE REGISTER RESTORE | interrupted Measure | {url}")
                        await module_page.go_back(wait_until="commit", timeout=15000)
                        await _wait_qac_complete(module_page, log, "Restore Sample Register", ready_selector="i.calendar-monitor:visible")
                        if await module_page.locator("i.calendar-monitor:visible").count() != 1:
                            raise RuntimeError("Sample Register restore: Check Sheet calendar not verified")
                    else:
                        raise RuntimeError(f"Sample Register wrong page: {url}")
                await _reuse_or_restore_task_list(module_page, task_date, log)
                log(f"[{idx}/{len(documents)}] SAMPLE REGISTER | slot={master_slot} | task={task_id} | {name}")

                measure_page = module_page
                pages_before = set(context.pages)
                await _click_measure_action(module_page, task_id, log)
                await module_page.wait_for_timeout(250)
                new_pages = [p for p in context.pages if p not in pages_before]
                if new_pages:
                    measure_page = new_pages[-1]
                    await measure_page.bring_to_front()
                await install_native_dialog_guard(measure_page, log)
                await interaction_checkpoint(measure_page, log, name=f"Sample register task={task_id}", wait_ms=220)
                # Prepare has already scanned every item and captured each
                # exact Result/slot. Do not reopen all 12 items on Register.
                # Each WRITE still rechecks its own live target immediately
                # before filling; the Save path observes Confirm + Complete.
                prepared_fields = list(doc.get("schema", []))
                actions = _validate_registration_slot(prepared_fields, prepared_fields, master_slot)
                log(f"SAMPLE PREPARED SNAPSHOT REUSED | slot={master_slot} | items={len(prepared_fields)}")
                log(f"SAMPLE SLOT CHECK | slot={master_slot} | existing={sum(v == 'SKIP' for v in actions.values())} | missing={sum(v == 'WRITE' for v in actions.values())}")
                if any(v == "SKIP" for v in actions.values()):
                    # Occupied type alone cannot prove 2D identity.  A later
                    # trace comment allows retries with positive attribution.
                    log(f"SAMPLE PARTIAL SLOT | slot={master_slot} | validate QAC contents; preserve slot")
                for field in doc.get("schema", []):
                    item = str(field.get("item") or "")
                    if actions[item] == "SKIP":
                        log(f"SAMPLE SLOT SKIP | slot={master_slot} | {field.get('section')}/{field.get('label')} | already saved")
                        continue
                    fieldset = await _activate_sample_item(measure_page, item, log)
                    current = next((x for x in await _live_schema(measure_page) if str(x.get("item")) == item), None)
                    if current is None or _slot_state(current, master_slot) is None:
                        await _activate_sample_item_force(measure_page, item, log)
                        current = next((x for x in await _live_schema(measure_page) if str(x.get("item")) == item), None)
                    if current is None or _slot_state(current, master_slot) is None:
                        raise RuntimeError(f"SAMPLE SLOT UNKNOWN | item={item} slot={master_slot} | no result row after reopen")
                    if _slot_matches_expected(current, master_slot, _clean(field.get("value"))):
                        log(f"SAMPLE SLOT SKIP VERIFIED | item={item} slot={master_slot}")
                        continue
                    if not _slot_state(current, master_slot).get("empty"):
                        raise RuntimeError(f"SAMPLE SLOT CONFLICT | item={item} slot={master_slot} | existing result differs")
                    await _fill_field_at_master_slot(measure_page, fieldset, field, master_slot, log)

                # Do not reopen every QAC item for a final audit. Each WRITE
                # requires QAC Confirm + Complete!; SKIP was checked against
                # the target slot before any writes. The trace is posted once.
                log(f"SAMPLE REGISTER ACK SUMMARY | slot={master_slot} | "
                    f"writes={sum(v == 'WRITE' for v in actions.values())} | "
                    f"skips={sum(v == 'SKIP' for v in actions.values())} | "
                    "verification=QAC_COMPLETE_ONLY")
                await _post_sample_trace_comment(measure_page, plan.get("serial_2d", ""), csv_trace_time, log)
                completed.append({"task_id": task_id, "document_name": name, "slot": master_slot})
                if measure_page is not module_page:
                    try:
                        await measure_page.close()
                    except Exception:
                        pass
                    await module_page.bring_to_front()
                else:
                    await _return_to_check_sheet(module_page, log, task_id)
                await _reuse_or_restore_task_list(module_page, task_date, log)

            log(f"SAMPLE REGISTER DONE | documents={len(completed)} | slot={master_slot}")
            return {
                "serial_2d": plan.get("serial_2d"),
                "sample_type": plan.get("sample_type"),
                "master_slot": master_slot,
                "completed": completed,
            }
        finally:
            await browser.close()

from __future__ import annotations

import csv
from pathlib import Path


ALIASES = {
    "document_name": {"document_name", "document", "document name", "doc name"},
    "document_no": {"document_no", "document no", "document number", "doc no"},
    "section": {"section", "inspection no", "inspection", "no"},
    "label": {"label", "item", "inspection item", "check item"},
    "slot": {"slot", "result_no", "result no", "sample", "sample no"},
    "value": {"value", "result", "input", "measure", "measurement"},
    "judge": {"judge", "okng", "ok/ng", "status"},
}


def _norm(value) -> str:
    return " ".join(str(value or "").replace("_", " ").split()).casefold()


def _header_map(headers) -> dict[str, int]:
    normalized = [_norm(value) for value in headers]
    result = {}
    for key, aliases in ALIASES.items():
        for index, value in enumerate(normalized):
            if value in aliases:
                result[key] = index
                break
    if "value" not in result and "judge" not in result:
        raise RuntimeError("Import file ต้องมีคอลัมน์ Value/Result หรือ Judge/OKNG อย่างน้อย 1 คอลัมน์")
    return result


def _row_to_record(values, hm: dict[str, int]) -> dict:
    def get(key: str) -> str:
        index = hm.get(key)
        if index is None or index >= len(values):
            return ""
        return str(values[index] or "").strip()

    value = get("value")
    judge = get("judge")
    if not value and judge:
        value = judge.upper()
    return {
        "document_name": get("document_name"),
        "document_no": get("document_no"),
        "section": get("section"),
        "label": get("label"),
        "slot": get("slot") or "1",
        "value": value,
        "judge": judge,
    }


def _load_csv(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        return []
    hm = _header_map(rows[0])
    return [
        record
        for values in rows[1:]
        if (record := _row_to_record(values, hm)).get("value")
    ]


def _load_xlsx(path: Path) -> list[dict]:
    from openpyxl import load_workbook

    wb = load_workbook(path, read_only=True, data_only=True)
    try:
        ws = wb[wb.sheetnames[0]]
        rows = ws.iter_rows(values_only=True)
        try:
            headers = next(rows)
        except StopIteration:
            return []
        hm = _header_map(headers)
        records = []
        for values in rows:
            record = _row_to_record(values, hm)
            if record.get("value"):
                records.append(record)
        return records
    finally:
        wb.close()


def load_checksheet_value_file(path_value: str | Path) -> list[dict]:
    path = Path(path_value).expanduser().resolve()
    if not path.exists():
        raise RuntimeError(f"ไม่พบไฟล์ข้อมูล: {path}")
    if path.suffix.lower() in {".xlsx", ".xlsm"}:
        return _load_xlsx(path)
    if path.suffix.lower() == ".csv":
        return _load_csv(path)
    raise RuntimeError("รองรับไฟล์ข้อมูลเฉพาะ .csv, .xlsx, .xlsm")


def latest_value_map_from_schemas(schemas: list[dict]) -> dict[tuple[str, str, str], str]:
    """Map (document_name, section, label) to latest non-empty value."""
    result: dict[tuple[str, str, str], str] = {}
    for schema in schemas:
        document_name = str(schema.get("document_name") or "")
        for field in schema.get("fields", []) or []:
            value = str(field.get("latest_value") or "").strip()
            if not value:
                continue
            key = (
                _norm(document_name),
                _norm(field.get("section")),
                _norm(field.get("label")),
            )
            result[key] = value
    return result

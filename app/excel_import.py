from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from openpyxl import load_workbook


@dataclass
class AlarmRow:
    source_file: str
    source_row: int
    column_b_time: str
    alarm_code: str
    message: str
    machine_code: str
    time_stop: str

    @property
    def description(self) -> str:
        # Required QAC description format.
        return f"Machine Alarm {self.message} No Action Monitor Run"


def _clean(value) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _time_plus_one_minute(value: str) -> str:
    value = _clean(value)
    formats = ("%H:%M:%S", "%H:%M")

    for fmt in formats:
        try:
            dt = datetime.strptime(value, fmt)
            out = dt + timedelta(minutes=1)
            return out.strftime("%H:%M:%S" if fmt == "%H:%M:%S" else "%H:%M")
        except ValueError:
            continue

    raise ValueError(f"รูปแบบเวลา Column B ไม่ถูกต้อง: {value}")


def _row_to_alarm(values, source_file: str, row_no: int) -> AlarmRow:
    vals = list(values) + [""] * max(0, 6 - len(values))

    b = _clean(vals[1])
    d = _clean(vals[3])
    e = _clean(vals[4])
    f = _clean(vals[5])

    if not b and not d and not e and not f:
        raise ValueError("EMPTY_ROW")

    if not b:
        raise ValueError(f"{source_file} row {row_no}: Column B (Time) ว่าง")
    if not e:
        raise ValueError(f"{source_file} row {row_no}: Column E (Message) ว่าง")
    if not f:
        raise ValueError(f"{source_file} row {row_no}: Column F (Machine Code) ว่าง")

    return AlarmRow(
        source_file=source_file,
        source_row=row_no,
        column_b_time=b,
        alarm_code=d,
        message=e,
        machine_code=f,
        time_stop=_time_plus_one_minute(b),
    )


def _read_csv(path: Path):
    rows = []
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.reader(f)
        for row_no, values in enumerate(reader, 1):
            try:
                rows.append(_row_to_alarm(values, path.name, row_no))
            except ValueError as e:
                if str(e) == "EMPTY_ROW":
                    continue
                raise
    return rows


def _read_xlsx(path: Path):
    rows = []
    wb = load_workbook(path, read_only=True, data_only=True)
    ws = wb[wb.sheetnames[0]]

    for row_no, values in enumerate(ws.iter_rows(values_only=True), 1):
        try:
            rows.append(_row_to_alarm(values, path.name, row_no))
        except ValueError as e:
            if str(e) == "EMPTY_ROW":
                continue
            raise

    return rows


def load_alarm_files(paths: list[str]) -> list[AlarmRow]:
    all_rows = []

    for raw in paths:
        path = Path(raw)
        suffix = path.suffix.lower()

        if suffix == ".csv":
            rows = _read_csv(path)
        elif suffix in (".xlsx", ".xlsm"):
            rows = _read_xlsx(path)
        else:
            raise ValueError(f"ไม่รองรับไฟล์: {path.name}")

        all_rows.extend(rows)

    return all_rows

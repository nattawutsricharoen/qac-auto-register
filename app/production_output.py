from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, date, time
from pathlib import Path
from collections import Counter
import csv
import re

from openpyxl import load_workbook


@dataclass
class HourlyProduction:
    interval_start: str
    interval_end: str
    qac_event_time: str
    qty: int
    rejected: int = 0
    gross: int = 0


@dataclass
class ProductionLineData:
    source_file: str
    sheet_name: str
    production_date: date
    shift_name: str
    shift_start: str
    shift_end: str
    model_hint: str
    line_no_hint: int | None
    first_datetime: datetime
    last_datetime: datetime
    counted_total: int
    workbook_total: int | None
    reject_total: int
    hourly: list[HourlyProduction]
    warnings: list[str]


def _norm_header(value) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _find_header(ws):
    for row_no in range(1, min(ws.max_row, 25) + 1):
        date_col = None
        serial_col = None

        for col_no in range(1, min(ws.max_column, 30) + 1):
            text = _norm_header(ws.cell(row_no, col_no).value)

            if text in ("date/time", "datetime", "date time"):
                date_col = col_no

            if (
                "serial(temporary)" in text
                or "serial (temporary)" in text
            ):
                serial_col = col_no

        if date_col and serial_col:
            return row_no, date_col, serial_col

    raise ValueError(
        "ไม่พบ Header Date/Time และ Serial(Temporary)"
    )


def _to_datetime(value):
    if isinstance(value, datetime):
        return value

    if isinstance(value, date):
        return datetime.combine(value, time.min)

    raw = str(value or "").strip()

    for fmt in (
        "%Y-%m-%d %H:%M:%S",
        "%d/%m/%Y %H:%M:%S",
        "%Y/%m/%d %H:%M:%S",
        "%d-%m-%Y %H:%M:%S",
    ):
        try:
            return datetime.strptime(raw, fmt)
        except ValueError:
            pass

    return None


def _parse_filename_hint(path: Path):
    stem = path.stem
    shift = ""

    if "night" in stem.lower():
        shift = "Night"
    elif "day" in stem.lower():
        shift = "Day"

    model_hint = ""
    line_no = None

    # 20260819-SC12-2CR(Night).xlsx -> SC1 / line 2
    m = re.search(
        r"-(?P<model>[A-Za-z]+\d)(?P<line>[1-7])(?:-|_)",
        stem
    )

    if m:
        model_hint = m.group("model").upper()
        line_no = int(m.group("line"))

    return shift, model_hint, line_no


def _hour_range(shift_start: str):
    start_h, start_m = map(int, shift_start.split(":"))

    if start_m != 0:
        raise ValueError("Shift start ต้องเป็นชั่วโมงเต็ม")

    return [
        (start_h + offset) % 24
        for offset in range(12)
    ]


def _read_csv_rows(path: Path):
    last_error = None

    for encoding in (
        "utf-8-sig",
        "utf-8",
        "cp932",
        "cp874",
        "latin-1",
    ):
        try:
            with path.open(
                "r",
                encoding=encoding,
                newline=""
            ) as f:
                sample = f.read(8192)
                f.seek(0)

                try:
                    dialect = csv.Sniffer().sniff(
                        sample,
                        delimiters=",;\t|"
                    )
                except Exception:
                    dialect = csv.excel

                rows = list(
                    csv.reader(
                        f,
                        dialect
                    )
                )

            if rows:
                return rows

        except Exception as e:
            last_error = e

    raise ValueError(
        f"อ่าน CSV ไม่สำเร็จ: {last_error}"
    )


def _load_csv_records(path: Path):
    rows = _read_csv_rows(path)

    header_index = None
    date_col = None
    serial_col = None

    for rno, row in enumerate(
        rows[:25]
    ):
        for cno, value in enumerate(row):
            text = _norm_header(value)

            if text in (
                "date/time",
                "datetime",
                "date time",
            ):
                date_col = cno

            if (
                "serial(temporary)" in text
                or "serial (temporary)" in text
            ):
                serial_col = cno

        if (
            date_col is not None
            and serial_col is not None
        ):
            header_index = rno
            break

    if header_index is None:
        raise ValueError(
            "CSV: ไม่พบ Header Date/Time "
            "และ Serial(Temporary)"
        )

    records = []

    for row in rows[
        header_index + 1:
    ]:
        dt = _to_datetime(
            row[date_col]
            if date_col < len(row)
            else None
        )
        serial = str(
            (
                row[serial_col]
                if serial_col < len(row)
                else None
            )
            or ""
        ).strip()

        if dt is not None and serial:
            records.append(
                (dt, serial, is_reject_marker(_last_nonempty(row[serial_col + 1:])))
            )

    return records, "CSV", None


def is_reject_marker(value) -> bool:
    """Reject comment in the trailing annotation column; do not treat ordinary measurements as reject."""
    return bool(re.search(r"\breject(?:ed|ion)?\b", str(value or ""), re.IGNORECASE))


def _last_nonempty(values):
    return next((v for v in reversed(values) if v is not None and str(v).strip()), None)


def load_production_line_file(
    raw_path: str,
    day_start: str = "08:00",
    day_end: str = "20:00",
    night_start: str = "20:00",
    night_end: str = "08:00",
) -> ProductionLineData:
    path = Path(raw_path)

    suffix = path.suffix.lower()

    if suffix not in (
        ".xlsx",
        ".xlsm",
        ".csv",
    ):
        raise ValueError(
            f"รองรับ XLSX/XLSM/CSV: {path.name}"
        )

    workbook_total = None

    if suffix == ".csv":
        (
            records,
            sheet_name,
            workbook_total,
        ) = _load_csv_records(path)
        ws = None
    else:
        wb = load_workbook(
            path,
            read_only=True,
            data_only=True
        )
        ws = wb[
            wb.sheetnames[0]
        ]

        sheet_name = ws.title
        header_row, date_col, serial_col = (
            _find_header(ws)
        )

        records = []

        for values in ws.iter_rows(
            min_row=header_row + 1,
            values_only=True
        ):
            dt = _to_datetime(
                values[date_col - 1]
                if len(values) >= date_col
                else None
            )
            serial = str(
                (
                    values[serial_col - 1]
                    if len(values) >= serial_col
                    else None
                )
                or ""
            ).strip()

            # COUNTA: every non-empty Serial(Temporary) row is counted.
            if dt is not None and serial:
                records.append((dt, serial, is_reject_marker(_last_nonempty(values[serial_col:]))))

    if not records:
        raise ValueError(
            "ไม่พบข้อมูล Date/Time + Serial(Temporary)"
        )

    records.sort(key=lambda item: item[0])

    first_dt = records[0][0]
    last_dt = records[-1][0]

    filename_shift, model_hint, line_no_hint = (
        _parse_filename_hint(path)
    )

    if filename_shift:
        shift_name = filename_shift
    else:
        shift_name = (
            "Night"
            if first_dt.hour >= 20 or first_dt.hour < 8
            else "Day"
        )

    if shift_name == "Night":
        shift_start = night_start
        shift_end = night_end
    else:
        shift_start = day_start
        shift_end = day_end

    gross_counts = Counter(dt.hour for dt, _, _ in records)
    reject_counts = Counter(dt.hour for dt, _, reject in records if reject)
    counts = gross_counts - reject_counts

    hourly = []

    for hour in _hour_range(shift_start):
        end_hour = (hour + 1) % 24

        hourly.append(
            HourlyProduction(
                interval_start=f"{hour:02d}:00",
                interval_end=f"{end_hour:02d}:00",
                # QAC Production Output point is the END of the interval.
                qac_event_time=f"{end_hour:02d}:00",
                qty=int(counts.get(hour, 0)),
                rejected=int(reject_counts.get(hour, 0)),
                gross=int(gross_counts.get(hour, 0)),
            )
        )

    if ws is not None:
        try:
            raw_total = ws.cell(1, 3).value
            if (
                raw_total is not None
                and str(raw_total).strip()
            ):
                workbook_total = int(
                    float(raw_total)
                )
        except Exception:
            workbook_total = None

    counted_total = sum(counts.values())
    reject_total = sum(reject_counts.values())
    warnings = []

    if (
        workbook_total is not None
        and workbook_total not in (counted_total, len(records))
    ):
        warnings.append(
            f"Workbook Total={workbook_total} "
            f"แต่ Gross Serial={len(records)} Net={counted_total} Reject={reject_total}"
        )

    return ProductionLineData(
        source_file=path.name,
        sheet_name=sheet_name,
        production_date=first_dt.date(),
        shift_name=shift_name,
        shift_start=shift_start,
        shift_end=shift_end,
        model_hint=model_hint,
        line_no_hint=line_no_hint,
        first_datetime=first_dt,
        last_datetime=last_dt,
        counted_total=counted_total,
        reject_total=reject_total,
        workbook_total=workbook_total,
        hourly=hourly,
        warnings=warnings,
    )

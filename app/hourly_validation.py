from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
import re
import sqlite3

from .runtime_paths import program_dir


@dataclass
class ValidationResult:
    status: str
    mct_sec: float | None
    total_stations: int
    expected_qty: float
    actual_qty: int
    recorded_event_min: float
    partial_capacity_min: float
    unexplained_min: float
    accounted_min: float
    effective_mct_sec: float | None
    average_capacity: float
    conflicts: list[str]
    html_events: list[dict]
    manual_events: list[dict]


class ManualEventStore:
    def __init__(self, path: str | Path | None = None):
        self.path = Path(path or (program_dir() / "hourly_validation.db"))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self):
        con = sqlite3.connect(self.path)
        con.row_factory = sqlite3.Row
        return con

    def _init_db(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS manual_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    production_date TEXT NOT NULL,
                    line TEXT NOT NULL,
                    model TEXT NOT NULL,
                    hour_start TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    downtime_value TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '',
                    category_value TEXT NOT NULL DEFAULT '',
                    machine TEXT NOT NULL DEFAULT '',
                    machine_value TEXT NOT NULL DEFAULT '',
                    loss_mode TEXT NOT NULL DEFAULT 'TIME_LOSS',
                    start_time TEXT NOT NULL,
                    end_time TEXT NOT NULL,
                    unavailable_stations INTEGER NOT NULL DEFAULT 0,
                    remark TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                )
                """
            )
            # Backward-compatible migration for databases created before v1.7.19.
            cols = {row[1] for row in con.execute("PRAGMA table_info(manual_events)").fetchall()}
            migrations = {
                "category": "TEXT NOT NULL DEFAULT ''",
                "downtime_value": "TEXT NOT NULL DEFAULT ''",
                "category_value": "TEXT NOT NULL DEFAULT ''",
                "machine": "TEXT NOT NULL DEFAULT ''",
                "machine_value": "TEXT NOT NULL DEFAULT ''",
            }
            for col, ddl in migrations.items():
                if col not in cols:
                    con.execute(f"ALTER TABLE manual_events ADD COLUMN {col} {ddl}")

            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_manual_hour
                ON manual_events(production_date, line, model, hour_start)
                """
            )

    def list_events(self, production_date: str, line: str, model: str, hour_start: str):
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT id, event_type, downtime_value, category, category_value,
                       machine, machine_value, loss_mode, start_time, end_time,
                       unavailable_stations, remark
                FROM manual_events
                WHERE production_date=? AND line=? AND model=? AND hour_start=?
                ORDER BY start_time, id
                """,
                (str(production_date), str(line), str(model), str(hour_start)),
            ).fetchall()
        return [dict(r) for r in rows]

    def replace_events(self, production_date: str, line: str, model: str, hour_start: str, events: list[dict]):
        with self._connect() as con:
            con.execute(
                "DELETE FROM manual_events WHERE production_date=? AND line=? AND model=? AND hour_start=?",
                (str(production_date), str(line), str(model), str(hour_start)),
            )
            for event in events:
                con.execute(
                    """
                    INSERT INTO manual_events(
                        production_date, line, model, hour_start,
                        event_type, downtime_value, category, category_value,
                        machine, machine_value, loss_mode, start_time, end_time,
                        unavailable_stations, remark
                    ) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        str(production_date), str(line), str(model), str(hour_start),
                        str(event.get("event_type") or ""),
                        str(event.get("downtime_value") or ""),
                        str(event.get("category") or ""),
                        str(event.get("category_value") or ""),
                        str(event.get("machine") or ""),
                        str(event.get("machine_value") or ""),
                        str(event.get("loss_mode") or "TIME_LOSS"),
                        str(event.get("start") or ""),
                        str(event.get("end") or ""),
                        int(event.get("unavailable_stations") or 0),
                        str(event.get("remark") or ""),
                    ),
                )


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().lower().split())


def _clock_parts(value: str):
    raw = str(value or "").strip()
    for fmt in ("%H:%M:%S", "%H:%M", "%I:%M %p", "%I:%M:%S %p"):
        try:
            d = datetime.strptime(raw.upper(), fmt)
            return d.hour, d.minute, d.second
        except ValueError:
            pass
    return None


def _clock_datetime(base_date: date, value: str, shift_start_hour: int):
    parts = _clock_parts(value)
    if parts is None:
        return None
    h, m, s = parts
    d = base_date
    # Night shift: clocks after midnight belong to following calendar day.
    if shift_start_hour >= 12 and h < shift_start_hour:
        d = d + timedelta(days=1)
    return datetime(d.year, d.month, d.day, h, m, s)


def hour_datetimes(production_date: date, shift_start: str, hour_start: str, hour_end: str):
    shift_parts = _clock_parts(shift_start)
    if shift_parts is None:
        raise ValueError(f"Invalid shift start: {shift_start}")
    shift_h = shift_parts[0]
    start = _clock_datetime(production_date, hour_start, shift_h)
    end = _clock_datetime(production_date, hour_end, shift_h)
    if start is None or end is None:
        raise ValueError("Invalid hour interval")
    if end <= start:
        end += timedelta(days=1)
    return start, end


def _event_datetimes(production_date: date, shift_start: str, start_value: str, end_value: str):
    shift_parts = _clock_parts(shift_start)
    if shift_parts is None:
        return None, None
    shift_h = shift_parts[0]
    start = _clock_datetime(production_date, start_value, shift_h)
    end = _clock_datetime(production_date, end_value, shift_h)
    if start is None or end is None:
        return None, None
    if end <= start:
        end += timedelta(days=1)
    return start, end


def resolve_mct_rule(settings: dict, line: str, model: str):
    cfg = settings.get("hourly_validation", {}) if isinstance(settings, dict) else {}
    rules = cfg.get("mct_rules", []) or []
    line_n = _norm(line)
    model_n = _norm(model)

    def score(rule):
        rl = _norm(rule.get("line", "*"))
        rm = _norm(rule.get("model", "*"))
        if rl not in ("", "*", "all") and rl != line_n:
            return -1
        if rm not in ("", "*", "all", "all model") and rm != model_n:
            return -1
        return (2 if rl == line_n else 0) + (1 if rm == model_n else 0)

    best = None
    best_score = -1
    for rule in rules:
        s = score(rule)
        if s > best_score:
            best = rule
            best_score = s

    if best is None:
        default_mct = cfg.get("default_mct_sec", "")
        try:
            mct = float(default_mct)
        except Exception:
            return None
        if mct <= 0:
            return None
        return {
            "line": "*",
            "model": "*",
            "mct_sec": mct,
            "stations": int(cfg.get("default_stations", 1) or 1),
            "tolerance_min": float(cfg.get("tolerance_min", 5.0) or 5.0),
        }

    try:
        mct = float(best.get("mct_sec"))
    except Exception:
        return None
    if mct <= 0:
        return None

    return {
        "line": best.get("line", "*"),
        "model": best.get("model", "*"),
        "mct_sec": mct,
        "stations": max(1, int(best.get("stations", 1) or 1)),
        "tolerance_min": max(0.0, float(best.get("tolerance_min", cfg.get("tolerance_min", 5.0)) or 0.0)),
    }


def _qac_event_mode(event: dict, total_stations: int):
    """Classify a QAC record for hourly time reconciliation.

    Production Output / Normal Production records are evidence of output entry,
    not downtime.  They must remain visible in the editor but must never consume
    wall-clock time.  Partial-capacity records reduce capacity; all other QAC
    downtime records are treated as time loss.
    """
    topic = _norm(event.get("topic_label") or "")
    category = _norm(event.get("category_label") or "")
    machine = _norm(event.get("machine_label") or "")
    desc = _norm(event.get("description") or "")
    text = " ".join(x for x in (topic, category, machine, desc) if x)

    production_markers = (
        "production output",
        "normal production",
        "actual qty",
        "actual (qty)",
    )
    if any(marker in topic or marker in category for marker in production_markers):
        return "PRODUCTION", 0

    partial, unavailable = _partial_from_text(event, total_stations)
    if partial:
        return "PARTIAL_CAPACITY", unavailable

    return "TIME_LOSS", 0


def _partial_from_text(event: dict, total_stations: int):
    text = _norm(" ".join([
        str(event.get("topic_label") or ""),
        str(event.get("category_label") or ""),
        str(event.get("machine_label") or ""),
        str(event.get("description") or ""),
    ]))

    partial = (
        "unreached mct" in text
        or "unreach mct" in text
        or "partial capacity" in text
        or "stop gas" in text
        or "gas stop" in text
    )
    if not partial:
        return False, 0

    unavailable = 1
    m = re.search(r"(?:down|stop|stopped)\s*(?:gas\s*)?(\d+)\s*(?:station|stations|st)?\b", text)
    if m:
        unavailable = max(1, int(m.group(1)))
    elif "stop gas" in text:
        # "Stop Gas 1" normally means station No.1 stopped, i.e. one unavailable station.
        unavailable = 1

    return True, min(max(1, unavailable), max(1, total_stations))


def normalize_qac_events(existing_events: list[dict], production_date: date, shift_start: str, hour_start: str, hour_end: str, total_stations: int):
    hour_s, hour_e = hour_datetimes(production_date, shift_start, hour_start, hour_end)
    out = []
    for raw in existing_events or []:
        s, e = _event_datetimes(production_date, shift_start, raw.get("start"), raw.get("end"))
        if s is None or e is None or e <= hour_s or s >= hour_e:
            continue
        s2, e2 = max(s, hour_s), min(e, hour_e)
        if e2 <= s2:
            continue
        mode, unavailable = _qac_event_mode(raw, total_stations)
        out.append({
            "source": "QAC_HTML",
            "event_type": str(raw.get("topic_label") or raw.get("category_label") or "QAC Event"),
            "topic_label": str(raw.get("topic_label") or ""),
            "category_label": str(raw.get("category_label") or ""),
            "machine_label": str(raw.get("machine_label") or ""),
            "loss_mode": mode,
            "start_dt": s2,
            "end_dt": e2,
            "start": s2.strftime("%H:%M:%S"),
            "end": e2.strftime("%H:%M:%S"),
            "unavailable_stations": unavailable if mode == "PARTIAL_CAPACITY" else 0,
            "remark": str(raw.get("description") or ""),
            "result_id": str(raw.get("result_id") or ""),
        })
    return out


def normalize_manual_events(events: list[dict], production_date: date, shift_start: str, hour_start: str, hour_end: str):
    hour_s, hour_e = hour_datetimes(production_date, shift_start, hour_start, hour_end)
    out = []
    for raw in events or []:
        s, e = _event_datetimes(production_date, shift_start, raw.get("start"), raw.get("end"))
        if s is None or e is None:
            continue
        # Manual editor is hour-scoped; keep exact interval within the selected hour.
        if s < hour_s or e > hour_e or e <= s:
            continue
        item = dict(raw)
        item.update({
            "source": "MANUAL",
            "start_dt": s,
            "end_dt": e,
            "start": s.strftime("%H:%M:%S"),
            "end": e.strftime("%H:%M:%S"),
            "unavailable_stations": int(raw.get("unavailable_stations") or 0),
        })
        out.append(item)
    return out


def find_overlaps(events: list[dict]):
    overlaps = []
    ordered = sorted(events, key=lambda e: (e["start_dt"], e["end_dt"]))
    for i, a in enumerate(ordered):
        for b in ordered[i + 1:]:
            if b["start_dt"] >= a["end_dt"]:
                break
            if a["start_dt"] < b["end_dt"] and b["start_dt"] < a["end_dt"]:
                overlap = (min(a["end_dt"], b["end_dt"]) - max(a["start_dt"], b["start_dt"])).total_seconds() / 60.0
                overlaps.append((a, b, overlap))
    return overlaps


def validate_manual_event_rows(events: list[dict], production_date: date, shift_start: str, hour_start: str, hour_end: str, existing_events: list[dict] | None = None):
    hour_s, hour_e = hour_datetimes(production_date, shift_start, hour_start, hour_end)
    normalized = []
    errors = []

    for idx, event in enumerate(events, start=1):
        s, e = _event_datetimes(production_date, shift_start, event.get("start"), event.get("end"))
        if s is None or e is None:
            errors.append(f"Row {idx}: Start/End time ไม่ถูกต้อง")
            continue
        if e <= s:
            errors.append(f"Row {idx}: End ต้องมากกว่า Start")
            continue
        if s < hour_s or e > hour_e:
            errors.append(f"Row {idx}: Event ต้องอยู่ภายใน {hour_start}-{hour_end}")
            continue
        item = dict(event)
        item["start_dt"], item["end_dt"] = s, e
        normalized.append(item)

    for a, b, minutes in find_overlaps(normalized):
        ai = normalized.index(a) + 1
        bi = normalized.index(b) + 1
        errors.append(f"Row {ai} overlaps Row {bi} = {minutes:.1f} min")

    # Manual rows must not overlap already-recorded QAC events either.
    for i, manual in enumerate(normalized, start=1):
        for existing in existing_events or []:
            # Partial-capacity records may legitimately span a whole shift
            # while another time-loss event occurs inside that period.
            if existing.get("loss_mode") != "TIME_LOSS":
                continue
            if manual["start_dt"] < existing["end_dt"] and existing["start_dt"] < manual["end_dt"]:
                minutes = (min(manual["end_dt"], existing["end_dt"]) - max(manual["start_dt"], existing["start_dt"])).total_seconds() / 60.0
                errors.append(
                    f"Row {i} overlaps QAC event {existing.get('event_type','')} "
                    f"{existing.get('start','')}-{existing.get('end','')} = {minutes:.1f} min"
                )

    return errors


def evaluate_hour(*, qty: int, mct_sec: float, total_stations: int, tolerance_min: float, html_events: list[dict], manual_events: list[dict], hour_start_dt: datetime, hour_end_dt: datetime):
    events = list(html_events) + list(manual_events)
    conflicts = []

    time_loss_events = [
        e for e in events
        if e.get("loss_mode") == "TIME_LOSS"
    ]
    for a, b, minutes in find_overlaps(time_loss_events):
        conflicts.append(
            f"OVERLAP {a.get('source')}:{a.get('event_type')} {a.get('start')}-{a.get('end')} "
            f"กับ {b.get('source')}:{b.get('event_type')} {b.get('start')}-{b.get('end')} ({minutes:.1f} min)"
        )

    relevant_events = [
        e for e in events
        if e.get("loss_mode") in ("TIME_LOSS", "PARTIAL_CAPACITY")
    ]

    boundaries = {hour_start_dt, hour_end_dt}
    for e in relevant_events:
        boundaries.add(max(hour_start_dt, e["start_dt"]))
        boundaries.add(min(hour_end_dt, e["end_dt"]))
    points = sorted(boundaries)

    expected_standard_sec = 0.0
    recorded_event_sec = 0.0
    partial_sec = 0.0
    available_wall_sec = 0.0

    for a, b in zip(points, points[1:]):
        if b <= a:
            continue
        duration = (b - a).total_seconds()
        active = [e for e in relevant_events if e["start_dt"] < b and a < e["end_dt"]]
        time_losses = [e for e in active if e.get("loss_mode") == "TIME_LOSS"]
        partials = [e for e in active if e.get("loss_mode") == "PARTIAL_CAPACITY"]

        if time_losses:
            recorded_event_sec += duration
            continue

        ratio = 1.0
        if partials:
            unavailable = sum(max(1, int(e.get("unavailable_stations") or 1)) for e in partials)
            ratio = max(0.0, (total_stations - unavailable) / total_stations)
            partial_sec += duration

        available_wall_sec += duration
        expected_standard_sec += duration * ratio

    expected_qty = expected_standard_sec / mct_sec if mct_sec > 0 else 0.0
    actual_standard_sec = max(0, int(qty)) * mct_sec
    avg_capacity = (expected_standard_sec / available_wall_sec) if available_wall_sec > 0 else 0.0

    if expected_standard_sec <= 0:
        unexplained_wall_sec = 0.0 if int(qty) == 0 else 0.0
        if int(qty) > 0:
            conflicts.append("OUTPUT > 0 แต่ Expected Capacity = 0")
    elif actual_standard_sec > expected_standard_sec:
        over_std = actual_standard_sec - expected_standard_sec
        over_wall = over_std / max(avg_capacity, 1e-9)
        if over_wall / 60.0 > tolerance_min:
            conflicts.append(
                f"OUTPUT เกิน Expected Capacity เทียบเวลา {over_wall/60.0:.1f} min"
            )
        unexplained_wall_sec = 0.0
    else:
        missing_std = expected_standard_sec - actual_standard_sec
        unexplained_wall_sec = missing_std / max(avg_capacity, 1e-9)

    unexplained_min = max(0.0, unexplained_wall_sec / 60.0)
    recorded_event_min = recorded_event_sec / 60.0
    partial_capacity_min = partial_sec / 60.0
    accounted_min = min(60.0, recorded_event_min + max(0.0, 60.0 - recorded_event_min - unexplained_min))

    effective_mct = None
    if avg_capacity > 0:
        effective_mct = mct_sec / avg_capacity

    if conflicts:
        status = "DATA CONFLICT"
    elif unexplained_min <= tolerance_min:
        status = "TIME OK"
    else:
        status = "ACTION REQUIRED"

    return ValidationResult(
        status=status,
        mct_sec=mct_sec,
        total_stations=total_stations,
        expected_qty=expected_qty,
        actual_qty=int(qty),
        recorded_event_min=recorded_event_min,
        partial_capacity_min=partial_capacity_min,
        unexplained_min=unexplained_min,
        accounted_min=60.0 - unexplained_min,
        effective_mct_sec=effective_mct,
        average_capacity=avg_capacity,
        conflicts=conflicts,
        html_events=list(html_events),
        manual_events=list(manual_events),
    )

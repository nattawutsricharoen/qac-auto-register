from __future__ import annotations

import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import program_dir


def _norm(value: str) -> str:
    return " ".join(str(value or "").strip().casefold().split())


@dataclass(frozen=True)
class AlarmSuggestion:
    machine_value: str = ""
    machine_name: str = ""
    ng_value: str = ""
    ng_name: str = ""
    process_value: str = ""
    process_name: str = ""
    count: int = 0
    match_scope: str = "LINE"


class AlarmLearningStore:
    """Persistent frequency memory for Alarm Import mappings.

    The key is normalized QAC line + Column E alarm message. Only successful
    QAC imports should call record_success(), so cancelled/failed selections do
    not pollute the learned statistics.
    """

    def __init__(self, db_path: str | Path | None = None):
        if db_path is None:
            db_path = program_dir() / "alarm_learning.db"
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._ensure_schema()

    def _connect(self):
        con = sqlite3.connect(str(self.db_path))
        con.row_factory = sqlite3.Row
        return con

    def _ensure_schema(self):
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS alarm_mapping_stats (
                    line_key TEXT NOT NULL,
                    alarm_key TEXT NOT NULL,
                    alarm_text TEXT NOT NULL,
                    machine_value TEXT NOT NULL DEFAULT '',
                    machine_name TEXT NOT NULL DEFAULT '',
                    ng_value TEXT NOT NULL DEFAULT '',
                    ng_name TEXT NOT NULL DEFAULT '',
                    process_value TEXT NOT NULL DEFAULT '',
                    process_name TEXT NOT NULL DEFAULT '',
                    use_count INTEGER NOT NULL DEFAULT 0,
                    last_used_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (
                        line_key, alarm_key,
                        machine_value, ng_value, process_value
                    )
                )
                """
            )
            con.execute(
                "CREATE INDEX IF NOT EXISTS idx_alarm_mapping_lookup "
                "ON alarm_mapping_stats(line_key, alarm_key, use_count DESC, last_used_at DESC)"
            )

    def record_success(self, line: str, alarm_text: str, *, machine_value: str,
                       machine_name: str, ng_value: str, ng_name: str,
                       process_value: str, process_name: str):
        line_key = _norm(line)
        alarm_key = _norm(alarm_text)
        if not line_key or not alarm_key:
            return
        with self._connect() as con:
            con.execute(
                """
                INSERT INTO alarm_mapping_stats (
                    line_key, alarm_key, alarm_text,
                    machine_value, machine_name,
                    ng_value, ng_name,
                    process_value, process_name,
                    use_count, last_used_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(line_key, alarm_key, machine_value, ng_value, process_value)
                DO UPDATE SET
                    alarm_text=excluded.alarm_text,
                    machine_name=excluded.machine_name,
                    ng_name=excluded.ng_name,
                    process_name=excluded.process_name,
                    use_count=alarm_mapping_stats.use_count + 1,
                    last_used_at=CURRENT_TIMESTAMP
                """,
                (
                    line_key, alarm_key, str(alarm_text or "").strip(),
                    str(machine_value or ""), str(machine_name or ""),
                    str(ng_value or ""), str(ng_name or ""),
                    str(process_value or ""), str(process_name or ""),
                ),
            )

    def best(self, line: str, alarm_text: str) -> AlarmSuggestion | None:
        line_key = _norm(line)
        alarm_key = _norm(alarm_text)
        if not line_key or not alarm_key:
            return None
        with self._connect() as con:
            row = con.execute(
                """
                SELECT * FROM alarm_mapping_stats
                WHERE line_key=? AND alarm_key=?
                ORDER BY use_count DESC, last_used_at DESC
                LIMIT 1
                """,
                (line_key, alarm_key),
            ).fetchone()
            match_scope = "LINE"
            if not row:
                row = con.execute(
                    """
                    SELECT
                        machine_value, MAX(machine_name) AS machine_name,
                        ng_value, MAX(ng_name) AS ng_name,
                        process_value, MAX(process_name) AS process_name,
                        SUM(use_count) AS use_count,
                        MAX(last_used_at) AS last_used_at
                    FROM alarm_mapping_stats
                    WHERE alarm_key=?
                    GROUP BY machine_value, ng_value, process_value
                    ORDER BY SUM(use_count) DESC, MAX(last_used_at) DESC
                    LIMIT 1
                    """,
                    (alarm_key,),
                ).fetchone()
                match_scope = "ALL_PAGES"
        if not row:
            return None
        return AlarmSuggestion(
            machine_value=row["machine_value"],
            machine_name=row["machine_name"],
            ng_value=row["ng_value"],
            ng_name=row["ng_name"],
            process_value=row["process_value"],
            process_name=row["process_name"],
            count=int(row["use_count"] or 0),
            match_scope=match_scope,
        )

    def distribution(self, line: str, alarm_text: str) -> list[dict]:
        line_key = _norm(line)
        alarm_key = _norm(alarm_text)
        if not line_key or not alarm_key:
            return []
        with self._connect() as con:
            rows = con.execute(
                """
                SELECT machine_value, machine_name, ng_value, ng_name,
                       process_value, process_name, use_count, last_used_at
                FROM alarm_mapping_stats
                WHERE line_key=? AND alarm_key=?
                ORDER BY use_count DESC, last_used_at DESC
                """,
                (line_key, alarm_key),
            ).fetchall()
        return [dict(r) for r in rows]

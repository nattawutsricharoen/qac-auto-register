from __future__ import annotations

import hashlib
import sqlite3
import threading
from datetime import datetime, date, timedelta
from pathlib import Path
from typing import Iterable

from .runtime_paths import qac_cache_path


EVENT_FIELDS = (
    "result_id",
    "source",
    "topic_value",
    "topic_label",
    "category_value",
    "category_label",
    "model_value",
    "model_label",
    "machine_value",
    "machine_label",
    "start",
    "end",
    "description",
    "process_value",
    "actual_qty",
    "timeline_text",
)


def _text(value) -> str:
    return str(value or "").strip()


def _parse_date(value) -> date | None:
    raw = _text(value)

    for fmt in (
        "%Y-%m-%d",
        "%d-%m-%y",
        "%d-%m-%Y",
        "%Y/%m/%d",
        "%d/%m/%Y",
    ):
        try:
            return datetime.strptime(
                raw,
                fmt
            ).date()
        except ValueError:
            pass

    return None


def build_document_key(
    production_date: str,
    line: str,
    shift: str,
    document_no: str,
    url: str = "",
) -> str:
    """
    Stable key across application restarts/browser page indexes.
    """
    parts = [
        _text(production_date).lower(),
        _text(line).lower(),
        _text(shift).lower(),
        _text(document_no).lower(),
    ]

    # Prefer QAC business identity so the same document reuses the same
    # cache across browser restarts. URL is only a fallback when the page
    # has not rendered enough identity fields yet.
    if sum(
        1
        for item in parts
        if item
    ) < 2:
        parts.append(
            _text(url)
            .split("#", 1)[0]
            .lower()
        )

    identity = "|".join(
        parts
    )

    return hashlib.sha1(
        identity.encode(
            "utf-8",
            errors="ignore"
        )
    ).hexdigest()


class QacCache:
    def __init__(
        self,
        path: str | Path | None = None
    ):
        self.path = Path(
            path or qac_cache_path()
        )
        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )
        self._lock = threading.RLock()
        self._init_db()
        self.cleanup_keep_today_yesterday()

    def _connect(self):
        con = sqlite3.connect(
            str(self.path),
            timeout=15.0
        )
        con.row_factory = sqlite3.Row
        con.execute(
            "PRAGMA journal_mode=WAL"
        )
        con.execute(
            "PRAGMA synchronous=NORMAL"
        )
        con.execute(
            "PRAGMA busy_timeout=15000"
        )
        return con

    def _init_db(self):
        with self._lock, self._connect() as con:
            con.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    document_key TEXT PRIMARY KEY,
                    production_date TEXT NOT NULL DEFAULT '',
                    line TEXT NOT NULL DEFAULT '',
                    shift TEXT NOT NULL DEFAULT '',
                    document_no TEXT NOT NULL DEFAULT '',
                    url TEXT NOT NULL DEFAULT '',
                    last_sync_at TEXT NOT NULL DEFAULT '',
                    timeline_count INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS events (
                    document_key TEXT NOT NULL,
                    result_id TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT '',
                    topic_value TEXT NOT NULL DEFAULT '',
                    topic_label TEXT NOT NULL DEFAULT '',
                    category_value TEXT NOT NULL DEFAULT '',
                    category_label TEXT NOT NULL DEFAULT '',
                    model_value TEXT NOT NULL DEFAULT '',
                    model_label TEXT NOT NULL DEFAULT '',
                    machine_value TEXT NOT NULL DEFAULT '',
                    machine_label TEXT NOT NULL DEFAULT '',
                    start TEXT NOT NULL DEFAULT '',
                    end TEXT NOT NULL DEFAULT '',
                    description TEXT NOT NULL DEFAULT '',
                    process_value TEXT NOT NULL DEFAULT '',
                    actual_qty TEXT NOT NULL DEFAULT '',
                    timeline_text TEXT NOT NULL DEFAULT '',
                    seen_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT '',
                    PRIMARY KEY (
                        document_key,
                        result_id
                    )
                );

                CREATE INDEX IF NOT EXISTS idx_events_doc_start
                ON events(
                    document_key,
                    start
                );

                CREATE INDEX IF NOT EXISTS idx_events_doc_model
                ON events(
                    document_key,
                    model_value
                );

                CREATE INDEX IF NOT EXISTS idx_documents_date
                ON documents(
                    production_date
                );
                """
            )

    def cleanup_keep_today_yesterday(
        self,
        today: date | None = None
    ) -> int:
        """
        Keep current calendar day + previous day.
        This is safer for factory night shifts than rolling 48 hours.
        """
        current = today or date.today()
        minimum = current - timedelta(
            days=1
        )

        deleted = 0

        with self._lock, self._connect() as con:
            docs = con.execute(
                """
                SELECT
                    document_key,
                    production_date,
                    last_sync_at
                FROM documents
                """
            ).fetchall()

            stale = []

            for row in docs:
                prod_date = _parse_date(
                    row["production_date"]
                )

                if prod_date is not None:
                    if prod_date < minimum:
                        stale.append(
                            row["document_key"]
                        )
                    continue

                # Unknown production date: retain for two calendar days
                # based on last sync timestamp.
                try:
                    last_sync = datetime.fromisoformat(
                        row["last_sync_at"]
                    ).date()
                except Exception:
                    last_sync = current

                if last_sync < minimum:
                    stale.append(
                        row["document_key"]
                    )

            for key in stale:
                con.execute(
                    """
                    DELETE FROM events
                    WHERE document_key=?
                    """,
                    (key,)
                )
                con.execute(
                    """
                    DELETE FROM documents
                    WHERE document_key=?
                    """,
                    (key,)
                )

            deleted = len(stale)

        return deleted

    def touch_document(
        self,
        document_key: str,
        *,
        production_date: str = "",
        line: str = "",
        shift: str = "",
        document_no: str = "",
        url: str = "",
        timeline_count: int | None = None,
    ):
        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self._lock, self._connect() as con:
            current = con.execute(
                """
                SELECT timeline_count
                FROM documents
                WHERE document_key=?
                """,
                (document_key,)
            ).fetchone()

            count = (
                int(timeline_count)
                if timeline_count is not None
                else int(
                    current["timeline_count"]
                    if current
                    else 0
                )
            )

            con.execute(
                """
                INSERT INTO documents(
                    document_key,
                    production_date,
                    line,
                    shift,
                    document_no,
                    url,
                    last_sync_at,
                    timeline_count
                )
                VALUES(?,?,?,?,?,?,?,?)
                ON CONFLICT(document_key)
                DO UPDATE SET
                    production_date=excluded.production_date,
                    line=excluded.line,
                    shift=excluded.shift,
                    document_no=excluded.document_no,
                    url=excluded.url,
                    last_sync_at=excluded.last_sync_at,
                    timeline_count=excluded.timeline_count
                """,
                (
                    document_key,
                    _text(production_date),
                    _text(line),
                    _text(shift),
                    _text(document_no),
                    _text(url),
                    now,
                    count,
                )
            )

    def get_events(
        self,
        document_key: str
    ) -> list[dict]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT *
                FROM events
                WHERE document_key=?
                ORDER BY
                    CAST(result_id AS INTEGER),
                    result_id
                """,
                (document_key,)
            ).fetchall()

        return [
            {
                key: row[key]
                for key in EVENT_FIELDS
            }
            for row in rows
        ]

    def get_result_ids(
        self,
        document_key: str
    ) -> set[str]:
        with self._lock, self._connect() as con:
            rows = con.execute(
                """
                SELECT result_id
                FROM events
                WHERE document_key=?
                """,
                (document_key,)
            ).fetchall()

        return {
            _text(row["result_id"])
            for row in rows
            if _text(row["result_id"])
        }

    def upsert_events(
        self,
        document_key: str,
        events: Iterable[dict]
    ) -> int:
        now = datetime.now().isoformat(
            timespec="seconds"
        )
        count = 0

        with self._lock, self._connect() as con:
            for event in events:
                result_id = _text(
                    event.get("result_id")
                )

                if (
                    not result_id
                    or result_id == "0"
                ):
                    continue

                values = {
                    key: _text(
                        event.get(key)
                    )
                    for key in EVENT_FIELDS
                }
                values["result_id"] = result_id

                con.execute(
                    """
                    INSERT INTO events(
                        document_key,
                        result_id,
                        source,
                        topic_value,
                        topic_label,
                        category_value,
                        category_label,
                        model_value,
                        model_label,
                        machine_value,
                        machine_label,
                        start,
                        end,
                        description,
                        process_value,
                        actual_qty,
                        timeline_text,
                        seen_at,
                        updated_at
                    )
                    VALUES(
                        ?,?,?,?,?,?,?,?,?,?,
                        ?,?,?,?,?,?,?,?,?
                    )
                    ON CONFLICT(
                        document_key,
                        result_id
                    )
                    DO UPDATE SET
                        source=CASE
                            WHEN excluded.source!=''
                            THEN excluded.source
                            ELSE events.source
                        END,
                        topic_value=CASE
                            WHEN excluded.topic_value!=''
                            THEN excluded.topic_value
                            ELSE events.topic_value
                        END,
                        topic_label=CASE
                            WHEN excluded.topic_label!=''
                            THEN excluded.topic_label
                            ELSE events.topic_label
                        END,
                        category_value=CASE
                            WHEN excluded.category_value!=''
                            THEN excluded.category_value
                            ELSE events.category_value
                        END,
                        category_label=CASE
                            WHEN excluded.category_label!=''
                            THEN excluded.category_label
                            ELSE events.category_label
                        END,
                        model_value=CASE
                            WHEN excluded.model_value!=''
                            THEN excluded.model_value
                            ELSE events.model_value
                        END,
                        model_label=CASE
                            WHEN excluded.model_label!=''
                            THEN excluded.model_label
                            ELSE events.model_label
                        END,
                        machine_value=CASE
                            WHEN excluded.machine_value!=''
                            THEN excluded.machine_value
                            ELSE events.machine_value
                        END,
                        machine_label=CASE
                            WHEN excluded.machine_label!=''
                            THEN excluded.machine_label
                            ELSE events.machine_label
                        END,
                        start=CASE
                            WHEN excluded.start!=''
                            THEN excluded.start
                            ELSE events.start
                        END,
                        end=CASE
                            WHEN excluded.end!=''
                            THEN excluded.end
                            ELSE events.end
                        END,
                        description=CASE
                            WHEN excluded.description!=''
                            THEN excluded.description
                            ELSE events.description
                        END,
                        process_value=CASE
                            WHEN excluded.process_value!=''
                            THEN excluded.process_value
                            ELSE events.process_value
                        END,
                        actual_qty=CASE
                            WHEN excluded.actual_qty!=''
                            THEN excluded.actual_qty
                            ELSE events.actual_qty
                        END,
                        timeline_text=CASE
                            WHEN excluded.timeline_text!=''
                            THEN excluded.timeline_text
                            ELSE events.timeline_text
                        END,
                        seen_at=excluded.seen_at,
                        updated_at=excluded.updated_at
                    """,
                    (
                        document_key,
                        values["result_id"],
                        values["source"],
                        values["topic_value"],
                        values["topic_label"],
                        values["category_value"],
                        values["category_label"],
                        values["model_value"],
                        values["model_label"],
                        values["machine_value"],
                        values["machine_label"],
                        values["start"],
                        values["end"],
                        values["description"],
                        values["process_value"],
                        values["actual_qty"],
                        values["timeline_text"],
                        now,
                        now,
                    )
                )
                count += 1

        return count

    def update_actual_qty(
        self,
        document_key: str,
        result_id: str,
        qty
    ):
        now = datetime.now().isoformat(
            timespec="seconds"
        )

        with self._lock, self._connect() as con:
            con.execute(
                """
                UPDATE events
                SET
                    actual_qty=?,
                    updated_at=?,
                    seen_at=?
                WHERE
                    document_key=?
                    AND result_id=?
                """,
                (
                    _text(qty),
                    now,
                    now,
                    document_key,
                    _text(result_id),
                )
            )

    def reconcile_result_ids(
        self,
        document_key: str,
        current_result_ids
    ) -> int:
        """
        Make cached Result IDs exactly follow the current QAC Timeline.

        Important for delete/re-create:
        if a QAC document is deleted and recreated with the same
        production date/line/shift/document no, it has the same cache key.
        Old Result rows must not survive when they are no longer present
        on the current Timeline.
        """
        keep = {
            _text(value)
            for value in (
                current_result_ids
                or []
            )
            if _text(value)
        }

        with self._lock, self._connect() as con:
            before = con.execute(
                """
                SELECT COUNT(*) AS c
                FROM events
                WHERE document_key=?
                """,
                (document_key,)
            ).fetchone()["c"]

            if not keep:
                con.execute(
                    """
                    DELETE FROM events
                    WHERE document_key=?
                    """,
                    (document_key,)
                )
            else:
                placeholders = ",".join(
                    "?"
                    for _ in keep
                )

                con.execute(
                    f"""
                    DELETE FROM events
                    WHERE document_key=?
                      AND result_id NOT IN ({placeholders})
                    """,
                    (
                        document_key,
                        *sorted(keep),
                    )
                )

            after = con.execute(
                """
                SELECT COUNT(*) AS c
                FROM events
                WHERE document_key=?
                """,
                (document_key,)
            ).fetchone()["c"]

        return int(before) - int(after)

    def stats(self) -> dict:
        with self._lock, self._connect() as con:
            documents = con.execute(
                "SELECT COUNT(*) AS c FROM documents"
            ).fetchone()["c"]
            events = con.execute(
                "SELECT COUNT(*) AS c FROM events"
            ).fetchone()["c"]

        return {
            "path": str(self.path),
            "documents": int(documents),
            "events": int(events),
        }

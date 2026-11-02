from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

from .runtime_paths import program_dir

_DB_NAME = "sample_mapping_local.sqlite3"
_SCHEMA_LOCK = threading.RLock()
_SCHEMA_READY: set[str] = set()
_LOCK_RETRIES = 6
_ALLOWED_SOURCE_TYPES = {"SMP_COLUMN", "ELECTRODE_NO", "ELECTRODE_SHOT", "MANUAL", "FIXED", "IGNORE"}


def mapping_db_path() -> Path:
    return program_dir() / "config" / _DB_NAME


def _connect() -> sqlite3.Connection:
    path = mapping_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), timeout=10.0)
    conn.execute("PRAGMA busy_timeout=10000")
    conn.row_factory = sqlite3.Row
    return conn


def _retry_locked(fn):
    delay = 0.02
    last = None
    for attempt in range(_LOCK_RETRIES):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last = exc
            if "locked" not in str(exc).casefold() or attempt == _LOCK_RETRIES - 1:
                raise
            time.sleep(delay)
            delay = min(delay * 2, 0.25)
    raise last  # pragma: no cover


def ensure_schema() -> None:
    path_key = str(mapping_db_path().resolve())
    if path_key in _SCHEMA_READY:
        return
    with _SCHEMA_LOCK:
        if path_key in _SCHEMA_READY:
            return

        def init():
            with _connect() as conn:
                conn.execute("PRAGMA journal_mode=WAL")
                conn.execute("PRAGMA synchronous=NORMAL")
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS sample_mapping_overrides (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        document_name TEXT NOT NULL COLLATE NOCASE,
                        qac_section TEXT NOT NULL DEFAULT '' COLLATE NOCASE,
                        qac_field TEXT NOT NULL COLLATE NOCASE,
                        source_type TEXT NOT NULL DEFAULT 'SMP_COLUMN',
                        source_group TEXT NOT NULL DEFAULT '',
                        source_column TEXT NOT NULL DEFAULT '',
                        source_value TEXT NOT NULL DEFAULT '',
                        source_machine TEXT NOT NULL DEFAULT '',
                        source_position TEXT NOT NULL DEFAULT '',
                        source_station TEXT NOT NULL DEFAULT '',
                        enabled INTEGER NOT NULL DEFAULT 1,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                        UNIQUE(document_name, qac_section, qac_field)
                    );
                    CREATE INDEX IF NOT EXISTS idx_sample_mapping_doc
                    ON sample_mapping_overrides(document_name, enabled);
                    """
                )
                # In-place migration from v1.7.61-v1.7.64 local DBs.
                cols = {r[1] for r in conn.execute("PRAGMA table_info(sample_mapping_overrides)").fetchall()}
                for name, ddl in (
                    ("source_type", "TEXT NOT NULL DEFAULT 'SMP_COLUMN'"),
                    ("source_value", "TEXT NOT NULL DEFAULT ''"),
                    ("source_machine", "TEXT NOT NULL DEFAULT ''"),
                    ("source_position", "TEXT NOT NULL DEFAULT ''"),
                    ("source_station", "TEXT NOT NULL DEFAULT ''"),
                ):
                    if name not in cols:
                        conn.execute(f"ALTER TABLE sample_mapping_overrides ADD COLUMN {name} {ddl}")
                # Legacy rows are SMP column mappings.
                conn.execute("UPDATE sample_mapping_overrides SET source_type='SMP_COLUMN' WHERE source_type IS NULL OR TRIM(source_type)='' ")

        _retry_locked(init)
        _SCHEMA_READY.add(path_key)


def load_overrides() -> dict[tuple[str, str, str], dict]:
    ensure_schema()

    def read():
        with _connect() as conn:
            return conn.execute(
                "SELECT document_name,qac_section,qac_field,source_type,source_group,source_column,"
                "source_value,source_machine,source_position,source_station FROM sample_mapping_overrides WHERE enabled=1"
            ).fetchall()

    rows = _retry_locked(read)
    out = {}
    for row in rows:
        key = (
            str(row["document_name"] or "").strip().casefold(),
            str(row["qac_section"] or "").strip().casefold(),
            str(row["qac_field"] or "").strip().casefold(),
        )
        out[key] = dict(row)
    return out


def save_override(
    document_name: str,
    qac_section: str,
    qac_field: str,
    source_group: str = "",
    source_column: str = "",
    *,
    source_type: str = "SMP_COLUMN",
    source_value: str = "",
    source_machine: str = "",
    source_position: str = "",
    source_station: str = "",
) -> None:
    vals = [str(x or "").strip() for x in (
        document_name, qac_section, qac_field, source_group, source_column,
        source_type, source_value, source_machine, source_position, source_station,
    )]
    (document_name, qac_section, qac_field, source_group, source_column,
     source_type, source_value, source_machine, source_position, source_station) = vals
    source_type = source_type.upper() or "SMP_COLUMN"
    if source_type not in _ALLOWED_SOURCE_TYPES:
        raise ValueError(f"source_type ไม่รองรับ: {source_type}")
    if not document_name or not qac_field:
        raise ValueError("document_name และ qac_field ห้ามว่าง")
    if source_type == "SMP_COLUMN" and not source_column:
        raise ValueError("SMP_COLUMN ต้องระบุ source_column")
    if source_type in {"ELECTRODE_NO", "ELECTRODE_SHOT"} and (not source_machine or not source_position):
        raise ValueError("Electrode source ต้องระบุ Machine และ Position")
    ensure_schema()

    def write():
        with _connect() as conn:
            conn.execute(
                """
                INSERT INTO sample_mapping_overrides
                    (document_name,qac_section,qac_field,source_type,source_group,source_column,
                     source_value,source_machine,source_position,source_station,enabled)
                VALUES (?,?,?,?,?,?,?,?,?,?,1)
                ON CONFLICT(document_name,qac_section,qac_field) DO UPDATE SET
                    source_type=excluded.source_type,
                    source_group=excluded.source_group,
                    source_column=excluded.source_column,
                    source_value=excluded.source_value,
                    source_machine=excluded.source_machine,
                    source_position=excluded.source_position,
                    source_station=excluded.source_station,
                    enabled=1,
                    updated_at=CURRENT_TIMESTAMP
                """,
                (document_name, qac_section, qac_field, source_type, source_group, source_column,
                 source_value, source_machine, source_position, source_station),
            )

    _retry_locked(write)


def delete_override(document_name: str, qac_section: str, qac_field: str) -> None:
    ensure_schema()

    def delete():
        with _connect() as conn:
            conn.execute(
                "DELETE FROM sample_mapping_overrides WHERE document_name=? COLLATE NOCASE "
                "AND qac_section=? COLLATE NOCASE AND qac_field=? COLLATE NOCASE",
                (str(document_name or "").strip(), str(qac_section or "").strip(), str(qac_field or "").strip()),
            )

    _retry_locked(delete)

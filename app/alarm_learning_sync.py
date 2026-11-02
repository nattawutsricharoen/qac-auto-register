from __future__ import annotations

import os
import re
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.runtime_paths import program_dir


CENTRAL_DIRNAME = "alarm_learning"


def _safe_name(value: str) -> str:
    text = re.sub(r"[^A-Za-z0-9._-]+", "_", str(value or "").strip())
    return text.strip("._-") or "unknown"


def resolve_central_alarm_dir(access_config_path: str, app_root: Path | None = None) -> Path:
    """Return central Alarm Learning directory beside access_control.csv.

    If no central access path is configured, returns a local-looking fallback path;
    callers should normally treat an empty access_config_path as unavailable and skip sync.
    """
    raw = str(access_config_path or "").strip()
    if raw:
        return Path(raw).expanduser().parent / CENTRAL_DIRNAME
    root = Path(app_root or program_dir())
    return root / CENTRAL_DIRNAME


@dataclass(frozen=True)
class AlarmSyncResult:
    ok: bool
    skipped: bool = False
    central_path: str = ""
    error: str = ""


def upload_alarm_learning_snapshot(
    access_config_path: str,
    *,
    machine_name: str,
    machine_ip: str,
    local_db_path: str | Path | None = None,
) -> AlarmSyncResult:
    """Upload a consistent snapshot of the *local* alarm_learning.db on shutdown.

    Each machine writes its own snapshot, so simultaneous shutdowns cannot overwrite
    another machine's learning database. No other local DB is uploaded here.
    """
    access_path = str(access_config_path or "").strip()
    if not access_path:
        return AlarmSyncResult(ok=False, skipped=True, error="Central access path is not configured")

    source = Path(local_db_path or (program_dir() / "alarm_learning.db"))
    if not source.exists():
        return AlarmSyncResult(ok=True, skipped=True, error="Local alarm_learning.db does not exist")

    central_dir = resolve_central_alarm_dir(access_path)
    central_dir.mkdir(parents=True, exist_ok=True)

    stem = f"alarm_learning_{_safe_name(machine_name)}_{_safe_name(machine_ip)}"
    destination = central_dir / f"{stem}.db"
    temp_destination = central_dir / f".{stem}.db.tmp"

    # Create a transaction-consistent local snapshot first. This is safer than
    # copying a live SQLite file directly (especially if WAL mode is ever used).
    fd, snapshot_name = tempfile.mkstemp(prefix="qac_alarm_learning_", suffix=".db")
    os.close(fd)
    snapshot = Path(snapshot_name)
    try:
        src_con = sqlite3.connect(str(source), timeout=5)
        try:
            dst_con = sqlite3.connect(str(snapshot))
            try:
                src_con.backup(dst_con)
                dst_con.commit()
            finally:
                dst_con.close()
        finally:
            src_con.close()

        shutil.copy2(snapshot, temp_destination)
        os.replace(temp_destination, destination)
        return AlarmSyncResult(ok=True, central_path=str(destination))
    except Exception as exc:
        try:
            if temp_destination.exists():
                temp_destination.unlink()
        except Exception:
            pass
        return AlarmSyncResult(ok=False, central_path=str(destination), error=str(exc))
    finally:
        try:
            snapshot.unlink(missing_ok=True)
        except Exception:
            pass

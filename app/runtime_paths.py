from __future__ import annotations

import sys
from pathlib import Path


APP_NAME = "QAC_Auto_Register"


def program_dir() -> Path:
    """
    Persistent application folder.

    PyInstaller --onedir:
      folder containing QAC_Auto_Register.exe

    Source / development:
      project root containing main.py
    """
    if getattr(
        sys,
        "frozen",
        False
    ):
        path = Path(
            sys.executable
        ).resolve().parent
    else:
        path = Path(
            __file__
        ).resolve().parents[1]

    path.mkdir(
        parents=True,
        exist_ok=True
    )
    return path


def local_state_dir() -> Path:
    # Backward-compatible API used by existing modules.
    return program_dir()


def qac_cache_path() -> Path:
    return program_dir() / "qac_cache.db"


def access_snapshot_path() -> Path:
    return program_dir() / "access_cache.json"


def pending_log_dir() -> Path:
    path = (
        program_dir()
        / "pending_logs"
    )
    path.mkdir(
        parents=True,
        exist_ok=True
    )
    return path

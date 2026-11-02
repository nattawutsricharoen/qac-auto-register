from __future__ import annotations

import csv
import os
import time
from pathlib import Path


MCT_FILENAME = "mct_master.csv"
MCT_FIELDS = ["line", "model", "mct_sec", "stations", "tolerance_min", "active"]


def _resolve_access_path(raw_path: str, app_root: Path) -> Path:
    raw = str(raw_path or "").strip()
    if not raw:
        raise RuntimeError("ACCESS_CONFIG_PATH_EMPTY")
    p = Path(raw)
    if not p.is_absolute():
        p = app_root / p
    return p


def resolve_central_mct_path(access_config_path: str, app_root: Path) -> Path:
    """MCT master always lives beside the central access_control.csv."""
    access_path = _resolve_access_path(access_config_path, app_root)
    return access_path.parent / MCT_FILENAME


def _as_float(value, name: str) -> float:
    try:
        return float(str(value).strip())
    except Exception as exc:
        raise ValueError(f"{name} must be numeric") from exc


def _as_int(value, name: str) -> int:
    try:
        return int(float(str(value).strip()))
    except Exception as exc:
        raise ValueError(f"{name} must be integer") from exc


def normalize_rule(row: dict, row_no: int | None = None) -> dict:
    prefix = f"row {row_no}: " if row_no else ""
    line = str(row.get("line", "*") or "*").strip() or "*"
    model = str(row.get("model", "*") or "*").strip() or "*"
    mct = _as_float(row.get("mct_sec", ""), prefix + "MCT sec")
    stations = _as_int(row.get("stations", 1), prefix + "Stations")
    tolerance = _as_float(row.get("tolerance_min", 5.0), prefix + "Tolerance")
    active_raw = str(row.get("active", "1") or "1").strip().lower()
    active = active_raw not in {"0", "false", "no", "inactive"}
    if mct <= 0:
        raise ValueError(prefix + "MCT sec must be > 0")
    if stations <= 0:
        raise ValueError(prefix + "Stations must be > 0")
    if tolerance < 0:
        raise ValueError(prefix + "Tolerance must be >= 0")
    return {
        "line": line,
        "model": model,
        "mct_sec": mct,
        "stations": stations,
        "tolerance_min": tolerance,
        "active": active,
    }


def load_central_mct(access_config_path: str, app_root: Path) -> tuple[list[dict], Path]:
    path = resolve_central_mct_path(access_config_path, app_root)
    if not path.exists():
        return [], path
    with path.open("r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        fields = {str(x or "").strip().lower() for x in (reader.fieldnames or [])}
        required = {"line", "model", "mct_sec", "stations", "tolerance_min"}
        if not required.issubset(fields):
            raise RuntimeError(f"MCT_MASTER_INVALID_HEADER:{path}")
        rules = []
        for idx, row in enumerate(reader, start=2):
            if not any(str(v or "").strip() for v in row.values()):
                continue
            rule = normalize_rule(row, idx)
            if rule["active"]:
                rules.append(rule)
    return rules, path


def _acquire_lock(path: Path, timeout_seconds: float = 8.0):
    lock_path = Path(str(path) + ".lock")
    deadline = time.monotonic() + timeout_seconds
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(fd, f"pid={os.getpid()}|{time.time()}".encode("utf-8"))
            return fd, lock_path
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError("MCT_MASTER_LOCK_TIMEOUT")
            time.sleep(0.2)


def _release_lock(fd, lock_path: Path):
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def save_central_mct(access_config_path: str, app_root: Path, rules: list[dict]) -> Path:
    path = resolve_central_mct_path(access_config_path, app_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    normalized = [normalize_rule(r, i + 1) for i, r in enumerate(rules)]
    fd, lock_path = _acquire_lock(path)
    tmp = path.with_name(path.name + f".tmp.{os.getpid()}")
    try:
        with tmp.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=MCT_FIELDS)
            writer.writeheader()
            for r in normalized:
                writer.writerow({
                    "line": r["line"],
                    "model": r["model"],
                    "mct_sec": f'{r["mct_sec"]:g}',
                    "stations": r["stations"],
                    "tolerance_min": f'{r["tolerance_min"]:g}',
                    "active": "1" if r["active"] else "0",
                })
        os.replace(tmp, path)
    finally:
        try:
            tmp.unlink(missing_ok=True)
        except Exception:
            pass
        _release_lock(fd, lock_path)
    return path

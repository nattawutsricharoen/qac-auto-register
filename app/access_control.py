from __future__ import annotations

import csv
import socket
import os
import time
import json
from datetime import datetime
from dataclasses import dataclass
from pathlib import Path

from .runtime_paths import access_snapshot_path


@dataclass
class AccessRecord:
    ip: str
    name: str
    status: str
    tab1_enable: bool
    tab1_show: bool
    tab2_enable: bool
    tab2_show: bool
    tab3_enable: bool
    tab3_show: bool
    tab4_enable: bool
    tab4_show: bool
    tab5_enable: bool
    tab5_show: bool
    tab6_enable: bool
    tab6_show: bool
    settings_show: bool
    source_path: str
    source_mode: str = "LAN"
    cached_at: str = ""

    # Backward-compatible aliases used by older code.
    @property
    def tab1(self) -> bool:
        return self.tab1_enable

    @property
    def tab2(self) -> bool:
        return self.tab2_enable


def _bool01(value, default: bool = False) -> bool:
    if value is None or str(value).strip() == "":
        return default
    return str(value).strip() == "1"


def local_ipv4_addresses() -> list[str]:
    result = set()

    try:
        hostname = socket.gethostname()
        for item in socket.getaddrinfo(
            hostname,
            None,
            family=socket.AF_INET
        ):
            ip = item[4][0]
            if ip and not ip.startswith("127."):
                result.add(ip)
    except Exception:
        pass

    try:
        _, _, ips = socket.gethostbyname_ex(
            socket.gethostname()
        )
        for ip in ips:
            if ip and not ip.startswith("127."):
                result.add(ip)
    except Exception:
        pass

    return sorted(result)


def _resolve_path(
    raw_path: str,
    app_root: Path
) -> Path:
    raw = str(raw_path or "").strip()

    if not raw:
        raise RuntimeError("ACCESS_CONFIG_PATH_EMPTY")

    p = Path(raw)

    if not p.is_absolute():
        p = app_root / p

    return p



def computer_name() -> str:
    try:
        value = socket.gethostname().strip()
        if value:
            return value
    except Exception:
        pass
    return "UNKNOWN-PC"


def _acquire_lock(
    path: Path,
    timeout_seconds: float = 8.0
):
    """
    Small cross-machine lock using an atomic lock-file create.
    Suitable for a central CSV on a LAN share.
    """
    lock_path = Path(str(path) + ".lock")
    deadline = time.monotonic() + timeout_seconds

    while True:
        try:
            fd = os.open(
                str(lock_path),
                os.O_CREAT | os.O_EXCL | os.O_WRONLY
            )
            os.write(
                fd,
                (
                    f"{computer_name()}|"
                    f"{os.getpid()}|"
                    f"{time.time()}"
                ).encode("utf-8")
            )
            return fd, lock_path
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "ACCESS_CONFIG_LOCK_TIMEOUT"
                )
            time.sleep(0.20)


def _release_lock(fd, lock_path: Path):
    try:
        os.close(fd)
    except Exception:
        pass
    try:
        lock_path.unlink(missing_ok=True)
    except Exception:
        pass


def enroll_pending_access(
    raw_path: str,
    app_root: Path,
    local_ips: list[str] | None = None
):
    """
    Add an unknown machine to the central access CSV.

    New machines are fail-closed:
      status=pending
      every permission=0

    Returns:
      (added: bool, ip: str, computer_name: str, path: str)

    The function re-checks the CSV while holding the LAN lock so
    simultaneous first launches cannot create duplicate IP rows.
    """
    path = _resolve_path(raw_path, app_root)

    if not path.exists():
        raise RuntimeError(
            f"ACCESS_CONFIG_NOT_FOUND:{path}"
        )

    ips = list(local_ips or local_ipv4_addresses())
    if not ips:
        raise RuntimeError(
            "LOCAL_IP_NOT_FOUND"
        )

    # Prefer normal private/LAN IPv4 and keep deterministic order.
    ip = sorted(ips)[0]
    host = computer_name()

    fd, lock_path = _acquire_lock(path)

    try:
        with path.open(
            "r",
            encoding="utf-8-sig",
            newline=""
        ) as f:
            reader = csv.DictReader(f)
            fieldnames = [
                str(x or "").strip()
                for x in (reader.fieldnames or [])
            ]
            rows = list(reader)

        fields = {
            x.lower()
            for x in fieldnames
        }

        common = {"ip", "name", "status"}
        v6 = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "tab4_enable",
            "tab4_show",
            "tab5_enable",
            "tab5_show",
            "tab6_enable",
            "tab6_show",
            "settings_show",
        }
        v5 = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "tab4_enable",
            "tab4_show",
            "tab5_enable",
            "tab5_show",
            "settings_show",
        }
        v4 = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "tab4_enable",
            "tab4_show",
            "settings_show",
        }
        v3 = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "settings_show",
        }
        v2 = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "settings_show",
        }
        v1 = {"tab1", "tab2"}

        if not common.issubset(fields):
            raise RuntimeError(
                "ACCESS_CONFIG_INVALID_HEADER"
            )

        is_v6 = v6.issubset(fields)
        is_v5 = v5.issubset(fields)
        is_v4 = v4.issubset(fields)
        is_v3 = v3.issubset(fields)
        is_v2 = v2.issubset(fields)
        is_v1 = v1.issubset(fields)

        if not is_v6 and not is_v5 and not is_v4 and not is_v3 and not is_v2 and not is_v1:
            raise RuntimeError(
                "ACCESS_CONFIG_INVALID_PERMISSION_FIELDS"
            )

        # Another machine/process may have inserted it while we waited.
        for row in rows:
            if str(row.get("ip", "")).strip() in ips:
                return (
                    False,
                    str(row.get("ip", "")).strip(),
                    str(row.get("name", "")).strip() or host,
                    str(path),
                )

        new_row = {
            key: ""
            for key in fieldnames
        }
        new_row["ip"] = ip
        new_row["name"] = host
        new_row["status"] = "pending"

        if is_v6:
            new_row["tab1_enable"] = "0"
            new_row["tab1_show"] = "0"
            new_row["tab2_enable"] = "0"
            new_row["tab2_show"] = "0"
            new_row["tab3_enable"] = "0"
            new_row["tab3_show"] = "0"
            new_row["tab4_enable"] = "0"
            new_row["tab4_show"] = "0"
            new_row["tab5_enable"] = "0"
            new_row["tab5_show"] = "0"
            new_row["tab6_enable"] = "0"
            new_row["tab6_show"] = "0"
            new_row["settings_show"] = "0"
        elif is_v5:
            new_row["tab1_enable"] = "0"
            new_row["tab1_show"] = "0"
            new_row["tab2_enable"] = "0"
            new_row["tab2_show"] = "0"
            new_row["tab3_enable"] = "0"
            new_row["tab3_show"] = "0"
            new_row["tab4_enable"] = "0"
            new_row["tab4_show"] = "0"
            new_row["tab5_enable"] = "0"
            new_row["tab5_show"] = "0"
            new_row["settings_show"] = "0"
        elif is_v4:
            new_row["tab1_enable"] = "0"
            new_row["tab1_show"] = "0"
            new_row["tab2_enable"] = "0"
            new_row["tab2_show"] = "0"
            new_row["tab3_enable"] = "0"
            new_row["tab3_show"] = "0"
            new_row["tab4_enable"] = "0"
            new_row["tab4_show"] = "0"
            new_row["settings_show"] = "0"
        elif is_v3:
            new_row["tab1_enable"] = "0"
            new_row["tab1_show"] = "0"
            new_row["tab2_enable"] = "0"
            new_row["tab2_show"] = "0"
            new_row["tab3_enable"] = "0"
            new_row["tab3_show"] = "0"
            new_row["settings_show"] = "0"
        elif is_v2:
            new_row["tab1_enable"] = "0"
            new_row["tab1_show"] = "0"
            new_row["tab2_enable"] = "0"
            new_row["tab2_show"] = "0"
            new_row["settings_show"] = "0"
        else:
            new_row["tab1"] = "0"
            new_row["tab2"] = "0"

        # Append only after header validation and duplicate re-check.
        with path.open(
            "a",
            encoding="utf-8",
            newline=""
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=fieldnames,
                extrasaction="ignore"
            )
            writer.writerow(new_row)
            f.flush()
            try:
                os.fsync(f.fileno())
            except OSError:
                pass

        return True, ip, host, str(path)

    finally:
        _release_lock(fd, lock_path)


def _load_access_record_lan(
    raw_path: str,
    app_root: Path
):
    """
    Central access config, fail closed.

    Preferred schema v6:
      ip,name,status,
      tab1_enable,tab1_show,
      tab2_enable,tab2_show,
      tab3_enable,tab3_show,
      tab4_enable,tab4_show,
      tab5_enable,tab5_show,
      tab6_enable,tab6_show,
      settings_show

    tab6 = Sample Register. Older schemas remain readable; when tab6
    columns are absent, Sample Register is fail-closed.

    Backward compatibility:
      ip,name,status,tab1,tab2
    maps tab1/tab2 to both enable and show.
    """
    path = _resolve_path(raw_path, app_root)
    local_ips = local_ipv4_addresses()

    if not path.exists():
        raise RuntimeError(
            f"ACCESS_CONFIG_NOT_FOUND:{path}"
        )

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline=""
    ) as f:
        reader = csv.DictReader(f)

        fields = {
            str(x or "").strip().lower()
            for x in (reader.fieldnames or [])
        }

        common = {"ip", "name", "status"}
        v6_fields = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "tab4_enable",
            "tab4_show",
            "tab5_enable",
            "tab5_show",
            "tab6_enable",
            "tab6_show",
            "settings_show",
        }
        v5_fields = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "tab4_enable",
            "tab4_show",
            "tab5_enable",
            "tab5_show",
            "settings_show",
        }
        v4_fields = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "tab4_enable",
            "tab4_show",
            "settings_show",
        }
        v3_fields = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "tab3_enable",
            "tab3_show",
            "settings_show",
        }
        new_fields = {
            "tab1_enable",
            "tab1_show",
            "tab2_enable",
            "tab2_show",
            "settings_show",
        }
        old_fields = {"tab1", "tab2"}

        if not common.issubset(fields):
            raise RuntimeError(
                "ACCESS_CONFIG_INVALID_HEADER"
            )

        is_v6 = v6_fields.issubset(fields)
        is_v5 = v5_fields.issubset(fields)
        is_v4 = v4_fields.issubset(fields)
        is_v3 = v3_fields.issubset(fields)
        is_v2 = new_fields.issubset(fields)
        is_v1 = old_fields.issubset(fields)

        if not is_v6 and not is_v5 and not is_v4 and not is_v3 and not is_v2 and not is_v1:
            raise RuntimeError(
                "ACCESS_CONFIG_INVALID_PERMISSION_FIELDS"
            )

        for raw in reader:
            row = {
                str(k or "").strip().lower():
                str(v or "").strip()
                for k, v in raw.items()
            }

            if row.get("ip") not in local_ips:
                continue

            if is_v6 or is_v5 or is_v4 or is_v3 or is_v2:
                tab1_enable = _bool01(
                    row.get("tab1_enable")
                )
                tab1_show = _bool01(
                    row.get("tab1_show")
                )
                tab2_enable = _bool01(
                    row.get("tab2_enable")
                )
                tab2_show = _bool01(
                    row.get("tab2_show")
                )
                if is_v6 or is_v5 or is_v4 or is_v3:
                    tab3_enable = _bool01(
                        row.get("tab3_enable")
                    )
                    tab3_show = _bool01(
                        row.get("tab3_show")
                    )
                else:
                    tab3_enable = False
                    tab3_show = False

                if is_v6 or is_v5 or is_v4:
                    tab4_enable = _bool01(
                        row.get("tab4_enable")
                    )
                    tab4_show = _bool01(
                        row.get("tab4_show")
                    )
                else:
                    tab4_enable = False
                    tab4_show = False

                if is_v6 or is_v5:
                    tab5_enable = _bool01(row.get("tab5_enable"))
                    tab5_show = _bool01(row.get("tab5_show"))
                else:
                    tab5_enable = False
                    tab5_show = False

                if is_v6:
                    tab6_enable = _bool01(row.get("tab6_enable"))
                    tab6_show = _bool01(row.get("tab6_show"))
                else:
                    tab6_enable = False
                    tab6_show = False

                settings_show = _bool01(
                    row.get("settings_show")
                )
            else:
                # Legacy: visible when enabled.
                tab1_enable = _bool01(row.get("tab1"))
                tab1_show = tab1_enable
                tab2_enable = _bool01(row.get("tab2"))
                tab2_show = tab2_enable
                tab3_enable = False
                tab3_show = False
                tab4_enable = False
                tab4_show = False
                tab5_enable = False
                tab5_show = False
                tab6_enable = False
                tab6_show = False
                settings_show = False

            return (
                AccessRecord(
                    ip=row.get("ip", ""),
                    name=row.get("name", ""),
                    status=row.get("status", ""),
                    tab1_enable=tab1_enable,
                    tab1_show=tab1_show,
                    tab2_enable=tab2_enable,
                    tab2_show=tab2_show,
                    tab3_enable=tab3_enable,
                    tab3_show=tab3_show,
                    tab4_enable=tab4_enable,
                    tab4_show=tab4_show,
                    tab5_enable=tab5_enable,
                    tab5_show=tab5_show,
                    tab6_enable=tab6_enable,
                    tab6_show=tab6_show,
                    settings_show=settings_show,
                    source_path=str(path),
                    source_mode="LAN",
                    cached_at="",
                ),
                local_ips,
                str(path),
            )

    return None, local_ips, str(path)



def _record_to_cache_payload(
    record: AccessRecord
) -> dict:
    return {
        "version": 1,
        "cached_at": datetime.now().isoformat(
            timespec="seconds"
        ),
        "record": {
            "ip": record.ip,
            "name": record.name,
            "status": record.status,
            "tab1_enable": int(record.tab1_enable),
            "tab1_show": int(record.tab1_show),
            "tab2_enable": int(record.tab2_enable),
            "tab2_show": int(record.tab2_show),
            "tab3_enable": int(record.tab3_enable),
            "tab3_show": int(record.tab3_show),
            "tab4_enable": int(record.tab4_enable),
            "tab4_show": int(record.tab4_show),
            "tab5_enable": int(record.tab5_enable),
            "tab5_show": int(record.tab5_show),
            "tab6_enable": int(record.tab6_enable),
            "tab6_show": int(record.tab6_show),
            "settings_show": int(record.settings_show),
            "source_path": record.source_path,
        },
    }


def _write_access_snapshot(
    record: AccessRecord
) -> None:
    """
    Cache the latest LAN decision locally.

    Active, pending, and disabled states are all cached. This is important:
    when LAN was available and revoked access, the next offline launch must
    not resurrect an older active snapshot.
    """
    path = access_snapshot_path()
    temp = path.with_suffix(
        ".json.tmp"
    )
    payload = _record_to_cache_payload(
        record
    )

    with temp.open(
        "w",
        encoding="utf-8"
    ) as f:
        json.dump(
            payload,
            f,
            ensure_ascii=False,
            indent=2
        )
        f.flush()
        try:
            os.fsync(
                f.fileno()
            )
        except OSError:
            pass

    temp.replace(
        path
    )


def _read_access_snapshot(
    local_ips: list[str]
) -> AccessRecord | None:
    path = access_snapshot_path()

    if not path.exists():
        return None

    try:
        payload = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
        raw = dict(
            payload.get(
                "record",
                {}
            )
        )
        cached_at = str(
            payload.get(
                "cached_at",
                ""
            )
            or ""
        )

        ip = str(
            raw.get(
                "ip",
                ""
            )
            or ""
        ).strip()

        # A cached grant belongs only to this exact machine/IP.
        if (
            not ip
            or ip not in set(local_ips)
        ):
            return None

        return AccessRecord(
            ip=ip,
            name=str(
                raw.get(
                    "name",
                    ""
                )
                or ""
            ).strip(),
            status=str(
                raw.get(
                    "status",
                    ""
                )
                or ""
            ).strip(),
            tab1_enable=_bool01(
                raw.get(
                    "tab1_enable"
                )
            ),
            tab1_show=_bool01(
                raw.get(
                    "tab1_show"
                )
            ),
            tab2_enable=_bool01(
                raw.get(
                    "tab2_enable"
                )
            ),
            tab2_show=_bool01(
                raw.get(
                    "tab2_show"
                )
            ),
            tab3_enable=_bool01(
                raw.get(
                    "tab3_enable"
                )
            ),
            tab3_show=_bool01(
                raw.get(
                    "tab3_show"
                )
            ),
            tab4_enable=_bool01(
                raw.get(
                    "tab4_enable"
                )
            ),
            tab4_show=_bool01(
                raw.get(
                    "tab4_show"
                )
            ),
            tab5_enable=_bool01(raw.get("tab5_enable")),
            tab5_show=_bool01(raw.get("tab5_show")),
            tab6_enable=_bool01(raw.get("tab6_enable")),
            tab6_show=_bool01(raw.get("tab6_show")),
            settings_show=_bool01(
                raw.get(
                    "settings_show"
                )
            ),
            source_path=str(
                raw.get(
                    "source_path",
                    ""
                )
                or ""
            ),
            source_mode="LOCAL_CACHE",
            cached_at=cached_at,
        )
    except Exception:
        return None


def load_access_record(
    raw_path: str,
    app_root: Path
):
    """
    Online-first access control.

    Priority:
      1) central LAN access_control.csv
      2) per-machine local snapshot, ONLY when LAN read fails

    If LAN is reachable and the machine is unknown, this returns None and
    the normal pending-enrollment flow is used. A stale local grant is never
    used while the central source of truth is available.
    """
    local_ips = local_ipv4_addresses()

    try:
        (
            record,
            lan_ips,
            resolved_path,
        ) = _load_access_record_lan(
            raw_path,
            app_root
        )

        # LAN read succeeded. Cache the exact current decision if the IP row
        # exists, including disabled/pending state.
        if record is not None:
            _write_access_snapshot(
                record
            )

        return (
            record,
            lan_ips,
            resolved_path,
        )

    except Exception as lan_error:
        cached = _read_access_snapshot(
            local_ips
        )

        if cached is not None:
            # Keep the configured LAN path as source_path when old snapshots
            # predate this field.
            if not cached.source_path:
                try:
                    cached.source_path = str(
                        _resolve_path(
                            raw_path,
                            app_root
                        )
                    )
                except Exception:
                    cached.source_path = str(
                        raw_path or ""
                    )

            return (
                cached,
                local_ips,
                cached.source_path,
            )

        raise RuntimeError(
            "ACCESS_LAN_UNAVAILABLE_AND_NO_LOCAL_CACHE:"
            + str(lan_error)
        ) from lan_error

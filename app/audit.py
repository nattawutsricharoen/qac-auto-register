from __future__ import annotations

import json
import os
import socket
import threading
from datetime import datetime
from pathlib import Path

from .runtime_paths import pending_log_dir


class AuditLogger:
    """
    Central-first system log.

    Desired destination:
      <directory containing access_control.csv>\\<machine_ip>.jsonl

    If LAN is unavailable, records are appended to a local pending queue.
    Pending records are replayed to the central file when LAN is available.
    """

    def __init__(
        self,
        app_root: Path,
        log_dir: str = "logs",
        user_name: str = "",
        user_ip: str = "",
    ):
        self.app_root = Path(
            app_root
        )
        self.user_name = user_name
        self.user_ip = user_ip
        self.hostname = socket.gethostname()
        self._lock = threading.RLock()

        # Keep this legacy directory only for compatibility/diagnostics.
        legacy = Path(
            log_dir
        )
        if not legacy.is_absolute():
            legacy = self.app_root / legacy
        self.legacy_log_dir = legacy

        self.pending_dir = pending_log_dir()
        self.central_access_path = None
        self.central_log_path = None

    def set_identity(
        self,
        user_name: str,
        user_ip: str
    ):
        self.user_name = str(
            user_name or ""
        ).strip()
        self.user_ip = str(
            user_ip or ""
        ).strip()

        # If central location is already known, changing identity changes the
        # target filename as requested by the user.
        if self.central_access_path:
            self.configure_central(
                self.central_access_path
            )

    @staticmethod
    def _safe_ip_filename(
        value: str
    ) -> str:
        raw = str(
            value or "UNKNOWN_IP"
        ).strip()

        return "".join(
            ch
            if (
                ch.isalnum()
                or ch in ".-_"
            )
            else "_"
            for ch in raw
        ) or "UNKNOWN_IP"

    def configure_central(
        self,
        access_config_path: str | Path
    ):
        raw = str(
            access_config_path or ""
        ).strip()

        if not raw:
            return

        access_path = Path(
            raw
        )

        self.central_access_path = str(
            access_path
        )

        filename = (
            self._safe_ip_filename(
                self.user_ip
            )
            + ".jsonl"
        )

        # Same directory as central access_control.csv.
        self.central_log_path = (
            access_path.parent
            / filename
        )

        self.flush_pending()

    def _pending_path(
        self
    ) -> Path:
        return (
            self.pending_dir
            / (
                self._safe_ip_filename(
                    self.user_ip
                )
                + ".pending.jsonl"
            )
        )

    def _payload(
        self,
        action: str,
        status: str,
        details: dict
    ) -> dict:
        now = datetime.now()

        return {
            "timestamp": now.isoformat(
                timespec="milliseconds"
            ),
            "action": action,
            "status": status,
            "user_name": self.user_name,
            "ip": self.user_ip,
            "hostname": self.hostname,
            "details": details,
        }

    @staticmethod
    def _append_jsonl(
        path: Path,
        payload: dict
    ):
        path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

        with path.open(
            "a",
            encoding="utf-8"
        ) as f:
            f.write(
                json.dumps(
                    payload,
                    ensure_ascii=False,
                    default=str
                )
                + "\n"
            )
            f.flush()

            try:
                os.fsync(
                    f.fileno()
                )
            except OSError:
                pass

    def _write_central(
        self,
        payload: dict
    ) -> bool:
        if self.central_log_path is None:
            return False

        try:
            self._append_jsonl(
                self.central_log_path,
                payload
            )
            return True
        except Exception:
            return False

    def _queue_pending(
        self,
        payload: dict
    ):
        self._append_jsonl(
            self._pending_path(),
            payload
        )

    def flush_pending(
        self
    ) -> int:
        """
        Replay local pending logs to LAN.

        The local file is removed only after every line was appended
        successfully.
        """
        with self._lock:
            if self.central_log_path is None:
                return 0

            path = self._pending_path()

            if not path.exists():
                return 0

            try:
                lines = path.read_text(
                    encoding="utf-8"
                ).splitlines()
            except Exception:
                return 0

            sent = 0

            for line in lines:
                if not line.strip():
                    continue

                try:
                    payload = json.loads(
                        line
                    )
                except Exception:
                    continue

                if not self._write_central(
                    payload
                ):
                    return sent

                sent += 1

            try:
                path.unlink(
                    missing_ok=True
                )
            except Exception:
                pass

            return sent

    def write(
        self,
        action: str,
        status: str = "INFO",
        **details
    ):
        payload = self._payload(
            action,
            status,
            details
        )

        with self._lock:
            # Try to flush prior offline records first.
            self.flush_pending()

            if self._write_central(
                payload
            ):
                return

            # LAN unavailable / central target not configured yet.
            # Never block QAC work because logging failed.
            self._queue_pending(
                payload
            )

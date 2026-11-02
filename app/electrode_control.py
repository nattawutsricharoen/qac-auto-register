from __future__ import annotations

import json
import re
import sqlite3
import threading
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable


ELECTRODE_RE = re.compile(r"^(?P<code>[A-Za-z0-9]+)-(?P<serial>[A-Za-z0-9]+?)(?:-R(?P<reuse>[1-9][0-9]*))?$", re.IGNORECASE)

ACTIVE_STATES = {
    "SPARE_ISSUED",
    "PD_RECEIVED",
    "LINE_STOCK",
    "INSTALLED",
    "WAITING_RETURN",
}
TERMINAL_STATES = {"COMPLETE", "SCRAPPED", "VOID"}


class ElectrodeError(RuntimeError):
    pass


class ElectrodeIdentityError(ElectrodeError):
    pass


class ElectrodeStateError(ElectrodeError):
    pass


class ElectrodePermissionError(ElectrodeError):
    pass


@dataclass(frozen=True)
class ElectrodeIdentity:
    electrode_code: str
    serial: str
    reuse_cycle: int
    base_no: str
    display_no: str


def parse_electrode_no(value: str) -> ElectrodeIdentity:
    raw = str(value or "").strip().upper()
    match = ELECTRODE_RE.fullmatch(raw)
    if not match:
        raise ElectrodeIdentityError(f"รูปแบบ Electrode No. ไม่ถูกต้อง: {value!r}")
    code = match.group("code").upper()
    serial = match.group("serial").upper()
    reuse = int(match.group("reuse") or 0)
    base = f"{code}-{serial}"
    display = base if reuse == 0 else f"{base}-R{reuse}"
    return ElectrodeIdentity(code, serial, reuse, base, display)


def utc_now_text() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SQLiteElectrodeRepository:
    """Transactional reference repository used by the desktop client and tests.

    It is intentionally local-file only. Do not place this DB on an SMB share.
    The same service contract can later be implemented by MariaDB/API without
    changing QAC business logic.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._write_lock = threading.RLock()
        self._init_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path, timeout=15.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=15000")
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA synchronous=NORMAL")
        return conn

    @contextmanager
    def _tx(self, write: bool = False):
        lock = self._write_lock if write else _NullLock()
        with lock:
            conn = self._connect()
            try:
                conn.execute("BEGIN IMMEDIATE" if write else "BEGIN")
                yield conn
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                conn.close()

    def _init_schema(self) -> None:
        with self._write_lock:
            conn = self._connect()
            try:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS electrode_type_master (
                        electrode_code TEXT PRIMARY KEY,
                        description TEXT NOT NULL DEFAULT '',
                        spec TEXT NOT NULL DEFAULT '',
                        drawing_path TEXT NOT NULL DEFAULT '',
                        is_active INTEGER NOT NULL DEFAULT 1 CHECK(is_active IN (0,1)),
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL
                    );

                    CREATE TABLE IF NOT EXISTS machine_positions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        line TEXT NOT NULL,
                        machine TEXT NOT NULL,
                        position TEXT NOT NULL,
                        status TEXT NOT NULL DEFAULT 'ACTIVE' CHECK(status IN ('ACTIVE','INACTIVE','DISABLED')),
                        drawing_path TEXT NOT NULL DEFAULT '',
                        snapshot_required INTEGER NOT NULL DEFAULT 1 CHECK(snapshot_required IN (0,1)),
                        UNIQUE(line, machine, position)
                    );

                    CREATE TABLE IF NOT EXISTS electrode_compatibility (
                        electrode_code TEXT NOT NULL,
                        position_id INTEGER NOT NULL,
                        PRIMARY KEY(electrode_code, position_id),
                        FOREIGN KEY(electrode_code) REFERENCES electrode_type_master(electrode_code),
                        FOREIGN KEY(position_id) REFERENCES machine_positions(id)
                    );

                    CREATE TABLE IF NOT EXISTS electrode_units (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        base_no TEXT NOT NULL UNIQUE,
                        electrode_code TEXT NOT NULL,
                        serial TEXT NOT NULL,
                        current_reuse_cycle INTEGER NOT NULL DEFAULT 0,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY(electrode_code) REFERENCES electrode_type_master(electrode_code)
                    );

                    CREATE TABLE IF NOT EXISTS electrode_cycles (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        unit_id INTEGER NOT NULL,
                        reuse_cycle INTEGER NOT NULL,
                        display_no TEXT NOT NULL UNIQUE,
                        lifecycle_status TEXT NOT NULL,
                        issued_line TEXT,
                        current_position_id INTEGER,
                        spare_issued_at TEXT,
                        pd_received_at TEXT,
                        installed_at TEXT,
                        removed_at TEXT,
                        pd_returned_at TEXT,
                        completed_at TEXT,
                        initial_shot INTEGER,
                        current_shot INTEGER,
                        final_shot INTEGER,
                        created_at TEXT NOT NULL,
                        updated_at TEXT NOT NULL,
                        UNIQUE(unit_id, reuse_cycle),
                        FOREIGN KEY(unit_id) REFERENCES electrode_units(id),
                        FOREIGN KEY(current_position_id) REFERENCES machine_positions(id)
                    );

                    CREATE TABLE IF NOT EXISTS electrode_transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        cycle_id INTEGER NOT NULL,
                        event_type TEXT NOT NULL,
                        from_location TEXT NOT NULL DEFAULT '',
                        to_location TEXT NOT NULL DEFAULT '',
                        line TEXT NOT NULL DEFAULT '',
                        position_id INTEGER,
                        shot INTEGER,
                        actor_department TEXT NOT NULL,
                        actor_id TEXT NOT NULL DEFAULT '',
                        event_at TEXT NOT NULL,
                        payload_json TEXT NOT NULL DEFAULT '{}',
                        FOREIGN KEY(cycle_id) REFERENCES electrode_cycles(id),
                        FOREIGN KEY(position_id) REFERENCES machine_positions(id)
                    );

                    CREATE INDEX IF NOT EXISTS idx_cycles_status ON electrode_cycles(lifecycle_status);
                    CREATE INDEX IF NOT EXISTS idx_cycles_line_status ON electrode_cycles(issued_line, lifecycle_status);
                    CREATE INDEX IF NOT EXISTS idx_cycles_position_status ON electrode_cycles(current_position_id, lifecycle_status);
                    CREATE INDEX IF NOT EXISTS idx_tx_cycle_time ON electrode_transactions(cycle_id, event_at);
                    CREATE INDEX IF NOT EXISTS idx_units_code ON electrode_units(electrode_code);
                    """
                )
            finally:
                conn.close()

    def upsert_type(self, electrode_code: str, *, description: str = "", spec: str = "", drawing_path: str = "", actor_department: str = "SPAREPART") -> None:
        if actor_department.upper() != "SPAREPART":
            raise ElectrodePermissionError("Electrode Master แก้ไขได้เฉพาะ Spare Part")
        code = str(electrode_code or "").strip().upper()
        if not code or "-" in code:
            raise ElectrodeIdentityError("Electrode Code ไม่ถูกต้อง")
        now = utc_now_text()
        with self._tx(write=True) as conn:
            conn.execute(
                """INSERT INTO electrode_type_master(electrode_code,description,spec,drawing_path,is_active,created_at,updated_at)
                   VALUES(?,?,?,?,1,?,?)
                   ON CONFLICT(electrode_code) DO UPDATE SET description=excluded.description,spec=excluded.spec,drawing_path=excluded.drawing_path,updated_at=excluded.updated_at""",
                (code, description, spec, drawing_path, now, now),
            )

    def add_position(self, line: str, machine: str, position: str, *, status: str = "ACTIVE", drawing_path: str = "") -> int:
        status = status.upper()
        if status not in {"ACTIVE", "INACTIVE", "DISABLED"}:
            raise ValueError("status ไม่ถูกต้อง")
        with self._tx(write=True) as conn:
            conn.execute(
                """INSERT INTO machine_positions(line,machine,position,status,drawing_path)
                   VALUES(?,?,?,?,?)
                   ON CONFLICT(line,machine,position) DO UPDATE SET status=excluded.status,drawing_path=excluded.drawing_path""",
                (line.strip(), machine.strip(), position.strip(), status, drawing_path),
            )
            row = conn.execute("SELECT id FROM machine_positions WHERE line=? AND machine=? AND position=?", (line.strip(), machine.strip(), position.strip())).fetchone()
            return int(row[0])

    def allow_compatibility(self, electrode_code: str, position_id: int, *, actor_department: str = "SPAREPART") -> None:
        if actor_department.upper() != "SPAREPART":
            raise ElectrodePermissionError("Compatibility Master แก้ไขได้เฉพาะ Spare Part")
        with self._tx(write=True) as conn:
            conn.execute("INSERT OR IGNORE INTO electrode_compatibility(electrode_code,position_id) VALUES(?,?)", (electrode_code.upper(), int(position_id)))

    def _position(self, conn: sqlite3.Connection, position_id: int) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM machine_positions WHERE id=?", (int(position_id),)).fetchone()
        if not row:
            raise ElectrodeStateError(f"ไม่พบ Machine Position id={position_id}")
        return row

    def _cycle_by_display(self, conn: sqlite3.Connection, electrode_no: str) -> sqlite3.Row:
        ident = parse_electrode_no(electrode_no)
        row = conn.execute(
            """SELECT c.*, u.base_no, u.electrode_code, u.serial
               FROM electrode_cycles c JOIN electrode_units u ON u.id=c.unit_id
               WHERE c.display_no=?""",
            (ident.display_no,),
        ).fetchone()
        if not row:
            raise ElectrodeStateError(f"ไม่พบ Electrode ในระบบ: {ident.display_no}")
        return row

    def _log(self, conn: sqlite3.Connection, cycle_id: int, event_type: str, *, actor_department: str, actor_id: str = "", from_location: str = "", to_location: str = "", line: str = "", position_id: int | None = None, shot: int | None = None, payload: dict | None = None, at: str | None = None) -> None:
        conn.execute(
            """INSERT INTO electrode_transactions(cycle_id,event_type,from_location,to_location,line,position_id,shot,actor_department,actor_id,event_at,payload_json)
               VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
            (cycle_id, event_type, from_location, to_location, line, position_id, shot, actor_department.upper(), actor_id, at or utc_now_text(), json.dumps(payload or {}, ensure_ascii=False, sort_keys=True)),
        )

    def spare_issue(self, electrode_no: str, line: str, *, actor_id: str = "") -> int:
        """Spare Part is the only authority that introduces a serialized cycle."""
        ident = parse_electrode_no(electrode_no)
        now = utc_now_text()
        with self._tx(write=True) as conn:
            type_row = conn.execute("SELECT * FROM electrode_type_master WHERE electrode_code=? AND is_active=1", (ident.electrode_code,)).fetchone()
            if not type_row:
                raise ElectrodeStateError(f"Electrode Code {ident.electrode_code} ยังไม่มี Active Master")
            unit = conn.execute("SELECT * FROM electrode_units WHERE base_no=?", (ident.base_no,)).fetchone()
            if unit is None:
                if ident.reuse_cycle != 0:
                    raise ElectrodeStateError("Electrode ใหม่ต้องเริ่มจาก Base No. ก่อนสร้าง Reuse")
                cur = conn.execute("INSERT INTO electrode_units(base_no,electrode_code,serial,current_reuse_cycle,created_at) VALUES(?,?,?,?,?)", (ident.base_no, ident.electrode_code, ident.serial, 0, now))
                unit_id = int(cur.lastrowid)
            else:
                unit_id = int(unit["id"])
                expected = int(unit["current_reuse_cycle"])
                existing = conn.execute("SELECT id FROM electrode_cycles WHERE unit_id=? AND reuse_cycle=?", (unit_id, ident.reuse_cycle)).fetchone()
                if existing:
                    raise ElectrodeStateError(f"Electrode cycle มีอยู่แล้ว: {ident.display_no}")
                if ident.reuse_cycle != expected:
                    raise ElectrodeStateError("ห้ามสร้าง Reuse cycle ด้วย spare_issue; ใช้ create_reuse_cycle")
            cur = conn.execute(
                """INSERT INTO electrode_cycles(unit_id,reuse_cycle,display_no,lifecycle_status,issued_line,spare_issued_at,created_at,updated_at)
                   VALUES(?,?,?,'SPARE_ISSUED',?,?,?,?)""",
                (unit_id, ident.reuse_cycle, ident.display_no, line.strip(), now, now, now),
            )
            cycle_id = int(cur.lastrowid)
            self._log(conn, cycle_id, "SPARE_ISSUE", actor_department="SPAREPART", actor_id=actor_id, from_location="SPAREPART", to_location=f"{line.strip()}_STAGING", line=line.strip(), at=now)
            return cycle_id

    def pd_receive(self, electrode_no: str, line: str, *, actor_id: str = "") -> None:
        now = utc_now_text()
        with self._tx(write=True) as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            if cycle["lifecycle_status"] != "SPARE_ISSUED":
                raise ElectrodeStateError(f"รับเข้า PD ไม่ได้ สถานะปัจจุบัน={cycle['lifecycle_status']}")
            if str(cycle["issued_line"] or "").casefold() != line.strip().casefold():
                raise ElectrodeStateError(f"Electrode นี้ Spare Part เบิกให้ {cycle['issued_line']} ไม่ใช่ {line}")
            conn.execute("UPDATE electrode_cycles SET lifecycle_status='PD_RECEIVED',pd_received_at=?,updated_at=? WHERE id=?", (now, now, cycle["id"]))
            self._log(conn, cycle["id"], "PD_RECEIVE", actor_department="PD", actor_id=actor_id, from_location="LINE_STAGING", to_location="PD_CONTROL", line=line.strip(), at=now)

    def pd_withdraw_to_line_stock(self, electrode_no: str, line: str, *, actor_id: str = "") -> None:
        now = utc_now_text()
        with self._tx(write=True) as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            if cycle["lifecycle_status"] != "PD_RECEIVED":
                raise ElectrodeStateError(f"เบิกออก PD ไม่ได้ สถานะปัจจุบัน={cycle['lifecycle_status']}")
            if str(cycle["issued_line"] or "").casefold() != line.strip().casefold():
                raise ElectrodeStateError("Line ไม่ตรงกับ Spare Part issue")
            conn.execute("UPDATE electrode_cycles SET lifecycle_status='LINE_STOCK',updated_at=? WHERE id=?", (now, cycle["id"]))
            self._log(conn, cycle["id"], "PD_WITHDRAW", actor_department="PD", actor_id=actor_id, from_location="PD_CONTROL", to_location=f"{line.strip()}_LINE_STOCK", line=line.strip(), at=now)

    def install(self, electrode_no: str, position_id: int, *, initial_shot: int | None = None, actor_id: str = "") -> None:
        now = utc_now_text()
        with self._tx(write=True) as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            if cycle["lifecycle_status"] not in {"PD_RECEIVED", "LINE_STOCK"}:
                raise ElectrodeStateError(f"ติดตั้งไม่ได้ สถานะปัจจุบัน={cycle['lifecycle_status']}")
            pos = self._position(conn, position_id)
            if pos["status"] != "ACTIVE":
                raise ElectrodeStateError("Machine Position ยังไม่ได้ Active")
            if str(cycle["issued_line"] or "").casefold() != str(pos["line"]).casefold():
                raise ElectrodeStateError(f"Electrode เบิกให้ {cycle['issued_line']} แต่ตำแหน่งอยู่ {pos['line']}")
            allowed = conn.execute("SELECT 1 FROM electrode_compatibility WHERE electrode_code=? AND position_id=?", (cycle["electrode_code"], int(position_id))).fetchone()
            if not allowed:
                raise ElectrodeStateError(f"Electrode Code {cycle['electrode_code']} ใช้กับ {pos['machine']} / {pos['position']} ไม่ได้")
            occupied = conn.execute("SELECT display_no FROM electrode_cycles WHERE current_position_id=? AND lifecycle_status='INSTALLED'", (int(position_id),)).fetchone()
            if occupied:
                raise ElectrodeStateError(f"ตำแหน่งนี้มี Electrode ติดตั้งอยู่แล้ว: {occupied['display_no']}")
            conn.execute(
                """UPDATE electrode_cycles SET lifecycle_status='INSTALLED',current_position_id=?,installed_at=?,initial_shot=?,current_shot=?,updated_at=? WHERE id=?""",
                (int(position_id), now, initial_shot, initial_shot, now, cycle["id"]),
            )
            self._log(conn, cycle["id"], "INSTALL", actor_department="PD", actor_id=actor_id, from_location=f"{pos['line']}_LINE_STOCK", to_location=f"{pos['line']}:{pos['machine']}:{pos['position']}", line=pos["line"], position_id=int(position_id), shot=initial_shot, at=now)

    def snapshot(self, electrode_no: str, shot: int, *, actor_id: str = "", event_at: str | None = None) -> None:
        with self._tx(write=True) as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            if cycle["lifecycle_status"] != "INSTALLED":
                raise ElectrodeStateError("Snapshot ทำได้เฉพาะ Electrode ที่ติดตั้งอยู่")
            if shot < 0:
                raise ElectrodeStateError("Shot ต้องไม่ติดลบ")
            current = cycle["current_shot"]
            if current is not None and shot < int(current):
                raise ElectrodeStateError(f"Shot ย้อนกลับไม่ได้ (current={current}, new={shot})")
            now = event_at or utc_now_text()
            conn.execute("UPDATE electrode_cycles SET current_shot=?,updated_at=? WHERE id=?", (int(shot), now, cycle["id"]))
            self._log(conn, cycle["id"], "SNAPSHOT", actor_department="PD", actor_id=actor_id, line=cycle["issued_line"] or "", position_id=cycle["current_position_id"], shot=int(shot), at=now)

    def remove_for_return(self, electrode_no: str, final_shot: int | None, *, actor_id: str = "") -> None:
        now = utc_now_text()
        with self._tx(write=True) as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            if cycle["lifecycle_status"] != "INSTALLED":
                raise ElectrodeStateError("ถอด Electrode ได้เฉพาะตัวที่ติดตั้งอยู่")
            if final_shot is not None and cycle["current_shot"] is not None and int(final_shot) < int(cycle["current_shot"]):
                raise ElectrodeStateError("Final Shot น้อยกว่า Shot ล่าสุดไม่ได้")
            pos = self._position(conn, int(cycle["current_position_id"]))
            conn.execute("UPDATE electrode_cycles SET lifecycle_status='WAITING_RETURN',removed_at=?,final_shot=?,current_shot=COALESCE(?,current_shot),updated_at=? WHERE id=?", (now, final_shot, final_shot, now, cycle["id"]))
            self._log(conn, cycle["id"], "REMOVE", actor_department="PD", actor_id=actor_id, from_location=f"{pos['line']}:{pos['machine']}:{pos['position']}", to_location=f"{pos['line']}_WAITING_RETURN", line=pos["line"], position_id=int(pos["id"]), shot=final_shot, at=now)

    def pd_return(self, electrode_no: str, line: str, *, actor_id: str = "") -> None:
        """Close exactly the serialized cycle that was issued; no quantity-only return."""
        now = utc_now_text()
        with self._tx(write=True) as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            if str(cycle["issued_line"] or "").casefold() != line.strip().casefold():
                raise ElectrodeStateError(f"Return mismatch: Electrode นี้เป็นของ {cycle['issued_line']}")
            if cycle["lifecycle_status"] not in {"WAITING_RETURN", "LINE_STOCK", "PD_RECEIVED"}:
                raise ElectrodeStateError(f"ส่งคืนไม่ได้ สถานะปัจจุบัน={cycle['lifecycle_status']}")
            if not cycle["spare_issued_at"] or not cycle["pd_received_at"]:
                raise ElectrodeStateError("Lifecycle ยังไม่ครบ Spare Issue + PD Receive")
            conn.execute(
                """UPDATE electrode_cycles SET lifecycle_status='COMPLETE',pd_returned_at=?,completed_at=?,current_position_id=NULL,updated_at=? WHERE id=?""",
                (now, now, now, cycle["id"]),
            )
            self._log(conn, cycle["id"], "PD_RETURN", actor_department="PD", actor_id=actor_id, from_location=f"{line.strip()}_RETURN", to_location="SPAREPART", line=line.strip(), at=now)

    def create_reuse_cycle(self, base_no: str, line: str, *, actor_id: str = "") -> str:
        """Spare Part creates the next Rn only after previous cycle is complete."""
        base = parse_electrode_no(base_no)
        if base.reuse_cycle != 0:
            base_no = base.base_no
        now = utc_now_text()
        with self._tx(write=True) as conn:
            unit = conn.execute("SELECT * FROM electrode_units WHERE base_no=?", (base.base_no,)).fetchone()
            if not unit:
                raise ElectrodeStateError(f"ไม่พบ Base Electrode: {base.base_no}")
            current = int(unit["current_reuse_cycle"])
            prev = conn.execute("SELECT * FROM electrode_cycles WHERE unit_id=? AND reuse_cycle=?", (unit["id"], current)).fetchone()
            if not prev or prev["lifecycle_status"] != "COMPLETE":
                raise ElectrodeStateError("สร้าง Reuse ไม่ได้จนกว่า cycle ปัจจุบันจะ COMPLETE")
            next_cycle = current + 1
            display = f"{base.base_no}-R{next_cycle}"
            cur = conn.execute(
                """INSERT INTO electrode_cycles(unit_id,reuse_cycle,display_no,lifecycle_status,issued_line,spare_issued_at,created_at,updated_at)
                   VALUES(?,?,?,'SPARE_ISSUED',?,?,?,?)""",
                (unit["id"], next_cycle, display, line.strip(), now, now, now),
            )
            cycle_id = int(cur.lastrowid)
            conn.execute("UPDATE electrode_units SET current_reuse_cycle=? WHERE id=?", (next_cycle, unit["id"]))
            self._log(conn, cycle_id, "SPARE_REUSE_ISSUE", actor_department="SPAREPART", actor_id=actor_id, from_location="SPAREPART", to_location=f"{line.strip()}_STAGING", line=line.strip(), payload={"previous_cycle": current}, at=now)
            return display

    def get_active_cycles(self, *, line: str | None = None) -> list[dict]:
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        args: list[object] = list(sorted(ACTIVE_STATES))
        sql = f"""SELECT c.*,u.base_no,u.electrode_code,u.serial,p.line AS position_line,p.machine,p.position
                  FROM electrode_cycles c JOIN electrode_units u ON u.id=c.unit_id
                  LEFT JOIN machine_positions p ON p.id=c.current_position_id
                  WHERE c.lifecycle_status IN ({placeholders})"""
        if line:
            sql += " AND c.issued_line=?"
            args.append(line)
        sql += " ORDER BY c.updated_at DESC"
        with self._tx() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def get_history(self, base_or_display_no: str) -> list[dict]:
        ident = parse_electrode_no(base_or_display_no)
        with self._tx() as conn:
            unit = conn.execute("SELECT id FROM electrode_units WHERE base_no=?", (ident.base_no,)).fetchone()
            if not unit:
                return []
            return [dict(r) for r in conn.execute("SELECT * FROM electrode_cycles WHERE unit_id=? ORDER BY reuse_cycle", (unit["id"],)).fetchall()]

    def current_installed(self, line: str, machine: str, position: str) -> dict | None:
        with self._tx() as conn:
            row = conn.execute(
                """SELECT c.display_no,c.current_shot,c.installed_at,u.base_no,u.electrode_code,p.id AS position_id
                   FROM machine_positions p
                   JOIN electrode_cycles c ON c.current_position_id=p.id AND c.lifecycle_status='INSTALLED'
                   JOIN electrode_units u ON u.id=c.unit_id
                   WHERE p.line=? AND p.machine=? AND p.position=?""",
                (line, machine, position),
            ).fetchone()
            return dict(row) if row else None

    def list_positions(self, *, line: str | None = None, include_disabled: bool = False) -> list[dict]:
        sql = "SELECT id,line,machine,position,status,drawing_path,snapshot_required FROM machine_positions WHERE 1=1"
        args: list[object] = []
        if line:
            sql += " AND line=?"
            args.append(str(line).strip())
        if not include_disabled:
            sql += " AND status<>'DISABLED'"
        sql += " ORDER BY line,machine,position"
        with self._tx() as conn:
            return [dict(r) for r in conn.execute(sql, args).fetchall()]

    def list_types(self, *, active_only: bool = True) -> list[dict]:
        sql = "SELECT electrode_code,description,spec,drawing_path,is_active FROM electrode_type_master"
        if active_only:
            sql += " WHERE is_active=1"
        sql += " ORDER BY electrode_code"
        with self._tx() as conn:
            return [dict(r) for r in conn.execute(sql).fetchall()]

    def position_compatibility(self, position_id: int) -> list[str]:
        with self._tx() as conn:
            rows = conn.execute(
                "SELECT electrode_code FROM electrode_compatibility WHERE position_id=? ORDER BY electrode_code",
                (int(position_id),),
            ).fetchall()
            return [str(r[0]) for r in rows]

    def balance_summary(self) -> list[dict]:
        """Active-only operational balance; completed cycles are excluded by design."""
        placeholders = ",".join("?" for _ in ACTIVE_STATES)
        with self._tx() as conn:
            rows = conn.execute(
                f"""SELECT c.issued_line AS line,u.electrode_code,c.lifecycle_status,COUNT(*) AS qty
                    FROM electrode_cycles c JOIN electrode_units u ON u.id=c.unit_id
                    WHERE c.lifecycle_status IN ({placeholders})
                    GROUP BY c.issued_line,u.electrode_code,c.lifecycle_status
                    ORDER BY c.issued_line,u.electrode_code,c.lifecycle_status""",
                tuple(sorted(ACTIVE_STATES)),
            ).fetchall()
            return [dict(r) for r in rows]

    def transactions_for(self, electrode_no: str) -> list[dict]:
        with self._tx() as conn:
            cycle = self._cycle_by_display(conn, electrode_no)
            return [dict(r) for r in conn.execute("SELECT * FROM electrode_transactions WHERE cycle_id=? ORDER BY id", (cycle["id"],)).fetchall()]


class _NullLock:
    def __enter__(self):
        return self
    def __exit__(self, exc_type, exc, tb):
        return False


class ElectrodeSampleResolver:
    """Read-only bridge for QAC Sample Register.

    The resolver never creates/edits an electrode identity. It only exposes the
    currently installed serialized cycle for a known line/machine/position.
    """
    def __init__(self, repository: SQLiteElectrodeRepository):
        self.repository = repository

    def resolve_electrode_no(self, line: str, machine: str, position: str) -> str:
        current = self.repository.current_installed(line, machine, position)
        if not current:
            raise ElectrodeStateError(f"ไม่พบ Electrode ที่กำลังใช้งาน: {line} / {machine} / {position}")
        return str(current["display_no"])

    def resolve_shot(self, line: str, machine: str, position: str) -> int | None:
        current = self.repository.current_installed(line, machine, position)
        return None if not current or current["current_shot"] is None else int(current["current_shot"])

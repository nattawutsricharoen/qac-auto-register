"""Independent offline issue/return ledger. No QAC login or network/SMB writes.

Pending events are intentionally NOT automatically synchronized: a central single-writer
service is required to coordinate across PCs. Do not treat local data as global stock.
"""
from __future__ import annotations
import json
import re
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

PATTERN = re.compile(r'^(?P<base>[A-Z0-9]+-[A-Z0-9]+)(?:-R(?P<r>[1-5]))?$', re.I)

class ElectrodeLedgerError(ValueError): pass

def normalize_barcode(value):
    value = str(value or '').strip().upper()
    m = PATTERN.fullmatch(value)
    if not m: raise ElectrodeLedgerError('Barcode ไม่ถูกต้อง: ต้องเป็น BASE หรือ BASE-R1 ถึง -R5')
    return value, m.group('base'), int(m.group('r') or 0), value.split('-',1)[0]

def now(): return datetime.now(timezone.utc).isoformat(timespec='milliseconds')

class IssueReturnStore:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS electrode_types(code TEXT PRIMARY KEY, target_shots INTEGER NOT NULL CHECK(target_shots>0), active INTEGER NOT NULL DEFAULT 1);
                CREATE TABLE IF NOT EXISTS electrode_local_settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS electrode_destinations(id INTEGER PRIMARY KEY, code TEXT NOT NULL REFERENCES electrode_types(code), line TEXT NOT NULL, machine TEXT NOT NULL, station TEXT NOT NULL DEFAULT '', position TEXT NOT NULL DEFAULT '', active INTEGER NOT NULL DEFAULT 1, UNIQUE(code,line,machine,station,position));
                CREATE TABLE IF NOT EXISTS electrode_usage_cycles(id TEXT PRIMARY KEY, barcode TEXT NOT NULL, base_barcode TEXT NOT NULL, regrind INTEGER NOT NULL CHECK(regrind BETWEEN 0 AND 5), code TEXT NOT NULL, destination_id INTEGER NOT NULL REFERENCES electrode_destinations(id), target_shots_at_issue INTEGER NOT NULL, issued_at TEXT NOT NULL, returned_at TEXT, final_counter INTEGER CHECK(final_counter>=0), return_reason TEXT, state TEXT NOT NULL CHECK(state IN ('ISSUED','RETURNED')));
                CREATE UNIQUE INDEX IF NOT EXISTS uq_open_barcode ON electrode_usage_cycles(barcode) WHERE state='ISSUED';
                CREATE TABLE IF NOT EXISTS electrode_outbox(event_id TEXT PRIMARY KEY, cycle_id TEXT NOT NULL REFERENCES electrode_usage_cycles(id), event_type TEXT NOT NULL, event_at TEXT NOT NULL, payload_json TEXT NOT NULL, delivery_state TEXT NOT NULL DEFAULT 'PENDING' CHECK(delivery_state IN ('PENDING','SYNCED')));
                CREATE INDEX IF NOT EXISTS idx_history_barcode ON electrode_usage_cycles(base_barcode,issued_at);
            ''')

    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA foreign_keys=ON')
        db.execute('PRAGMA busy_timeout=15000')
        return db

    @staticmethod
    def _regrind_interlock_from_connection(db):
        row=db.execute("SELECT value FROM electrode_local_settings WHERE key='regrind_history_interlock'").fetchone()
        return row is None or row['value']=='1'

    def regrind_interlock_enabled(self):
        with self.connection() as db:
            row=db.execute("SELECT value FROM electrode_local_settings WHERE key='regrind_history_interlock'").fetchone()
            return row is None or row['value']=='1'  # Existing installs remain strict until Admin opts out.

    def set_regrind_interlock(self, enabled):
        with self.connection() as db:
            db.execute("INSERT INTO electrode_local_settings(key,value) VALUES('regrind_history_interlock',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",('1' if enabled else '0',))
            db.commit()

    def master_summary(self):
        with self.connection() as db:
            return [dict(x) for x in db.execute("""SELECT d.id,d.code,d.line,d.machine,d.station,d.position,
                     t.target_shots,d.active FROM electrode_destinations d
                     JOIN electrode_types t ON t.code=d.code
                     ORDER BY d.code,d.line,d.machine,d.station,d.position""")]

    def save_master_mapping(self, code, target_shots, line, machine, station='', position=''):
        """Save type and destination atomically. Existing mapping receives updated target without duplicate error."""
        code=str(code or '').strip().upper()
        fields=[str(x or '').strip() for x in (line,machine,station,position)]
        try:target=int(target_shots)
        except (TypeError, ValueError):raise ElectrodeLedgerError('Target ต้องเป็นจำนวนเต็ม')
        if not re.fullmatch(r'[A-Z0-9]+',code) or not 0<target<=2_000_000_000 or not all(fields[:2]):
            raise ElectrodeLedgerError('ระบุ Electrode Code, Target, Line และ Machine ให้ถูกต้อง')
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                db.execute('INSERT INTO electrode_types(code,target_shots) VALUES(?,?) ON CONFLICT(code) DO UPDATE SET target_shots=excluded.target_shots',(code,target))
                db.execute("""INSERT INTO electrode_destinations(code,line,machine,station,position)
                              VALUES(?,?,?,?,?) ON CONFLICT(code,line,machine,station,position)
                              DO UPDATE SET active=1""",(code,*fields))
                db.commit()
            except Exception:
                db.rollback();raise

    def set_type(self, code, target_shots):
        code = str(code).strip().upper()
        if not re.fullmatch(r'[A-Z0-9]+', code) or int(target_shots) <= 0:
            raise ElectrodeLedgerError('Code / Target ไม่ถูกต้อง')
        with self.connection() as db:
            db.execute('INSERT INTO electrode_types(code,target_shots) VALUES(?,?) ON CONFLICT(code) DO UPDATE SET target_shots=excluded.target_shots', (code,int(target_shots)))
            db.commit()

    def add_destination(self, code, line, machine, station='', position=''):
        fields = [str(x).strip() for x in (code,line,machine,station,position)]
        fields[0] = fields[0].upper()
        if not all(fields[:3]): raise ElectrodeLedgerError('ระบุ Code, Line และ Machine')
        with self.connection() as db:
            try:
                db.execute('INSERT INTO electrode_destinations(code,line,machine,station,position) VALUES(?,?,?,?,?)',fields)
                db.commit()
            except sqlite3.IntegrityError as e: raise ElectrodeLedgerError('Master / Mapping ไม่พบหรือซ้ำ') from e

    def destinations(self, code=None):
        with self.connection() as db:
            q='SELECT d.*,t.target_shots FROM electrode_destinations d JOIN electrode_types t ON d.code=t.code WHERE d.active=1 AND t.active=1'
            args=[]
            if code: q+=' AND d.code=?';args.append(code.upper())
            q+=' ORDER BY d.line,d.machine,d.station,d.position'
            return [dict(x) for x in db.execute(q,args)]

    def find_open(self, barcode):
        barcode,_,_,_=normalize_barcode(barcode)
        with self.connection() as db:
            r=db.execute("SELECT c.*,d.line,d.machine,d.station,d.position FROM electrode_usage_cycles c JOIN electrode_destinations d ON d.id=c.destination_id WHERE barcode=? AND state='ISSUED'",(barcode,)).fetchone()
            return dict(r) if r else None

    def scan(self, barcode):
        barcode,base,regrind,code=normalize_barcode(barcode)
        existing=self.find_open(barcode)
        if existing:return {'action':'RETURN','cycle':existing}
        options=self.destinations(code)
        if not options:raise ElectrodeLedgerError(f'ไม่พบ Active Target / Machine Mapping สำหรับ {code}')
        return {'action':'ISSUE','barcode':barcode,'base':base,'regrind':regrind,'options':options}

    def issue(self, barcode, destination_id):
        barcode,base,regrind,code=normalize_barcode(barcode)
        event_at=now();cycle_id=str(uuid.uuid4());event_id=str(uuid.uuid4())
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                dest=db.execute('SELECT d.*,t.target_shots FROM electrode_destinations d JOIN electrode_types t ON t.code=d.code WHERE d.id=? AND d.code=? AND d.active=1 AND t.active=1',(int(destination_id),code)).fetchone()
                if not dest:raise ElectrodeLedgerError('Mapping นี้ไม่รองรับ Barcode หรือถูกปิดใช้งาน')
                if db.execute("SELECT 1 FROM electrode_usage_cycles WHERE barcode=? AND state='ISSUED'",(barcode,)).fetchone():raise ElectrodeLedgerError('Electrode ถูกเบิกอยู่แล้ว: ห้ามเบิกซ้ำ')
                # Never silently create a second completed history for the same physical suffix.
                if db.execute('SELECT 1 FROM electrode_usage_cycles WHERE barcode=?',(barcode,)).fetchone():raise ElectrodeLedgerError('Barcode นี้เคยคืนแล้ว ไม่อนุญาตเบิกซ้ำรอบเดิม; ตรวจสอบ Regrind Barcode')
                if regrind and self._regrind_interlock_from_connection(db):
                    prior=base if regrind==1 else f'{base}-R{regrind-1}'
                    if not db.execute("SELECT 1 FROM electrode_usage_cycles WHERE barcode=? AND state='RETURNED'",(prior,)).fetchone():
                        raise ElectrodeLedgerError(f'ยังไม่พบประวัติคืนของ {prior} ก่อนเบิก {barcode}')
                payload={'barcode':barcode,'destination_id':int(destination_id),'target_shots_at_issue':int(dest['target_shots'])}
                db.execute("INSERT INTO electrode_usage_cycles(id,barcode,base_barcode,regrind,code,destination_id,target_shots_at_issue,issued_at,state) VALUES(?,?,?,?,?,?,?,?, 'ISSUED')",(cycle_id,barcode,base,regrind,code,int(destination_id),int(dest['target_shots']),event_at))
                db.execute('INSERT INTO electrode_outbox(event_id,cycle_id,event_type,event_at,payload_json) VALUES(?,?,?,?,?)',(event_id,cycle_id,'ISSUE',event_at,json.dumps(payload)))
                db.commit()
            except Exception:
                db.rollback();raise
        return cycle_id

    def return_electrode(self, barcode, final_counter, reason=''):
        barcode,_,_,_=normalize_barcode(barcode)
        try:shot=int(final_counter)
        except (TypeError,ValueError):raise ElectrodeLedgerError('Final Counter ต้องเป็นจำนวนเต็ม')
        if shot<0 or str(final_counter).strip()!=str(shot):raise ElectrodeLedgerError('Final Counter ต้องเป็นจำนวนเต็มไม่ติดลบ')
        at=now();event_id=str(uuid.uuid4())
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            try:
                row=db.execute("SELECT * FROM electrode_usage_cycles WHERE barcode=? AND state='ISSUED'",(barcode,)).fetchone()
                if not row:raise ElectrodeLedgerError('ไม่พบ ISSUE ค้าง ห้ามทำ RETURN')
                target=int(row['target_shots_at_issue'])
                if shot>=target:reason='Full counter'
                else:
                    reason=str(reason or '').strip()
                    if not reason:raise ElectrodeLedgerError('คืนก่อน Target ต้องระบุสาเหตุ')
                db.execute("UPDATE electrode_usage_cycles SET state='RETURNED',returned_at=?,final_counter=?,return_reason=? WHERE id=? AND state='ISSUED'",(at,shot,reason,row['id']))
                db.execute('INSERT INTO electrode_outbox(event_id,cycle_id,event_type,event_at,payload_json) VALUES(?,?,?,?,?)',(event_id,row['id'],'RETURN',at,json.dumps({'barcode':barcode,'final_counter':shot,'reason':reason,'target_shots_at_issue':target})))
                db.commit()
            except Exception:
                db.rollback();raise
        return reason

    def history(self, search=''):
        with self.connection() as db:
            q='''SELECT c.*,d.line,d.machine,d.station,d.position FROM electrode_usage_cycles c JOIN electrode_destinations d ON d.id=c.destination_id'''
            args=[]
            if search:
                q+=' WHERE c.barcode LIKE ? OR c.base_barcode LIKE ? OR d.machine LIKE ?'
                args=[f'%{search.upper()}%',f'%{search.upper()}%',f'%{search}%']
            q+=' ORDER BY c.issued_at DESC'
            return [dict(x) for x in db.execute(q,args)]

    def pending_count(self):
        with self.connection() as db:
            return db.execute("SELECT COUNT(*) FROM electrode_outbox WHERE delivery_state='PENDING'").fetchone()[0]

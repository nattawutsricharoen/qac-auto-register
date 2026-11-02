"""Local replacement ledger for QAC desktop Electrode Control.

Separate from spare-part lifecycle; no irreversible changes to existing cycles.
"""
from __future__ import annotations
import csv
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path


def initial_slots():
    slots=[]
    def add(machine, position, diameter, station=''):
        slots.append((machine,station,position,str(diameter)))
    for machine in ('Housing Disc Welding','Housing Bottle Welding'):
        for diameter in ('20','25'):
            for position in ('Upper','Lower'): add(machine,position,diameter)
    for diameter in ('20','25'):
        add('Housing Cap Crimp','Upper',diameter)
        for position in ('Upper','Lower'): add('Diffuser Disc Welding',position,diameter)
    for position in ('Upper','Lower'): add('Diffuser Disc Welding',position,'Common')
    for head in ('Head 1','Head 2'):
        for position in ('Piston','Collet Chuck','Collet Guide'): add('Stud Bolt Welding',position,'N/A',head)
    for station in ('Station 1','Station 2','Station 3'):
        for diameter in ('20','25'):
            for position in ('Upper','SealHead','Contacting','Base Support'):
                add('Gas Filling',position,diameter,station)
    return slots


class ReplacementError(ValueError): pass

class ReplacementStore:
    def __init__(self,path):
        self.path=Path(path); self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.tx(True) as c:
            c.executescript('''
            CREATE TABLE IF NOT EXISTS replacement_slots (
              id INTEGER PRIMARY KEY, machine TEXT NOT NULL, station TEXT NOT NULL DEFAULT '',
              position TEXT NOT NULL, diameter TEXT NOT NULL,
              enabled INTEGER NOT NULL DEFAULT 1 CHECK(enabled IN (0,1)),
              required INTEGER NOT NULL DEFAULT 1 CHECK(required IN (0,1)),
              UNIQUE(machine,station,position,diameter));
            CREATE TABLE IF NOT EXISTS replacement_current (
              slot_id INTEGER PRIMARY KEY REFERENCES replacement_slots(id),
              electrode_no TEXT NOT NULL, start_counter INTEGER NOT NULL CHECK(start_counter>=0),
              installed_at TEXT NOT NULL, actor TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS replacement_history (
              id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES replacement_slots(id),
              old_no TEXT NOT NULL, old_start INTEGER NOT NULL, final_counter INTEGER NOT NULL,
              new_no TEXT NOT NULL, new_start INTEGER NOT NULL,
              changed_at TEXT NOT NULL, actor TEXT NOT NULL, remark TEXT NOT NULL DEFAULT '',
              CHECK(final_counter>=old_start), CHECK(new_start>=0));
            CREATE TABLE IF NOT EXISTS replacement_shot_history (
              id INTEGER PRIMARY KEY, slot_id INTEGER NOT NULL REFERENCES replacement_slots(id),
              electrode_no TEXT NOT NULL, shot INTEGER NOT NULL CHECK(shot>=0),
              observed_at TEXT NOT NULL, actor TEXT NOT NULL);
            CREATE INDEX IF NOT EXISTS idx_replace_history_date ON replacement_history(changed_at);
            ''')
            if c.execute('SELECT COUNT(*) FROM replacement_slots').fetchone()[0]==0:
                c.executemany('INSERT INTO replacement_slots(machine,station,position,diameter) VALUES(?,?,?,?)',initial_slots())

    @contextmanager
    def tx(self,write=False):
        c=sqlite3.connect(self.path,timeout=15)
        c.row_factory=sqlite3.Row
        c.execute('PRAGMA foreign_keys=ON')
        c.execute('PRAGMA busy_timeout=15000')
        try:
            if write:c.execute('BEGIN IMMEDIATE')
            yield c
            c.commit()
        except Exception:
            c.rollback(); raise
        finally:c.close()

    def slots(self,include_disabled=True):
        with self.tx() as c:
            return [dict(r) for r in c.execute('SELECT * FROM replacement_slots '+('' if include_disabled else 'WHERE enabled=1 ')+ 'ORDER BY machine,station,diameter,position')]

    def add_slot(self,machine,station,position,diameter):
        vals=[str(v).strip() for v in (machine,station,position,diameter)]
        if not vals[0] or not vals[2] or not vals[3]:raise ReplacementError('กรุณาระบุ Machine, Position และ Diameter')
        if vals[0]=='Gas Filling' and vals[1] not in ('Station 1','Station 2','Station 3'):
            raise ReplacementError('Gas Filling ต้องเลือก Station 1, 2 หรือ 3')
        with self.tx(True) as c:
            try:c.execute('INSERT INTO replacement_slots(machine,station,position,diameter) VALUES(?,?,?,?)',vals)
            except sqlite3.IntegrityError as e: raise ReplacementError('มีตำแหน่งนี้อยู่แล้ว') from e

    def set_slot(self,slot_id,enabled,required):
        with self.tx(True) as c:
            if c.execute('UPDATE replacement_slots SET enabled=?,required=? WHERE id=?', (int(enabled),int(required),int(slot_id))).rowcount!=1:
                raise ReplacementError('ไม่พบรายการ Master')

    def current(self):
        with self.tx() as c:
            return [dict(r) for r in c.execute('''SELECT s.*,r.electrode_no,r.start_counter,r.installed_at,r.actor,
                (SELECT h.shot FROM replacement_shot_history h WHERE h.slot_id=s.id
                AND h.electrode_no=r.electrode_no ORDER BY h.id DESC LIMIT 1) AS current_shot
                FROM replacement_slots s LEFT JOIN replacement_current r ON r.slot_id=s.id
                ORDER BY s.machine,s.station,s.diameter,s.position''')]

    def first_install(self,slot_id,no,start,actor):
        no=no.strip(); actor=actor.strip()
        if not no or not actor or not str(start).isdigit():raise ReplacementError('ระบุ Electrode No., Start Counter และ Employee ID')
        at=datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.tx(True) as c:
            row=c.execute('SELECT enabled FROM replacement_slots WHERE id=?',(slot_id,)).fetchone()
            if not row or not row['enabled']:raise ReplacementError('ตำแหน่งถูกปิดใช้งาน')
            if c.execute('SELECT 1 FROM replacement_current WHERE slot_id=?',(slot_id,)).fetchone():raise ReplacementError('มีตัวเก่าแล้ว ต้องใช้ Replace')
            c.execute('INSERT INTO replacement_current VALUES(?,?,?,?,?)',(slot_id,no,int(start),at,actor))
            c.execute('INSERT INTO replacement_shot_history(slot_id,electrode_no,shot,observed_at,actor) VALUES(?,?,?,?,?)',(slot_id,no,int(start),at,actor))

    def replace(self,slot_id,expected_old,final_counter,new_no,new_start,actor,remark=''):
        new_no=new_no.strip();actor=actor.strip()
        if not new_no or not actor:raise ReplacementError('ระบุ Electrode No. ใหม่และ Employee ID')
        if not str(final_counter).isdigit() or not str(new_start).isdigit():raise ReplacementError('Counter ต้องเป็นจำนวนเต็มไม่ติดลบ')
        at=datetime.now(timezone.utc).isoformat(timespec='seconds')
        with self.tx(True) as c:
            slot=c.execute('SELECT enabled FROM replacement_slots WHERE id=?',(slot_id,)).fetchone()
            if not slot or not slot['enabled']:raise ReplacementError('ตำแหน่งถูกปิดใช้งาน')
            old=c.execute('SELECT * FROM replacement_current WHERE slot_id=?',(slot_id,)).fetchone()
            if not old:raise ReplacementError('ยังไม่มีตัวเก่า กรุณา Initial Install ก่อน')
            if old['electrode_no']!=expected_old:raise ReplacementError('ข้อมูลเปลี่ยนระหว่างเปิดหน้าจอ กรุณา Refresh')
            if new_no==expected_old:raise ReplacementError('หมายเลขใหม่ต้องต่างจากตัวเก่า')
            if int(final_counter)<old['start_counter']:raise ReplacementError('Final Counter ต่ำกว่า Start Counter ของตัวเก่า')
            c.execute('''INSERT INTO replacement_history(slot_id,old_no,old_start,final_counter,new_no,new_start,changed_at,actor,remark)
               VALUES(?,?,?,?,?,?,?,?,?)''',(slot_id,expected_old,old['start_counter'],int(final_counter),new_no,int(new_start),at,actor,remark.strip()))
            c.execute('''UPDATE replacement_current SET electrode_no=?,start_counter=?,installed_at=?,actor=? WHERE slot_id=?''',
                (new_no,int(new_start),at,actor,slot_id))
            c.execute('INSERT INTO replacement_shot_history(slot_id,electrode_no,shot,observed_at,actor) VALUES(?,?,?,?,?)',(slot_id,new_no,int(new_start),at,actor))

    def record_shot(self,slot_id,expected_no,shot,actor):
        if not str(shot).isdigit() or not str(actor).strip():
            raise ReplacementError('Shot must be nonnegative integer; employee is required')
        with self.tx(True) as c:
            old=c.execute('SELECT electrode_no,start_counter FROM replacement_current WHERE slot_id=?',(slot_id,)).fetchone()
            if old is None or old['electrode_no'] != expected_no:
                raise ReplacementError('Electrode changed; refresh required')
            last=c.execute('SELECT shot FROM replacement_shot_history WHERE slot_id=? AND electrode_no=? ORDER BY id DESC LIMIT 1',(slot_id,expected_no)).fetchone()
            if int(shot)<old['start_counter'] or (last is not None and int(shot)<last['shot']):
                raise ReplacementError('Shot cannot be lower than prior reading')
            at=datetime.now(timezone.utc).isoformat(timespec='seconds')
            c.execute('INSERT INTO replacement_shot_history(slot_id,electrode_no,shot,observed_at,actor) VALUES(?,?,?,?,?)',(slot_id,expected_no,int(shot),at,str(actor).strip()))

    def shot_history(self):
        with self.tx() as c:
            query="SELECT h.*,s.machine,s.station,s.position,s.diameter FROM replacement_shot_history h JOIN replacement_slots s ON s.id=h.slot_id ORDER BY h.id DESC"
            return [dict(r) for r in c.execute(query)]

    def history(self):
        with self.tx() as c:
            return [dict(r) for r in c.execute('''SELECT h.*,s.machine,s.station,s.position,s.diameter,
                h.final_counter-h.old_start AS usage_count FROM replacement_history h
                JOIN replacement_slots s ON s.id=h.slot_id ORDER BY h.id DESC''')]

    def export_csv(self,path,kind='history'):
        rows=self.history() if kind=='history' else self.current()
        columns=(['changed_at','machine','station','position','diameter','old_no','old_start','final_counter','usage_count','new_no','new_start','actor','remark']
            if kind=='history' else ['machine','station','position','diameter','electrode_no','start_counter','current_shot','installed_at','actor','enabled','required'])
        with open(path,'w',encoding='utf-8-sig',newline='') as f:
            w=csv.DictWriter(f,fieldnames=columns,extrasaction='ignore');w.writeheader();w.writerows(rows)
        return len(rows)

    def export_xlsx(self,path):
        from openpyxl import Workbook
        w=Workbook();w.remove(w.active)
        for title,rows,fields in [('Current',self.current(),['machine','station','position','diameter','electrode_no','start_counter','current_shot','installed_at','actor','enabled','required']),
            ('Shot History',self.shot_history(),['observed_at','machine','station','position','diameter','electrode_no','shot','actor']),
            ('History',self.history(),['changed_at','machine','station','position','diameter','old_no','old_start','final_counter','usage_count','new_no','new_start','actor','remark'])]:
            s=w.create_sheet(title);s.append(fields)
            for r in rows:s.append([r.get(field) for field in fields])
            s.freeze_panes='A2';s.auto_filter.ref=s.dimensions
        w.save(path)

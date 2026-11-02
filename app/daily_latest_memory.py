"""Small last-confirmed-result cache for Daily only (never Sample).

A cache value is a suggestion, not evidence of today's inspection.
"""
from __future__ import annotations
import json
import sqlite3
from pathlib import Path
from datetime import datetime, timezone


def memory_identity(document: dict) -> str:
    name = str(document.get('document_name') or '').strip()
    if not name: raise ValueError('Daily document name missing')
    # ALL_MODEL documents are deliberately shared across products; never share
    # ordinary documents with missing/unknown model.
    all_model = 'all model' in name.casefold() or 'all_model' in name.casefold()
    model = 'ALL_MODEL' if all_model else str(document.get('model') or '').strip().upper()
    if not model: raise ValueError('MODEL_UNKNOWN: cannot reuse saved results across models')
    return json.dumps([str(document.get('line') or '').strip().casefold(),
      str(document.get('document_no') or '').strip().casefold(), name.casefold(), model],
      ensure_ascii=False, separators=(',', ':'))

class DailyLatestMemory:
    def __init__(self, path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS daily_latest_results (
                identity TEXT NOT NULL, item TEXT NOT NULL, slot INTEGER NOT NULL,
                value TEXT NOT NULL, result_id TEXT NOT NULL, confirmed_at TEXT NOT NULL,
                PRIMARY KEY(identity,item,slot))''')
    def _db(self):
        db=sqlite3.connect(self.path,timeout=10)
        db.execute('PRAGMA busy_timeout=10000')
        return db
    def read(self,document):
        key=memory_identity(document)
        with self._db() as db:
            rows=db.execute('SELECT item,slot,value,result_id,confirmed_at FROM daily_latest_results WHERE identity=?',(key,)).fetchall()
        return {(str(i),int(n)):{'value':v,'result_id':r,'confirmed_at':t} for i,n,v,r,t in rows}
    def confirmed(self,document,item,slot,value,result_id):
        if not result_id:raise ValueError('Cannot cache unverified result')
        key=memory_identity(document)
        with self._db() as db:
            db.execute('''INSERT INTO daily_latest_results VALUES(?,?,?,?,?,?)
                ON CONFLICT(identity,item,slot) DO UPDATE SET
                value=excluded.value,result_id=excluded.result_id,confirmed_at=excluded.confirmed_at''',
                (key,str(item),int(slot),str(value),str(result_id),datetime.now(timezone.utc).isoformat()))
            db.commit()

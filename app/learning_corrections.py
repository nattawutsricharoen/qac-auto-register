"""Auditable, scoped correction suggestions. No silent changes to QAC data.

Suggestions require an explicit user confirmation before application; learning
never modifies a serial, numeric measurement, or judgment autonomously.
"""
from __future__ import annotations
import sqlite3
from pathlib import Path
from datetime import datetime, timezone

class CorrectionLearning:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._db() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS correction_learning (
                module TEXT NOT NULL, line TEXT NOT NULL, model TEXT NOT NULL,
                field TEXT NOT NULL, source_text TEXT NOT NULL, corrected_text TEXT NOT NULL,
                confirmations INTEGER NOT NULL DEFAULT 1, approved INTEGER NOT NULL DEFAULT 0,
                updated_at TEXT NOT NULL,
                PRIMARY KEY(module,line,model,field,source_text,corrected_text))''')
    def _db(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA busy_timeout=15000')
        return db
    @staticmethod
    def _scope(module, line, model, field):
        values = tuple(str(v or '').strip().casefold() for v in (module,line,model,field))
        if not all(values):
            raise ValueError('Learning needs module, line, model and field identity')
        return values
    def record_confirmation(self, module, line, model, field, original, correction):
        scope = self._scope(module,line,model,field)
        original, correction = str(original).strip(), str(correction).strip()
        if not original or not correction or original == correction:
            raise ValueError('Correction must be meaningful and nonempty')
        with self._db() as db:
            db.execute('''INSERT INTO correction_learning VALUES(?,?,?,?,?,?,1,0,?)
                ON CONFLICT(module,line,model,field,source_text,corrected_text)
                DO UPDATE SET confirmations=confirmations+1, updated_at=excluded.updated_at''',
                (*scope, original, correction, datetime.now(timezone.utc).isoformat()))
            db.commit()
    def suggestions(self, module, line, model, field, original):
        scope = self._scope(module,line,model,field)
        with self._db() as db:
            rows = db.execute('''SELECT corrected_text,confirmations,approved FROM correction_learning
                WHERE module=? AND line=? AND model=? AND field=? AND source_text=?
                ORDER BY approved DESC, confirmations DESC, corrected_text''', (*scope,str(original).strip())).fetchall()
        return [{'value':r[0], 'confirmations':r[1], 'approved':bool(r[2])} for r in rows]
    def set_approved(self, module, line, model, field, original, correction, approved):
        scope=self._scope(module,line,model,field)
        with self._db() as db:
            cur=db.execute('''UPDATE correction_learning SET approved=?,updated_at=?
                WHERE module=? AND line=? AND model=? AND field=? AND source_text=? AND corrected_text=?''',
                (int(bool(approved)),datetime.now(timezone.utc).isoformat(),*scope,str(original).strip(),str(correction).strip()))
            if not cur.rowcount: raise KeyError('Correction not found')
            db.commit()

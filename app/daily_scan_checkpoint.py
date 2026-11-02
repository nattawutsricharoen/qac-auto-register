"""Durable, independent QAC read checkpoints (never authority to register).

A checkpoint records observations already checked against a live Measure page.
It must NEVER replace a fresh target preflight before any write.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from .daily_latest_memory import memory_identity


class DailyScanCheckpoint:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS daily_scan_checkpoints (
                scope TEXT NOT NULL CHECK(scope IN ('TARGET','REFERENCE')),
                identity TEXT NOT NULL, production_date TEXT NOT NULL,
                task_id TEXT NOT NULL, payload TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                PRIMARY KEY (scope,identity,production_date,task_id))''')

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA busy_timeout=15000')
        return db

    @staticmethod
    def _key(scope, document, production_date, task_id):
        scope = str(scope).upper()
        if scope not in ('TARGET', 'REFERENCE'):
            raise ValueError('Checkpoint scope must be TARGET or REFERENCE')
        date = str(production_date).strip()
        datetime.strptime(date, '%Y-%m-%d')
        task = str(task_id).strip()
        if not task:
            raise ValueError('Checkpoint task ID is required')
        return (scope, memory_identity(document), date, task)

    def save(self, scope, document, production_date, task_id, items):
        key = self._key(scope, document, production_date, task_id)
        if not isinstance(items, list) or not items:
            raise ValueError('Checkpoint needs actual verified items')
        # Input MUST be from live identity-verified Measure DOM, not from templates.
        payload = json.dumps(items, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        with self._connect() as db:
            db.execute('''INSERT INTO daily_scan_checkpoints VALUES(?,?,?,?,?,?)
                ON CONFLICT(scope,identity,production_date,task_id) DO UPDATE SET
                payload=excluded.payload,updated_at=excluded.updated_at''',
                (*key, payload, datetime.now(timezone.utc).isoformat()))
            db.commit()

    def load(self, scope, document, production_date, task_id):
        key = self._key(scope, document, production_date, task_id)
        with self._connect() as db:
            record = db.execute('''SELECT payload,updated_at FROM daily_scan_checkpoints
                WHERE scope=? AND identity=? AND production_date=? AND task_id=?''', key).fetchone()
        return {'items': json.loads(record[0]), 'updated_at': record[1]} if record else None


def verified_reference_values(items):
    """Return only persisted, nonempty QAC evidence from verified Measure items.

    The source checkpoint identity must already match exact task/date/line/model.
    UNKNOWN and EMPTY observations never become values.
    """
    found = {}
    if not isinstance(items, list):
        raise ValueError('Invalid checkpoint items')
    for field in items:
        item = str(field.get('item') or '').strip()
        fmt = str(field.get('format') or '')
        if not item:
            raise ValueError('Checkpoint item missing')
        for slot in field.get('slots', []):
            if slot.get('status') != 'SAVED' or not slot.get('saved', False):
                continue
            number = int(slot['number'])
            value = str(slot.get('value') or '').strip()
            if not value or number < 1:
                continue
            if fmt == '1':
                from decimal import Decimal, InvalidOperation
                try:
                    parsed = Decimal(value)
                except InvalidOperation:
                    continue
                if not parsed.is_finite():
                    continue
            elif fmt == '4' and value.upper() not in ('OK', 'NG'):
                continue
            elif fmt == '3' and value.upper() not in ('INITIAL', 'MIDDLE', 'FINAL'):
                continue
            elif fmt not in ('1', '3', '4'):
                continue
            key = (item, number)
            if key in found:
                raise ValueError(f'Duplicate slot in checkpoint: {key}')
            found[key] = {'item': item, 'number': number, 'value': value,
                          'result_id': str(slot.get('result_id') or ''), 'readable': True}
    return found

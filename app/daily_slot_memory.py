"""Per-document operator choice presets (not proof of actual QAC results)."""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
def document_key(document: dict) -> str:
    fields = ('document_no', 'line', 'model', 'period', 'document_name')
    values = {k: str(document.get(k) or '').strip().casefold() for k in fields}
    if not values['document_name']:
        raise ValueError('Document name required for Daily slot memory')
    return json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


class DailySlotMemory:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._open() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS daily_slot_presets (
                document_key TEXT PRIMARY KEY, choices TEXT NOT NULL, updated_at TEXT NOT NULL
            )''')

    def _open(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.execute('PRAGMA busy_timeout=15000')
        return db

    def load(self, document: dict) -> dict:
        with self._open() as db:
            row = db.execute('SELECT choices FROM daily_slot_presets WHERE document_key=?',
                             (document_key(document),)).fetchone()
        return json.loads(row[0]) if row else {}

    def save(self, document: dict, choices: dict) -> None:
        sanitized = {
            str(item): {str(slot):str(choice) for slot, choice in slots.items()
                        if str(choice) in ('Initial','Middle','Final','OK','NG')
                        or (str(choice).startswith('VALUE:') and str(choice)[6:].strip())}
            for item, slots in choices.items()
            if isinstance(slots, dict)
        }
        sanitized = {key:value for key,value in sanitized.items() if value}
        with self._open() as db:
            db.execute('''INSERT INTO daily_slot_presets(document_key,choices,updated_at)
                VALUES(?,?,?) ON CONFLICT(document_key) DO UPDATE SET
                choices=excluded.choices, updated_at=excluded.updated_at''',
                (document_key(document),json.dumps(sanitized,ensure_ascii=False),
                 datetime.now(timezone.utc).isoformat()))
            db.commit()

    def reset(self, document: dict):
        with self._open() as db:
            db.execute('DELETE FROM daily_slot_presets WHERE document_key=?',
                       (document_key(document),))
            db.commit()

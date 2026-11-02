"""Audit snapshots for QAC read-only reference pages.

Store the full rendered HTML before closing the page. A snapshot is evidence
of what was presented, NOT permission to copy values into another task.
"""
from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

class DailyReferenceSnapshot:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as db:
            db.execute('''CREATE TABLE IF NOT EXISTS daily_reference_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                captured_at TEXT NOT NULL,
                target_task TEXT NOT NULL,
                reference_task TEXT NOT NULL,
                requested_date TEXT NOT NULL,
                document_name TEXT NOT NULL,
                expected_document_no TEXT NOT NULL,
                identity_verified INTEGER NOT NULL,
                page_url TEXT NOT NULL,
                rendered_html TEXT NOT NULL,
                visible_values_json TEXT NOT NULL,
                results_json TEXT NOT NULL
            )''')
    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10)
        db.execute('PRAGMA busy_timeout=10000')
        return db
    def save(self, *, target_task, reference_task, requested_date, document_name,
             expected_document_no, identity_verified, page_url, rendered_html,
             visible_values, results):
        if not rendered_html:
            raise ValueError('Reference HTML empty; snapshot not saved')
        with self._connect() as db:
            cur = db.execute('''INSERT INTO daily_reference_snapshots
              (captured_at,target_task,reference_task,requested_date,document_name,
               expected_document_no,identity_verified,page_url,rendered_html,
               visible_values_json,results_json) VALUES (?,?,?,?,?,?,?,?,?,?,?)''', (
              datetime.now(timezone.utc).isoformat(),str(target_task),str(reference_task),
              str(requested_date),str(document_name),str(expected_document_no),
              int(bool(identity_verified)),str(page_url),str(rendered_html),
              json.dumps(visible_values,ensure_ascii=False),json.dumps(results,ensure_ascii=False)))
            db.commit()
            return cur.lastrowid

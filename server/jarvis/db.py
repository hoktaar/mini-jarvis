"""SQLite-Speicher für Geräte, Timer, Router- und Audit-Log."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    kind TEXT NOT NULL,
    room TEXT DEFAULT '',
    token_hash TEXT NOT NULL UNIQUE,
    created REAL NOT NULL,
    revoked INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS timers (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,          -- timer | alarm | reminder
    label TEXT DEFAULT '',
    due REAL NOT NULL,
    device_id INTEGER,
    fired INTEGER DEFAULT 0,
    created REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS router_log (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    text TEXT NOT NULL,
    intent TEXT,
    confidence REAL,
    route TEXT,
    corrected_intent TEXT
);
CREATE TABLE IF NOT EXISTS audit_log (
    id INTEGER PRIMARY KEY,
    ts REAL NOT NULL,
    actor TEXT,
    action TEXT NOT NULL,
    detail TEXT,
    result TEXT
);
"""


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            self._conn.executescript(SCHEMA)
            self._conn.commit()

    def execute(self, sql: str, params: tuple = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._conn.execute(sql, params)
            self._conn.commit()
            return cur

    def query(self, sql: str, params: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            return list(self._conn.execute(sql, params).fetchall())

    def audit(self, actor: str, action: str, detail: str = "", result: str = "") -> None:
        self.execute(
            "INSERT INTO audit_log (ts, actor, action, detail, result) VALUES (?,?,?,?,?)",
            (time.time(), actor, action, detail, result),
        )

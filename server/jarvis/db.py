"""SQLite-Speicher für Geräte, Timer, Logs, Gedächtnis und Verbrauch – mit Migrationen."""

from __future__ import annotations

import sqlite3
import threading
import time
from pathlib import Path

# Jede Migration läuft genau einmal (PRAGMA user_version). Nur anhängen, nie ändern.
MIGRATIONS = [
    # 1 – Grundschema (0.1/0.2)
    """
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
        fired INTEGER DEFAULT 0,     -- 0 offen, 1 ausgelöst, 2 gelöscht
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
    """,
    # 2 – 0.3: Gerätestatus, Alarm-Quittung, Gedächtnis, Verbrauch, Korrekturen, Chat-Konten
    """
    ALTER TABLE devices ADD COLUMN last_seen REAL;
    ALTER TABLE devices ADD COLUMN settings TEXT DEFAULT '{}';
    ALTER TABLE devices ADD COLUMN fw TEXT DEFAULT '';
    ALTER TABLE timers ADD COLUMN acked INTEGER DEFAULT 0;
    ALTER TABLE router_log ADD COLUMN device_id INTEGER;
    ALTER TABLE router_log ADD COLUMN latency_ms REAL;
    CREATE INDEX IF NOT EXISTS idx_timers_open ON timers (fired, due);
    CREATE INDEX IF NOT EXISTS idx_router_ts ON router_log (ts);
    CREATE INDEX IF NOT EXISTS idx_audit_ts ON audit_log (ts);
    CREATE TABLE IF NOT EXISTS memories (
        id INTEGER PRIMARY KEY,
        device_id INTEGER,
        text TEXT NOT NULL,
        created REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS usage (
        id INTEGER PRIMARY KEY,
        ts REAL NOT NULL,
        provider TEXT NOT NULL,
        model TEXT,
        prompt_tokens INTEGER DEFAULT 0,
        completion_tokens INTEGER DEFAULT 0,
        cost_eur REAL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS intent_examples (
        id INTEGER PRIMARY KEY,
        intent TEXT NOT NULL,
        text TEXT NOT NULL,
        created REAL NOT NULL,
        UNIQUE (intent, text)
    );
    CREATE TABLE IF NOT EXISTS adapter_users (
        adapter TEXT NOT NULL,
        user_id TEXT NOT NULL,
        device_id INTEGER NOT NULL,
        PRIMARY KEY (adapter, user_id)
    );
    """,
]


class Database:
    def __init__(self, path: Path | str):
        if str(path) != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._lock = threading.Lock()
        with self._lock:
            if str(path) != ":memory:":
                self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._migrate()

    def _migrate(self) -> None:
        version = self._conn.execute("PRAGMA user_version").fetchone()[0]
        for i, script in enumerate(MIGRATIONS[version:], start=version + 1):
            for stmt in (s.strip() for s in script.split(";")):
                if not stmt:
                    continue
                try:
                    self._conn.execute(stmt)
                except sqlite3.OperationalError as e:
                    # Spalte existiert schon (z. B. halb migrierte Entwicklungs-DB) → weiter.
                    if "duplicate column" not in str(e):
                        raise
            self._conn.execute(f"PRAGMA user_version = {i}")
            self._conn.commit()

    @property
    def version(self) -> int:
        with self._lock:
            return self._conn.execute("PRAGMA user_version").fetchone()[0]

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

    def purge(self, retention_days: int) -> int:
        """Alte Router- und Aktionsprotokolle löschen (Datenschutz)."""
        if retention_days <= 0:
            return 0
        cutoff = time.time() - retention_days * 86400
        n = self.execute("DELETE FROM router_log WHERE ts < ?", (cutoff,)).rowcount
        n += self.execute("DELETE FROM audit_log WHERE ts < ?", (cutoff,)).rowcount
        n += self.execute("DELETE FROM timers WHERE fired != 0 AND due < ?", (cutoff,)).rowcount
        return n

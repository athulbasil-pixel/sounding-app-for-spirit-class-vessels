"""SQLite access. One connection per request; WAL mode for crash safety."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from flask import current_app, g

SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS officer (
    id INTEGER PRIMARY KEY,
    display_name TEXT NOT NULL,
    rank TEXT,
    active INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS watch_log (
    id INTEGER PRIMARY KEY,
    ship_date TEXT NOT NULL,                 -- ISO date chosen by the crew
    watch TEXT NOT NULL CHECK (watch IN ('w1','w2','w3','w4')),
    status TEXT NOT NULL DEFAULT 'draft' CHECK (status IN ('draft','closed')),
    version INTEGER NOT NULL DEFAULT 1,
    supersedes_id INTEGER REFERENCES watch_log(id),
    correction_reason TEXT,
    remarks TEXT,
    officer_id INTEGER REFERENCES officer(id),
    missing_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    saved_at TEXT,
    closed_at TEXT,
    UNIQUE (ship_date, watch, version)
);

CREATE TABLE IF NOT EXISTS reading (
    id INTEGER PRIMARY KEY,
    log_id INTEGER NOT NULL REFERENCES watch_log(id) ON DELETE CASCADE,
    field_id TEXT NOT NULL,
    slot TEXT NOT NULL DEFAULT 'watch',      -- 'watch' or FW slot s1,s2,s4,s5
    value_num REAL,                          -- NULL = missing
    qualifier TEXT,                          -- '+', '-', '~'
    raw_text TEXT,
    status TEXT NOT NULL CHECK (status IN ('entered','missing','unavailable')),
    unavailable_reason TEXT,
    entered_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    UNIQUE (log_id, field_id, slot)
);
CREATE INDEX IF NOT EXISTS ix_reading_field ON reading(field_id, slot);

-- opening balances are per field+series; rollover / meter swap are per point
CREATE TABLE IF NOT EXISTS counter_event (
    id INTEGER PRIMARY KEY,
    field_id TEXT NOT NULL,
    series TEXT NOT NULL CHECK (series IN ('6h','4h')),
    ship_date TEXT,
    point TEXT,                              -- watch id (6h) or slot id (4h)
    kind TEXT NOT NULL CHECK (kind IN ('opening_balance','rollover','meter_replaced')),
    value REAL,
    reason TEXT,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_opening ON counter_event(field_id, series) WHERE kind = 'opening_balance';
CREATE UNIQUE INDEX IF NOT EXISTS ux_point_event ON counter_event(field_id, series, ship_date, point) WHERE kind <> 'opening_balance';

-- per-field settings that change over time (not in use) keep an effective date
CREATE TABLE IF NOT EXISTS field_state (
    id INTEGER PRIMARY KEY,
    field_id TEXT NOT NULL,
    effective_from TEXT NOT NULL,            -- ship date from which this applies
    not_in_use INTEGER NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime')),
    UNIQUE (field_id, effective_from)
);

CREATE TABLE IF NOT EXISTS field_setting (
    field_id TEXT PRIMARY KEY,
    rollover_limit REAL
);

CREATE TABLE IF NOT EXISTS pdf_file (
    id INTEGER PRIMARY KEY,
    log_id INTEGER NOT NULL REFERENCES watch_log(id),
    filename TEXT NOT NULL,
    rel_path TEXT NOT NULL,                  -- relative to the data folder
    sha256 TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%S','now','localtime'))
);
"""

# columns added after schema v1 (ALTER TABLE ... ADD COLUMN when missing)
MIGRATIONS = {
    "watch_log": {
        "officer_name": "TEXT",              # name snapshot at closure (record must not change if officer renamed)
        "closed_recorded_at": "TEXT",        # PC time the close button was pressed
        "correction_created_at": "TEXT",
        "snapshot_json": "TEXT",             # full computed record frozen at closure
    },
}

DEFAULT_ROLLOVER = 1_000_000


def connect(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path), detect_types=0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = FULL")
    return conn


def init_db(path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = connect(path)
    try:
        conn.executescript(SCHEMA)
        for table, cols in MIGRATIONS.items():
            have = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
            for col, decl in cols.items():
                if col not in have:
                    conn.execute(f"ALTER TABLE {table} ADD COLUMN {col} {decl}")
        conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '2')")
        conn.execute("UPDATE meta SET value='2' WHERE key='schema_version'")
    finally:
        conn.close()


def get_db() -> sqlite3.Connection:
    if "db" not in g:
        g.db = connect(current_app.config["DATABASE"])
    return g.db


def close_db(_exc=None) -> None:
    db = g.pop("db", None)
    if db is not None:
        db.close()

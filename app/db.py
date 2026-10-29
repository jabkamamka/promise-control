"""Работа с SQLite: подключение, схема, инициализация."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from .config import settings
from .services.taxonomy import BUILTIN_TYPES
from .utils import utc_now

SCHEMA_VERSION = 1

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id             TEXT PRIMARY KEY,
    operator_id    INTEGER,
    client_phone   TEXT,
    started_at     TEXT,
    ended_at       TEXT,
    transcript     TEXT NOT NULL,
    received_at    TEXT NOT NULL,
    processed_at   TEXT,
    promise_count  INTEGER NOT NULL DEFAULT 0,
    status         TEXT NOT NULL DEFAULT 'processed',
    raw            TEXT
);
CREATE INDEX IF NOT EXISTS idx_calls_operator ON calls(operator_id);
CREATE INDEX IF NOT EXISTS idx_calls_started  ON calls(started_at);

CREATE TABLE IF NOT EXISTS promise_types (
    code        TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    keywords    TEXT NOT NULL DEFAULT '[]',
    examples    TEXT NOT NULL DEFAULT '[]',
    is_builtin  INTEGER NOT NULL DEFAULT 0,
    priority    INTEGER NOT NULL DEFAULT 78,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tasks (
    id               TEXT PRIMARY KEY,
    call_id          TEXT NOT NULL REFERENCES calls(id) ON DELETE CASCADE,
    operator_id      INTEGER,
    promise_type     TEXT NOT NULL REFERENCES promise_types(code),
    title            TEXT NOT NULL,
    object           TEXT NOT NULL DEFAULT '',
    quote            TEXT NOT NULL,
    transcript_index INTEGER NOT NULL DEFAULT 0,
    actions          TEXT NOT NULL DEFAULT '[]',
    secondary_types  TEXT NOT NULL DEFAULT '[]',
    search_text      TEXT NOT NULL DEFAULT '',
    due_at           TEXT NOT NULL,
    due_hint         TEXT NOT NULL DEFAULT '',
    deadline_source  TEXT NOT NULL DEFAULT 'default_24h',
    status           TEXT NOT NULL DEFAULT 'created',
    confidence       REAL NOT NULL DEFAULT 0.5,
    matched_by       TEXT NOT NULL DEFAULT 'rule',
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    closed_at        TEXT,
    overdue_marked_at TEXT,
    dedupe_key       TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_tasks_call     ON tasks(call_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due      ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_operator ON tasks(operator_id);
CREATE INDEX IF NOT EXISTS idx_tasks_type     ON tasks(promise_type);
CREATE TABLE IF NOT EXISTS task_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    event       TEXT NOT NULL,
    from_status TEXT,
    to_status   TEXT,
    comment     TEXT,
    at          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id);
"""


def _db_path() -> str:
    return settings.database_path


def connect() -> sqlite3.Connection:
    path = _db_path()
    if path != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    if path != ":memory:":
        conn.execute("PRAGMA journal_mode = WAL")
    return conn


def init_db() -> None:
    """Создаёт схему и наполняет справочник типов обещаний."""
    with connect() as conn:
        conn.executescript(SCHEMA)
        conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
        now = utc_now()
        for t in BUILTIN_TYPES:
            conn.execute(
                """INSERT INTO promise_types
                   (code, title, description, keywords, examples, is_builtin, priority, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)
                   ON CONFLICT(code) DO NOTHING""",
                (
                    t["code"],
                    t["title"],
                    t["description"],
                    t["keywords_json"],
                    t["examples_json"],
                    t["priority"],
                    now,
                    now,
                ),
            )
        conn.commit()


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI-зависимость: соединение на запрос."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()

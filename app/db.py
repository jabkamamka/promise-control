"""Слой хранения: SQLite без ORM.

Схема специально простая: звонки, задачи, журнал смены статусов и справочник
типов обещаний. Индексы и UNIQUE-ограничения закрывают два требования кейса:
защиту от дублей при повторной обработке звонка и быстрые фильтры по задачам.
"""

from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Iterator

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS calls (
    id            TEXT PRIMARY KEY,
    operator_id   TEXT,
    phone         TEXT,
    started_at    TEXT,
    ended_at      TEXT,
    segments_json TEXT NOT NULL,
    payload_json  TEXT,
    received_at   TEXT NOT NULL,
    tasks_count   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id     TEXT NOT NULL,
    operator_id TEXT,
    phone       TEXT,
    type_code   TEXT NOT NULL,
    title       TEXT NOT NULL,
    quote       TEXT NOT NULL,
    comment     TEXT,
    confidence  REAL NOT NULL DEFAULT 0.5,
    due_at      TEXT NOT NULL,
    due_source  TEXT NOT NULL,
    due_phrase  TEXT,
    status      TEXT NOT NULL DEFAULT 'created',
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    closed_at   TEXT,
    dedupe_key  TEXT NOT NULL,
    UNIQUE (call_id, dedupe_key)
);

CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks (status);
CREATE INDEX IF NOT EXISTS idx_tasks_operator ON tasks (operator_id);
CREATE INDEX IF NOT EXISTS idx_tasks_due      ON tasks (due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_call     ON tasks (call_id);

CREATE TABLE IF NOT EXISTS task_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id     INTEGER NOT NULL,
    from_status TEXT,
    to_status   TEXT NOT NULL,
    note        TEXT,
    at          TEXT NOT NULL,
    FOREIGN KEY (task_id) REFERENCES tasks (id)
);

CREATE INDEX IF NOT EXISTS idx_events_task ON task_events (task_id);

CREATE TABLE IF NOT EXISTS promise_types (
    code        TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL,
    examples    TEXT NOT NULL DEFAULT '[]',
    keywords    TEXT NOT NULL DEFAULT '[]',
    patterns    TEXT NOT NULL DEFAULT '[]',
    action      TEXT NOT NULL DEFAULT '',
    is_builtin  INTEGER NOT NULL DEFAULT 0,
    active      INTEGER NOT NULL DEFAULT 1,
    created_at  TEXT NOT NULL
);
"""


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    """Единый формат хранения: UTC, ISO-8601 с суффиксом Z."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


@contextmanager
def connect() -> Iterator[sqlite3.Connection]:
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with connect() as conn:
        conn.executescript(SCHEMA)


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [dict(r) for r in rows]


def loads(value: str | None, default: Any) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return default

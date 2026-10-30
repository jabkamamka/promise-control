"""Работа с SQLite: подключение, схема, инициализация."""
from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Iterator

from .config import settings
from .services.taxonomy import BUILTIN_TYPES
from .utils import utc_now

SCHEMA_VERSION = 4

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
    verification_status TEXT,
    verified_at      TEXT,
    verified_call_id TEXT,
    verification_quote TEXT,
    dedupe_key       TEXT NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS idx_tasks_call     ON tasks(call_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status   ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_due      ON tasks(due_at);
CREATE INDEX IF NOT EXISTS idx_tasks_operator ON tasks(operator_id);
CREATE INDEX IF NOT EXISTS idx_tasks_type     ON tasks(promise_type);
CREATE INDEX IF NOT EXISTS idx_tasks_verification ON tasks(verification_status);
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

CREATE TABLE IF NOT EXISTS employees (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    email            TEXT NOT NULL UNIQUE,
    password_hash    TEXT NOT NULL,
    full_name        TEXT NOT NULL DEFAULT '',
    role             TEXT NOT NULL DEFAULT 'operator',
    is_active        INTEGER NOT NULL DEFAULT 1,
    email_confirmed_at TEXT,
    created_at       TEXT NOT NULL,
    last_login_at    TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT PRIMARY KEY,
    employee_id INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_sessions_employee ON sessions(employee_id);

CREATE TABLE IF NOT EXISTS notifications (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id   INTEGER NOT NULL REFERENCES employees(id) ON DELETE CASCADE,
    task_id       TEXT REFERENCES tasks(id) ON DELETE CASCADE,
    kind          TEXT NOT NULL,
    title         TEXT NOT NULL,
    body          TEXT NOT NULL DEFAULT '',
    link          TEXT NOT NULL DEFAULT '/',
    read_at       TEXT,
    email_status  TEXT,
    email_error   TEXT,
    email_sent_at TEXT,
    created_at    TEXT NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_notifications_once
    ON notifications(employee_id, kind, IFNULL(task_id, ''));
CREATE INDEX IF NOT EXISTS idx_notifications_employee
    ON notifications(employee_id, created_at DESC);

CREATE TABLE IF NOT EXISTS login_tokens (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    email      TEXT NOT NULL,
    token_hash TEXT NOT NULL UNIQUE,
    code       TEXT NOT NULL,
    purpose    TEXT NOT NULL DEFAULT 'login',
    expires_at TEXT NOT NULL,
    used_at    TEXT,
    attempts   INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_login_tokens_email ON login_tokens(email, created_at);
"""


def _db_path() -> str:
    return settings.database_path


_VERIFICATION_COLUMNS = (
    "verification_status TEXT",
    "verified_at TEXT",
    "verified_call_id TEXT",
    "verification_quote TEXT",
    "assignee_id INTEGER",
    "assignee_name TEXT",
    "taken_at TEXT",
    "reminder_sent_at TEXT",
)


def _migrate(conn: sqlite3.Connection) -> None:
    """Доводит существующую БД до текущей версии схемы."""
    _migrate_tasks(conn)
    _migrate_employees(conn)
    _ensure_employee_columns(conn)
    conn.executescript("DROP TABLE IF EXISTS auth_codes;")
    conn.commit()


def _ensure_employee_columns(conn: sqlite3.Connection) -> None:
    """Добавляет новые поля сотрудников. Старым аккаунтам почту считаем подтверждённой."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(employees)")}
    if not columns:
        return
    if "email_confirmed_at" not in columns:
        conn.execute("ALTER TABLE employees ADD COLUMN email_confirmed_at TEXT")
        conn.execute("UPDATE employees SET email_confirmed_at = created_at WHERE email_confirmed_at IS NULL")
        conn.commit()

    token_columns = {row["name"] for row in conn.execute("PRAGMA table_info(login_tokens)")}
    if token_columns and "purpose" not in token_columns:
        conn.execute("ALTER TABLE login_tokens ADD COLUMN purpose TEXT NOT NULL DEFAULT 'login'")
        conn.commit()


def _migrate_tasks(conn: sqlite3.Connection) -> None:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    if not columns:
        return
    for definition in _VERIFICATION_COLUMNS:
        name = definition.split()[0]
        if name not in columns:
            conn.execute(f"ALTER TABLE tasks ADD COLUMN {definition}")
    conn.commit()


def _migrate_employees(conn: sqlite3.Connection) -> None:
    """Убирает из сотрудников поля Telegram: вход теперь только по почте."""
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(employees)")}
    if not columns or "telegram_id" not in columns:
        return

    conn.commit()
    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        conn.executescript(
            """
            CREATE TABLE employees_new (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                full_name     TEXT NOT NULL DEFAULT '',
                role          TEXT NOT NULL DEFAULT 'operator',
                is_active     INTEGER NOT NULL DEFAULT 1,
                created_at    TEXT NOT NULL,
                last_login_at TEXT
            );
            INSERT INTO employees_new
                (id, email, password_hash, full_name, role, is_active, created_at, last_login_at)
            SELECT id, email, password_hash, full_name, role, is_active, created_at, last_login_at
            FROM employees;
            DROP TABLE employees;
            ALTER TABLE employees_new RENAME TO employees;
            """
        )
        conn.commit()
    finally:
        conn.execute("PRAGMA foreign_keys = ON")


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
        _migrate(conn)
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

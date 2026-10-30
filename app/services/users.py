"""Пользователи, сессии и вход: почта (magic link) и Telegram-бот.

Внешних зависимостей нет: SQLite + stdlib. Почта уходит через SMTP, если он
настроен; иначе сервис работает в dev-режиме и возвращает ссылку в ответе —
это честно помечено в ответе API (`delivery: "dev"`).

Сессия — случайный токен в HttpOnly cookie, в базе хранится только он.
"""

from __future__ import annotations

import hashlib
import os
import secrets
import smtplib
import sqlite3
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from ..utils import utc_now  # noqa: F401  (оставлено для совместимости импортов)

SESSION_COOKIE = "promise_session"
SESSION_DAYS = 30
CODE_MINUTES = 10

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    email         TEXT UNIQUE,
    telegram_id   INTEGER UNIQUE,
    plan          TEXT NOT NULL DEFAULT 'free',
    operator_id   INTEGER,
    created_at    TEXT NOT NULL,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS sessions (
    token      TEXT PRIMARY KEY,
    user_id    TEXT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS login_codes (
    code        TEXT PRIMARY KEY,
    kind        TEXT NOT NULL,
    email       TEXT,
    telegram_id INTEGER,
    user_id     TEXT,
    created_at  TEXT NOT NULL,
    expires_at  TEXT NOT NULL,
    used_at     TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_user ON sessions(user_id);
"""


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _now() -> datetime:
    """Текущее время в UTC. Своё, потому что app.utils.utc_now возвращает строку."""
    return datetime.now(timezone.utc)


def normalize_email(email: str) -> str:
    value = (email or "").strip().lower()
    if "@" not in value or len(value) < 5 or value.startswith("@") or value.endswith("@"):
        raise ValueError("Некорректный адрес почты")
    return value


def _get_or_create(conn: sqlite3.Connection, *, email: str | None = None,
                   telegram_id: int | None = None) -> sqlite3.Row:
    if email:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
        if row:
            return row
    if telegram_id is not None:
        row = conn.execute("SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)).fetchone()
        if row:
            return row

    user_id = secrets.token_hex(8)
    conn.execute(
        "INSERT INTO users (id, email, telegram_id, plan, created_at, last_login_at) VALUES (?, ?, ?, 'free', ?, ?)",
        (user_id, email, telegram_id, _iso(_now()), _iso(_now())),
    )
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def create_session(conn: sqlite3.Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = _now() + timedelta(days=SESSION_DAYS)
    conn.execute(
        "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
        (token, user_id, _iso(_now()), _iso(expires)),
    )
    conn.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (_iso(_now()), user_id))
    return token


def user_by_session(conn: sqlite3.Connection, token: str | None) -> sqlite3.Row | None:
    if not token:
        return None
    row = conn.execute(
        "SELECT u.* FROM sessions s JOIN users u ON u.id = s.user_id "
        "WHERE s.token = ? AND s.expires_at > ?",
        (token, _iso(_now())),
    ).fetchone()
    return row


def drop_session(conn: sqlite3.Connection, token: str) -> None:
    conn.execute("DELETE FROM sessions WHERE token = ?", (token,))


def user_public(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "email": row["email"],
        "telegram_id": row["telegram_id"],
        "plan": row["plan"],
        "ads": row["plan"] == "free",
        "operator_id": row["operator_id"],
        "created_at": row["created_at"],
    }


# ------------------------------------------------------------------ вход по почте


def _smtp_config() -> dict | None:
    host = os.environ.get("SMTP_HOST")
    if not host:
        return None
    return {
        "host": host,
        "port": int(os.environ.get("SMTP_PORT", "587")),
        "user": os.environ.get("SMTP_USER", ""),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "sender": os.environ.get("SMTP_FROM", os.environ.get("SMTP_USER", "no-reply@localhost")),
        "tls": os.environ.get("SMTP_TLS", "1") not in {"0", "false", "False"},
    }


def _send_email(to: str, link: str) -> bool:
    cfg = _smtp_config()
    if not cfg:
        return False
    message = EmailMessage()
    message["Subject"] = "Вход в сервис контроля обещаний"
    message["From"] = cfg["sender"]
    message["To"] = to
    message.set_content(
        "Здравствуйте!\n\n"
        f"Ссылка для входа (действует {CODE_MINUTES} минут):\n{link}\n\n"
        "Если вы не запрашивали вход, просто проигнорируйте письмо."
    )
    try:
        with smtplib.SMTP(cfg["host"], cfg["port"], timeout=15) as smtp:
            if cfg["tls"]:
                smtp.starttls()
            if cfg["user"]:
                smtp.login(cfg["user"], cfg["password"])
            smtp.send_message(message)
        return True
    except Exception:  # noqa: BLE001 - почта не должна ронять запрос входа
        return False


def issue_email_code(conn: sqlite3.Connection, email: str, base_url: str) -> dict:
    email = normalize_email(email)
    user = _get_or_create(conn, email=email)
    code = secrets.token_urlsafe(32)
    conn.execute(
        "INSERT INTO login_codes (code, kind, email, user_id, created_at, expires_at) VALUES (?, 'email', ?, ?, ?, ?)",
        (code, email, user["id"], _iso(_now()), _iso(_now() + timedelta(minutes=CODE_MINUTES))),
    )
    link = f"{base_url.rstrip('/')}/api/v1/auth/email/confirm?token={code}"
    delivered = _send_email(email, link)
    return {
        "status": "sent",
        "delivery": "smtp" if delivered else "dev",
        "email": email,
        # В dev-режиме ссылка возвращается, чтобы вход можно было проверить без почты.
        "dev_link": None if delivered else link,
    }


def confirm_email_code(conn: sqlite3.Connection, code: str) -> str | None:
    row = conn.execute(
        "SELECT * FROM login_codes WHERE code = ? AND kind = 'email' AND used_at IS NULL", (code,)
    ).fetchone()
    if not row or row["expires_at"] <= _iso(_now()):
        return None
    conn.execute("UPDATE login_codes SET used_at = ? WHERE code = ?", (_iso(_now()), code))
    user = conn.execute("SELECT * FROM users WHERE id = ?", (row["user_id"],)).fetchone()
    if not user:
        return None
    return create_session(conn, user["id"])


# -------------------------------------------------------------------- Telegram


def issue_telegram_code(conn: sqlite3.Connection, telegram_id: int) -> str:
    user = _get_or_create(conn, telegram_id=int(telegram_id))
    code = f"{secrets.randbelow(900000) + 100000}"
    conn.execute(
        "INSERT INTO login_codes (code, kind, telegram_id, user_id, created_at, expires_at) VALUES (?, 'telegram', ?, ?, ?, ?)",
        (code, int(telegram_id), user["id"], _iso(_now()), _iso(_now() + timedelta(minutes=CODE_MINUTES))),
    )
    return code


def confirm_telegram_code(conn: sqlite3.Connection, code: str) -> str | None:
    code = (code or "").strip()
    row = conn.execute(
        "SELECT * FROM login_codes WHERE code = ? AND kind = 'telegram' AND used_at IS NULL "
        "ORDER BY created_at DESC LIMIT 1",
        (code,),
    ).fetchone()
    if not row or row["expires_at"] <= _iso(_now()):
        return None
    conn.execute("UPDATE login_codes SET used_at = ? WHERE code = ?", (_iso(_now()), code))
    return create_session(conn, row["user_id"])


# ---------------------------------------------------------------- подписка


def set_plan(conn: sqlite3.Connection, user_id: str, plan: str) -> sqlite3.Row:
    if plan not in {"free", "pro"}:
        raise ValueError("Неизвестный тариф")
    conn.execute("UPDATE users SET plan = ? WHERE id = ?", (plan, user_id))
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def bind_operator(conn: sqlite3.Connection, user_id: str, operator_id: int | None) -> sqlite3.Row:
    conn.execute("UPDATE users SET operator_id = ? WHERE id = ?", (operator_id, user_id))
    return conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()


def email_fingerprint(email: str | None) -> str | None:
    """Не храним лишнего: для логов достаточно короткого отпечатка."""
    if not email:
        return None
    return hashlib.sha256(email.encode("utf-8")).hexdigest()[:12]

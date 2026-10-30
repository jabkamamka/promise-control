"""Сотрудники: регистрация по почте, вход по паролю, сессии.

Пароли хранятся как PBKDF2-HMAC-SHA256 с солью (stdlib, без зависимостей).
Сессия — случайный токен в таблице `sessions`, клиент получает его в HttpOnly-cookie.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import re
import secrets
import sqlite3
from typing import Any

from ..utils import normalize_text, parse_iso, utc_now

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[a-zа-я]{2,}$", re.IGNORECASE)
PASSWORD_MIN = 8
PASSWORD_MAX = 128
SESSION_DAYS = 30
PBKDF2_ITERATIONS = 200_000

#: Сколько живёт ссылка/код входа и сколько писем можно запросить за окно.
LINK_MINUTES = 15
CONFIRM_MINUTES = 24 * 60
LINK_COOLDOWN_MINUTES = 10
LINK_MAX_PER_WINDOW = 3
LINK_MAX_ATTEMPTS = 5


class AuthError(Exception):
    """Ошибка авторизации с человекочитаемым текстом."""

    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------- #
# Пароли
# --------------------------------------------------------------------------- #

def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), PBKDF2_ITERATIONS)
    return f"pbkdf2${PBKDF2_ITERATIONS}${salt}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        scheme, iterations, salt, expected = stored.split("$")
        if scheme != "pbkdf2":
            return False
        digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), int(iterations))
        return hmac.compare_digest(digest.hex(), expected)
    except (ValueError, TypeError):
        return False


def normalize_email(value: str) -> str:
    email = normalize_text(value or "").strip().lower()
    if not EMAIL_RE.match(email):
        raise AuthError("Укажите корректный email", 422)
    return email


def validate_password(password: str) -> str:
    if not password or len(password) < PASSWORD_MIN:
        raise AuthError(f"Пароль должен быть не короче {PASSWORD_MIN} символов", 422)
    if len(password) > PASSWORD_MAX:
        raise AuthError("Пароль слишком длинный", 422)
    return password


def normalize_name(value: str) -> str:
    name = " ".join((value or "").split())
    if len(name) < 2:
        raise AuthError("Укажите имя сотрудника", 422)
    if len(name) > 120:
        raise AuthError("Имя слишком длинное", 422)
    return name


# --------------------------------------------------------------------------- #
# Сессии
# --------------------------------------------------------------------------- #

def create_session(conn: sqlite3.Connection, employee_id: int) -> tuple[str, str]:
    token = secrets.token_urlsafe(32)
    now = dt.datetime.now(dt.timezone.utc)
    expires = now + dt.timedelta(days=SESSION_DAYS)
    conn.execute(
        "INSERT INTO sessions (token, employee_id, created_at, expires_at) VALUES (?,?,?,?)",
        (token, employee_id, utc_now(), expires.replace(microsecond=0).isoformat().replace("+00:00", "Z")),
    )
    conn.commit()
    return token, expires.isoformat()


def employee_by_session(conn: sqlite3.Connection, token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    row = conn.execute(
        """SELECT e.* FROM sessions s JOIN employees e ON e.id = s.employee_id
           WHERE s.token = ? AND s.expires_at > ? AND e.is_active = 1""",
        (token, utc_now()),
    ).fetchone()
    return dict(row) if row else None


def delete_session(conn: sqlite3.Connection, token: str | None) -> None:
    if token:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()


def public_employee(row: dict[str, Any] | None) -> dict[str, Any] | None:
    if not row:
        return None
    return {
        "id": row["id"],
        "email": row["email"],
        "full_name": row["full_name"],
        "role": row["role"],
        "email_confirmed": bool(row.get("email_confirmed_at")),
        "email_confirmed_at": row.get("email_confirmed_at"),
        "created_at": row["created_at"],
        "last_login_at": row.get("last_login_at"),
    }


# --------------------------------------------------------------------------- #
# Сотрудники
# --------------------------------------------------------------------------- #

def employee_by_email(conn: sqlite3.Connection, email: str) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM employees WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None


def register(
    conn: sqlite3.Connection,
    email: str,
    password: str,
    full_name: str,
) -> dict[str, Any]:
    """Создаёт неподтверждённого сотрудника. Вход — только после подтверждения почты."""
    email = normalize_email(email)
    password = validate_password(password)
    name = normalize_name(full_name)
    if employee_by_email(conn, email):
        raise AuthError("Сотрудник с таким email уже зарегистрирован", 409)

    conn.execute(
        """INSERT INTO employees (email, password_hash, full_name, role, created_at)
           VALUES (?,?,?,'operator',?)""",
        (email, hash_password(password), name, utc_now()),
    )
    conn.commit()
    return employee_by_email(conn, email) or {}


def login(conn: sqlite3.Connection, email: str, password: str) -> dict[str, Any]:
    email = normalize_email(email)
    employee = employee_by_email(conn, email)
    if not employee or not employee["is_active"]:
        raise AuthError("Неверный email или пароль", 401)
    if not verify_password(password, employee["password_hash"]):
        raise AuthError("Неверный email или пароль", 401)
    if not employee.get("email_confirmed_at"):
        raise AuthError(
            "Почта не подтверждена. Откройте ссылку из письма или запросите новое.",
            403,
        )
    conn.execute("UPDATE employees SET last_login_at = ? WHERE id = ?", (utc_now(), employee["id"]))
    conn.commit()
    return employee


def change_password(conn: sqlite3.Connection, employee: dict[str, Any], current: str, new: str) -> None:
    if not verify_password(current, employee["password_hash"]):
        raise AuthError("Текущий пароль неверен", 401)
    new = validate_password(new)
    conn.execute(
        "UPDATE employees SET password_hash = ? WHERE id = ?",
        (hash_password(new), employee["id"]),
    )
    # все прочие сессии закрываем: пароль сменился
    conn.execute("DELETE FROM sessions WHERE employee_id = ?", (employee["id"],))
    conn.commit()


# --------------------------------------------------------------------------- #
# Вход по ссылке на почту (без пароля)
# --------------------------------------------------------------------------- #

def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _iso_in(minutes: int) -> str:
    moment = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def name_from_email(email: str) -> str:
    """Имя по умолчанию для нового сотрудника: «anna.smirnova» → «Anna Smirnova»."""
    local = email.split("@", 1)[0]
    parts = [part for part in re.split(r"[._\-+]", local) if part]
    if not parts:
        return "Сотрудник"
    pretty = [part[:1].upper() + part[1:] for part in parts[:2]]
    return " ".join(pretty)


def start_email_login(
    conn: sqlite3.Connection,
    email: str,
    full_name: str | None = None,
) -> dict[str, Any]:
    """Создаёт одноразовую ссылку и код. Нового сотрудника заводит сразу."""
    email = normalize_email(email)

    window = _iso_in(-LINK_COOLDOWN_MINUTES)
    recent = conn.execute(
        "SELECT COUNT(*) AS c FROM login_tokens WHERE email = ? AND created_at > ?",
        (email, window),
    ).fetchone()["c"]
    if recent >= LINK_MAX_PER_WINDOW:
        raise AuthError("Слишком много писем — попробуйте через несколько минут", 429)

    employee = employee_by_email(conn, email)
    created = False
    if employee and not employee["is_active"]:
        raise AuthError("Сотрудник заблокирован", 403)
    if not employee:
        name = normalize_name(full_name) if (full_name or "").strip() else name_from_email(email)
        # пароля нет: вход только по ссылке, пока сотрудник не задаст пароль сам
        conn.execute(
            """INSERT INTO employees (email, password_hash, full_name, role, created_at)
               VALUES (?, ?, ?, 'operator', ?)""",
            (email, "!login-by-link", name, utc_now()),
        )
        conn.commit()
        employee = employee_by_email(conn, email)
        created = True

    token, code = _issue_token(conn, email, "login", LINK_MINUTES)
    return {
        "token": token,
        "code": code,
        "email": email,
        "employee": employee,
        "created": created,
        "expires_in_minutes": LINK_MINUTES,
    }


def _issue_token(
    conn: sqlite3.Connection,
    email: str,
    purpose: str,
    minutes: int,
) -> tuple[str, str]:
    """Одноразовый токен и код. Прежние неиспользованные токены того же назначения гасим."""
    token = secrets.token_urlsafe(32)
    code = f"{secrets.randbelow(1_000_000):06d}"
    conn.execute(
        """UPDATE login_tokens SET used_at = ?
           WHERE email = ? AND purpose = ? AND used_at IS NULL""",
        (utc_now(), email, purpose),
    )
    conn.execute(
        """INSERT INTO login_tokens (email, token_hash, code, purpose, expires_at, created_at)
           VALUES (?,?,?,?,?,?)""",
        (email, _token_hash(token), code, purpose, _iso_in(minutes), utc_now()),
    )
    conn.commit()
    return token, code


def issue_confirmation(conn: sqlite3.Connection, employee: dict[str, Any]) -> tuple[str, str]:
    """Ссылка подтверждения почты для зарегистрированного сотрудника."""
    if employee.get("email_confirmed_at"):
        raise AuthError("Почта уже подтверждена", 409)
    return _issue_token(conn, employee["email"], "confirm", CONFIRM_MINUTES)


def confirm_by_token(conn: sqlite3.Connection, token: str) -> dict[str, Any]:
    """Подтверждает почту по ссылке и впускает сотрудника."""
    if not token:
        raise AuthError("Ссылка недействительна", 400)
    row = _login_token_row(conn, "token_hash = ? AND purpose = 'confirm'", (_token_hash(token),))
    employee = employee_by_email(conn, row["email"])
    if not employee or not employee["is_active"]:
        raise AuthError("Сотрудник не найден", 404)

    now = utc_now()
    conn.execute("UPDATE employees SET email_confirmed_at = ? WHERE id = ?", (now, employee["id"]))
    conn.execute("UPDATE employees SET last_login_at = ? WHERE id = ?", (now, employee["id"]))
    conn.execute("UPDATE login_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
    conn.commit()
    return employee_by_email(conn, row["email"]) or employee


def _login_token_row(conn: sqlite3.Connection, where: str, params: tuple) -> sqlite3.Row:
    row = conn.execute(
        f"SELECT * FROM login_tokens WHERE {where} AND used_at IS NULL ORDER BY id DESC LIMIT 1",
        params,
    ).fetchone()
    if not row:
        raise AuthError("Ссылка недействительна. Запросите новую.", 400)
    expires = parse_iso(row["expires_at"])
    if not expires or expires < dt.datetime.now(dt.timezone.utc):
        raise AuthError("Срок действия ссылки истёк — запросите новую", 400)
    if row["attempts"] >= LINK_MAX_ATTEMPTS:
        raise AuthError("Слишком много попыток. Запросите новую ссылку.", 429)
    return row


def _complete_login(conn: sqlite3.Connection, row: sqlite3.Row) -> dict[str, Any]:
    employee = employee_by_email(conn, row["email"])
    if not employee or not employee["is_active"]:
        raise AuthError("Сотрудник не найден", 404)
    now = utc_now()
    conn.execute("UPDATE login_tokens SET used_at = ? WHERE id = ?", (now, row["id"]))
    conn.execute("UPDATE employees SET last_login_at = ? WHERE id = ?", (now, employee["id"]))
    if not employee.get("email_confirmed_at"):
        # переход по ссылке из письма сам доказывает, что ящик существует
        conn.execute("UPDATE employees SET email_confirmed_at = ? WHERE id = ?", (now, employee["id"]))
    conn.commit()
    return employee_by_email(conn, row["email"]) or employee


def login_by_token(conn: sqlite3.Connection, token: str) -> dict[str, Any]:
    if not token:
        raise AuthError("Ссылка недействительна", 400)
    row = _login_token_row(conn, "token_hash = ? AND purpose = 'login'", (_token_hash(token),))
    return _complete_login(conn, row)


def login_by_email_code(conn: sqlite3.Connection, email: str, code: str) -> dict[str, Any]:
    email = normalize_email(email)
    code = (code or "").strip()
    if len(code) != 6 or not code.isdigit():
        raise AuthError("Код состоит из шести цифр", 422)
    row = conn.execute(
        """SELECT * FROM login_tokens WHERE email = ? AND purpose = 'login' AND used_at IS NULL
           ORDER BY id DESC LIMIT 1""",
        (email,),
    ).fetchone()
    if not row:
        raise AuthError("Код не найден. Запросите новую ссылку.", 400)
    if not hmac.compare_digest(row["code"], code):
        conn.execute("UPDATE login_tokens SET attempts = attempts + 1 WHERE id = ?", (row["id"],))
        conn.commit()
        left = LINK_MAX_ATTEMPTS - (row["attempts"] + 1)
        raise AuthError(f"Неверный код. Осталось попыток: {max(left, 0)}", 400)
    row = _login_token_row(conn, "id = ?", (row["id"],))
    return _complete_login(conn, row)

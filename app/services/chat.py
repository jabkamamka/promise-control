"""Внутренний мессенджер: каналы, личные диалоги, сообщения и вложения.

Модель простая и «слеечная»:

* канал (channel) — общий для всей команды, участники добавляются автоматически;
* группа (group) — приватный чат, участников приглашает владелец;
* личный диалог (direct) — ровно два сотрудника, создаётся один раз на пару.

Непрочитанное считается по `chat_members.last_read_id`, печать — по
`typing_at`, присутствие — по `chat_presence.last_seen_at`. Внешних
зависимостей и брокеров нет: всё живёт в той же SQLite, что и остальной сервис.
"""
from __future__ import annotations

import datetime as dt
import json
import mimetypes
import re
import sqlite3
import uuid
from pathlib import Path
from typing import Any

from ..config import settings
from ..utils import parse_iso, utc_now

ONLINE_SECONDS = 90
TYPING_SECONDS = 8
MAX_GROUP_MEMBERS = 50

#: Расширения, которые нельзя загружать: HTML/SVG/скрипты превращают вложение
#: в фишинг или XSS на домене сервиса.
BLOCKED_EXTENSIONS = {
    ".html", ".htm", ".xhtml", ".svg", ".xml", ".js", ".mjs", ".cjs",
    ".exe", ".msi", ".bat", ".cmd", ".ps1", ".vbs", ".vbe", ".scr", ".com",
    ".dll", ".jar", ".lnk", ".hta", ".reg", ".sh", ".app", ".pif",
}

INLINE_IMAGE_MIME = {"image/png", "image/jpeg", "image/gif", "image/webp"}

DEFAULT_CHANNELS = (
    ("general", "Общий", "Вся команда: объявления, вопросы, важное"),
    ("operators", "Операторы", "Смена, звонки и обещания клиентам"),
    ("urgent", "Срочное", "Просроченные обещания и эскалации"),
)


class ChatError(Exception):
    """Ошибка мессенджера с HTTP-статусом для API-слоя."""

    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


# --------------------------------------------------------------------------- #
# Служебные помощники
# --------------------------------------------------------------------------- #

def _seconds_since(value: str | None) -> float:
    parsed = parse_iso(value)
    if not parsed:
        return 10**9
    return (dt.datetime.now(dt.timezone.utc) - parsed).total_seconds()


def _is_online(last_seen_at: str | None) -> bool:
    return _seconds_since(last_seen_at) <= ONLINE_SECONDS


def _initials(full_name: str) -> str:
    parts = [part for part in re.split(r"\s+", (full_name or "").strip()) if part]
    if not parts:
        return "??"
    first = parts[0][0]
    second = parts[1][0] if len(parts) > 1 else ""
    return (first + second).upper()


def _hue(employee_id: int | None) -> int:
    return ((employee_id or 1) * 47) % 360


def _plural(count: int, one: str, few: str, many: str) -> str:
    value = abs(count) % 100
    tail = value % 10
    if 10 < value < 20:
        return many
    if tail == 1:
        return one
    if 2 <= tail <= 4:
        return few
    return many


def _person(row: sqlite3.Row, online: bool | None = None) -> dict[str, Any]:
    name = row["full_name"] or "Сотрудник"
    keys = row.keys()
    last_seen_at = row["last_seen_at"] if "last_seen_at" in keys else None
    return {
        "id": row["id"],
        "full_name": name,
        "role": row["role"],
        "online": _is_online(last_seen_at) if online is None else online,
        "last_seen_at": last_seen_at,
        "initials": _initials(name),
        "hue": _hue(row["id"]),
    }


def _like(query: str) -> str:
    escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
    return f"%{escaped}%"


def _snippet(body: str, query: str, limit: int = 180) -> str:
    body = (body or "").replace("\n", " ")
    if len(body) <= limit:
        return body
    position = body.lower().find((query or "").lower())
    start = max(0, position - limit // 3) if position >= 0 else 0
    fragment = body[start : start + limit].strip()
    return ("…" if start else "") + fragment + ("…" if start + limit < len(body) else "")


def _json_list(raw: str | None) -> list[int]:
    try:
        data = json.loads(raw or "[]")
    except (TypeError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    return [int(item) for item in data if isinstance(item, (int, str)) and str(item).isdigit()]


# --------------------------------------------------------------------------- #
# Каналы и участники
# --------------------------------------------------------------------------- #

def ensure_default_channels(conn: sqlite3.Connection) -> None:
    """Создаёт общесистемные каналы. Вызывается при инициализации БД."""
    now = utc_now()
    for slug, title, topic in DEFAULT_CHANNELS:
        conn.execute(
            """INSERT INTO chat_channels (kind, slug, title, topic, created_at, is_default)
               VALUES ('channel', ?, ?, ?, ?, 1)
               ON CONFLICT(slug) DO NOTHING""",
            (slug, title, topic, now),
        )


def ensure_default_membership(conn: sqlite3.Connection, employee_id: int) -> int:
    """Добавляет сотрудника в общесистемные каналы. Возвращает число вступлений."""
    added = 0
    rows = conn.execute("SELECT id FROM chat_channels WHERE is_default = 1").fetchall()
    for row in rows:
        if _ensure_membership(conn, row["id"], employee_id, "member"):
            added += 1
    return added


def _ensure_membership(
    conn: sqlite3.Connection, channel_id: int, employee_id: int, role: str = "member"
) -> bool:
    exists = conn.execute(
        "SELECT 1 FROM chat_members WHERE channel_id = ? AND employee_id = ?",
        (channel_id, employee_id),
    ).fetchone()
    if exists:
        return False
    last_id = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS last FROM chat_messages WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()["last"]
    conn.execute(
        """INSERT INTO chat_members (channel_id, employee_id, role, joined_at, last_read_id)
           VALUES (?, ?, ?, ?, ?)""",
        (channel_id, employee_id, role, utc_now(), last_id),
    )
    return True


def _membership(conn: sqlite3.Connection, channel_id: int, employee_id: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM chat_members WHERE channel_id = ? AND employee_id = ?",
        (channel_id, employee_id),
    ).fetchone()


def _require_membership(conn: sqlite3.Connection, channel_id: int, employee_id: int) -> sqlite3.Row:
    channel = conn.execute(
        "SELECT * FROM chat_channels WHERE id = ?", (channel_id,)
    ).fetchone()
    if not channel:
        raise ChatError("Диалог не найден", 404)
    membership = _membership(conn, channel_id, employee_id)
    if not membership:
        raise ChatError("Нет доступа к этому диалогу", 403)
    return membership


def _members(conn: sqlite3.Connection, channel_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.id, e.full_name, e.role, e.is_active,
                  m.role AS member_role, m.joined_at, p.last_seen_at
           FROM chat_members m
           JOIN employees e ON e.id = m.employee_id
           LEFT JOIN chat_presence p ON p.employee_id = e.id
           WHERE m.channel_id = ?
           ORDER BY CASE m.role WHEN 'owner' THEN 0 ELSE 1 END,
                    e.full_name COLLATE NOCASE""",
        (channel_id,),
    ).fetchall()
    result = []
    for row in rows:
        person = _person(row)
        person["member_role"] = row["member_role"]
        person["joined_at"] = row["joined_at"]
        result.append(person)
    return result


def _direct_peer(members: list[dict[str, Any]], me_id: int) -> dict[str, Any] | None:
    for member in members:
        if member["id"] != me_id:
            return member
    return None


def _title_for(
    channel: sqlite3.Row, members: list[dict[str, Any]], me_id: int
) -> str:
    if channel["kind"] == "direct":
        peer = _direct_peer(members, me_id)
        return peer["full_name"] if peer else "Личный диалог"
    return channel["title"] or "Без названия"


def _channel_avatar(channel: sqlite3.Row, members: list[dict[str, Any]], me_id: int) -> dict[str, Any]:
    if channel["kind"] == "direct":
        peer = _direct_peer(members, me_id)
        if peer:
            return {"initials": peer["initials"], "hue": peer["hue"], "kind": "person"}
        return {"initials": "??", "hue": _hue(channel["id"]), "kind": "person"}
    title = channel["title"] or "Чат"
    return {"initials": _initials(title), "hue": _hue(channel["id"]), "kind": channel["kind"]}


def _last_message(conn: sqlite3.Connection, channel_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """SELECT m.id, m.body, m.kind, m.created_at, m.deleted_at, m.sender_id,
                  e.full_name AS sender_name
           FROM chat_messages m
           LEFT JOIN employees e ON e.id = m.sender_id
           WHERE m.channel_id = ?
           ORDER BY m.id DESC LIMIT 1""",
        (channel_id,),
    ).fetchone()
    if not row:
        return None
    body = "" if row["deleted_at"] else (row["body"] or "")
    return {
        "id": row["id"],
        "body": body[:160],
        "kind": row["kind"],
        "created_at": row["created_at"],
        "deleted": bool(row["deleted_at"]),
        "sender_id": row["sender_id"],
        "sender_name": row["sender_name"] or "Система",
    }


def _unread(conn: sqlite3.Connection, channel_id: int, employee_id: int, last_read_id: int) -> tuple[int, int]:
    count = conn.execute(
        """SELECT COUNT(*) AS c FROM chat_messages
           WHERE channel_id = ? AND id > ? AND deleted_at IS NULL
             AND (sender_id IS NULL OR sender_id <> ?)""",
        (channel_id, last_read_id, employee_id),
    ).fetchone()["c"]
    mention_rows = conn.execute(
        """SELECT mentions FROM chat_messages
           WHERE channel_id = ? AND id > ? AND deleted_at IS NULL
             AND sender_id IS NOT NULL AND sender_id <> ? AND mentions <> '[]'""",
        (channel_id, last_read_id, employee_id),
    ).fetchall()
    mentions = sum(1 for row in mention_rows if employee_id in _json_list(row["mentions"]))
    return count, mentions


def _summary(conn: sqlite3.Connection, row: sqlite3.Row, me_id: int) -> dict[str, Any]:
    channel = row
    members = _members(conn, channel["id"])
    unread, mentions = _unread(conn, channel["id"], me_id, row["last_read_id"])
    title = _title_for(channel, members, me_id)
    online_count = sum(1 for member in members if member["online"])
    peer = _direct_peer(members, me_id) if channel["kind"] == "direct" else None
    last_message = _last_message(conn, channel["id"])

    if channel["kind"] == "channel":
        subtitle = channel["topic"]
    elif channel["kind"] == "direct":
        subtitle = "в сети" if peer and peer["online"] else "не в сети"
    else:
        subtitle = (
            f"{len(members)} {_plural(len(members), 'участник', 'участника', 'участников')}"
            f" · {online_count} в сети"
        )

    return {
        "id": channel["id"],
        "kind": channel["kind"],
        "slug": channel["slug"],
        "title": title,
        "topic": channel["topic"],
        "subtitle": subtitle,
        "avatar": _channel_avatar(channel, members, me_id),
        "unread": unread,
        "mentions": mentions,
        "muted": bool(row["muted"]),
        "last_read_id": row["last_read_id"],
        "member_count": len(members),
        "online_count": online_count,
        "peer": peer,
        "last_message": last_message,
        "last_id": last_message["id"] if last_message else 0,
        "me_role": row["role"],
        "can_manage": row["role"] == "owner",
        "created_at": channel["created_at"],
    }


def list_conversations(conn: sqlite3.Connection, me: dict[str, Any]) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT c.*, m.role, m.last_read_id, m.muted
           FROM chat_channels c
           JOIN chat_members m ON m.channel_id = c.id AND m.employee_id = ?
           WHERE c.is_archived = 0""",
        (me["id"],),
    ).fetchall()
    conversations = [_summary(conn, row, me["id"]) for row in rows]
    conversations.sort(key=lambda item: (item["last_id"], item["id"]), reverse=True)
    return conversations


def conversation_payload(conn: sqlite3.Connection, channel_id: int, me: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute(
        """SELECT c.*, m.role, m.last_read_id, m.muted
           FROM chat_channels c
           JOIN chat_members m ON m.channel_id = c.id AND m.employee_id = ?
           WHERE c.id = ?""",
        (me["id"], channel_id),
    ).fetchone()
    if not row:
        raise ChatError("Диалог не найден", 404)
    payload = _summary(conn, row, me["id"])
    payload["can_manage"] = row["role"] == "owner" or me.get("role") == "admin"
    return payload


def conversation_details(conn: sqlite3.Connection, channel_id: int, me: dict[str, Any]) -> dict[str, Any]:
    membership = _require_membership(conn, channel_id, me["id"])
    channel = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    payload = conversation_payload(conn, channel_id, me)
    return {
        "conversation": payload,
        "members": _members(conn, channel_id),
        "me_role": membership["role"],
        "can_manage": membership["role"] == "owner" or me.get("role") == "admin",
    }


def create_conversation(
    conn: sqlite3.Connection,
    me: dict[str, Any],
    kind: str,
    title: str = "",
    employee_ids: list[int] | None = None,
) -> dict[str, Any]:
    if kind not in {"direct", "group"}:
        raise ChatError("Поддерживаются личные диалоги и группы", 422)

    ids = []
    for value in employee_ids or []:
        try:
            employee_id = int(value)
        except (TypeError, ValueError):
            continue
        if employee_id != me["id"] and employee_id not in ids:
            ids.append(employee_id)

    if kind == "direct":
        if len(ids) != 1:
            raise ChatError("Для личного диалога выберите одного сотрудника", 422)
        peer_id = ids[0]
        _require_active(conn, [peer_id])
        direct_key = ":".join(str(item) for item in sorted([me["id"], peer_id]))
        existing = conn.execute(
            "SELECT id FROM chat_channels WHERE direct_key = ?", (direct_key,)
        ).fetchone()
        if existing:
            _ensure_membership(conn, existing["id"], me["id"])
            _ensure_membership(conn, existing["id"], peer_id)
            conn.commit()
            return conversation_payload(conn, existing["id"], me)
        now = utc_now()
        cursor = conn.execute(
            """INSERT INTO chat_channels (kind, title, topic, created_by, created_at, direct_key)
               VALUES ('direct', '', '', ?, ?, ?)""",
            (me["id"], now, direct_key),
        )
        channel_id = int(cursor.lastrowid)
        _ensure_membership(conn, channel_id, me["id"], "member")
        _ensure_membership(conn, channel_id, peer_id, "member")
        conn.commit()
        return conversation_payload(conn, channel_id, me)

    clean_title = (title or "").strip()
    if not 2 <= len(clean_title) <= 80:
        raise ChatError("Название группы — от 2 до 80 символов", 422)
    if not ids:
        raise ChatError("Добавьте хотя бы одного участника", 422)
    if len(ids) > MAX_GROUP_MEMBERS - 1:
        raise ChatError(f"В группе может быть не больше {MAX_GROUP_MEMBERS} участников", 422)
    _require_active(conn, ids)

    now = utc_now()
    cursor = conn.execute(
        """INSERT INTO chat_channels (kind, title, topic, created_by, created_at)
           VALUES ('group', ?, '', ?, ?)""",
        (clean_title, me["id"], now),
    )
    channel_id = int(cursor.lastrowid)
    _ensure_membership(conn, channel_id, me["id"], "owner")
    for employee_id in ids:
        _ensure_membership(conn, channel_id, employee_id, "member")
    _send_system(conn, channel_id, f"{me['full_name']} создал(а) группу «{clean_title}»")
    conn.commit()
    return conversation_payload(conn, channel_id, me)


def _require_active(conn: sqlite3.Connection, employee_ids: list[int]) -> None:
    if not employee_ids:
        return
    placeholders = ",".join("?" for _ in employee_ids)
    rows = conn.execute(
        f"SELECT id FROM employees WHERE is_active = 1 AND id IN ({placeholders})",
        employee_ids,
    ).fetchall()
    found = {row["id"] for row in rows}
    missing = [str(item) for item in employee_ids if item not in found]
    if missing:
        raise ChatError("Сотрудник не найден: " + ", ".join(missing), 422)


def update_conversation(
    conn: sqlite3.Connection, channel_id: int, me: dict[str, Any], title: str | None, topic: str | None
) -> dict[str, Any]:
    membership = _require_membership(conn, channel_id, me["id"])
    channel = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    if channel["kind"] != "group":
        raise ChatError("Переименовать можно только группу", 403)
    if membership["role"] != "owner" and me.get("role") != "admin":
        raise ChatError("Переименовать группу может только её владелец", 403)

    if title is not None:
        clean_title = title.strip()
        if not 2 <= len(clean_title) <= 80:
            raise ChatError("Название группы — от 2 до 80 символов", 422)
        conn.execute("UPDATE chat_channels SET title = ? WHERE id = ?", (clean_title, channel_id))
    if topic is not None:
        conn.execute(
            "UPDATE chat_channels SET topic = ? WHERE id = ?", (topic.strip()[:200], channel_id)
        )
    conn.commit()
    return conversation_details(conn, channel_id, me)


def add_members(
    conn: sqlite3.Connection, channel_id: int, me: dict[str, Any], employee_ids: list[int]
) -> dict[str, Any]:
    membership = _require_membership(conn, channel_id, me["id"])
    channel = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    if channel["kind"] != "group":
        raise ChatError("Участников можно добавлять только в группу", 403)
    if membership["role"] != "owner" and me.get("role") != "admin":
        raise ChatError("Приглашать участников может владелец группы", 403)

    current = [member["id"] for member in _members(conn, channel_id)]
    ids = []
    for value in employee_ids:
        try:
            employee_id = int(value)
        except (TypeError, ValueError):
            continue
        if employee_id not in current and employee_id not in ids:
            ids.append(employee_id)
    if not ids:
        return conversation_details(conn, channel_id, me)
    if len(current) + len(ids) > MAX_GROUP_MEMBERS:
        raise ChatError(f"В группе может быть не больше {MAX_GROUP_MEMBERS} участников", 422)
    _require_active(conn, ids)
    for employee_id in ids:
        _ensure_membership(conn, channel_id, employee_id, "member")
    names = conn.execute(
        f"SELECT full_name FROM employees WHERE id IN ({','.join('?' for _ in ids)})", ids
    ).fetchall()
    _send_system(
        conn,
        channel_id,
        f"{me['full_name']} добавил(а): " + ", ".join(row["full_name"] for row in names),
    )
    conn.commit()
    return conversation_details(conn, channel_id, me)


def remove_member(
    conn: sqlite3.Connection, channel_id: int, me: dict[str, Any], employee_id: int
) -> dict[str, Any]:
    membership = _require_membership(conn, channel_id, me["id"])
    channel = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    if channel["kind"] != "group":
        raise ChatError("Удалить участника можно только из группы", 403)
    if employee_id == me["id"]:
        return leave_conversation(conn, channel_id, me)
    if membership["role"] != "owner" and me.get("role") != "admin":
        raise ChatError("Удалять участников может владелец группы", 403)
    target = conn.execute(
        "SELECT full_name FROM employees WHERE id = ?", (employee_id,)
    ).fetchone()
    if not target:
        raise ChatError("Сотрудник не найден", 404)
    conn.execute(
        "DELETE FROM chat_members WHERE channel_id = ? AND employee_id = ?",
        (channel_id, employee_id),
    )
    _send_system(conn, channel_id, f"{me['full_name']} удалил(а) {target['full_name']}")
    conn.commit()
    return conversation_details(conn, channel_id, me)


def leave_conversation(conn: sqlite3.Connection, channel_id: int, me: dict[str, Any]) -> dict[str, Any]:
    membership = _require_membership(conn, channel_id, me["id"])
    channel = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    if channel["kind"] != "group":
        raise ChatError("Выйти можно только из группы", 403)

    others = [member for member in _members(conn, channel_id) if member["id"] != me["id"]]
    conn.execute(
        "DELETE FROM chat_members WHERE channel_id = ? AND employee_id = ?",
        (channel_id, me["id"]),
    )
    if not others:
        conn.execute("UPDATE chat_channels SET is_archived = 1 WHERE id = ?", (channel_id,))
    elif membership["role"] == "owner":
        new_owner = others[0]
        conn.execute(
            "UPDATE chat_members SET role = 'owner' WHERE channel_id = ? AND employee_id = ?",
            (channel_id, new_owner["id"]),
        )
        _send_system(
            conn,
            channel_id,
            f"{me['full_name']} покинул(а) группу. Владелец теперь {new_owner['full_name']}",
        )
    else:
        _send_system(conn, channel_id, f"{me['full_name']} покинул(а) группу")
    conn.commit()
    return {"left": True, "channel_id": channel_id}


def set_muted(
    conn: sqlite3.Connection, channel_id: int, me: dict[str, Any], muted: bool
) -> dict[str, Any]:
    _require_membership(conn, channel_id, me["id"])
    conn.execute(
        "UPDATE chat_members SET muted = ? WHERE channel_id = ? AND employee_id = ?",
        (1 if muted else 0, channel_id, me["id"]),
    )
    conn.commit()
    return conversation_payload(conn, channel_id, me)


# --------------------------------------------------------------------------- #
# Присутствие и контакты
# --------------------------------------------------------------------------- #

def touch_presence(conn: sqlite3.Connection, employee_id: int) -> None:
    conn.execute(
        """INSERT INTO chat_presence (employee_id, last_seen_at) VALUES (?, ?)
           ON CONFLICT(employee_id) DO UPDATE SET last_seen_at = excluded.last_seen_at""",
        (employee_id, utc_now()),
    )


def list_contacts(conn: sqlite3.Connection, me_id: int) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT e.id, e.full_name, e.role, p.last_seen_at
           FROM employees e
           LEFT JOIN chat_presence p ON p.employee_id = e.id
           WHERE e.is_active = 1 AND e.id <> ?
           ORDER BY e.full_name COLLATE NOCASE""",
        (me_id,),
    ).fetchall()
    return [_person(row) for row in rows]


def bootstrap(conn: sqlite3.Connection, me: dict[str, Any]) -> dict[str, Any]:
    ensure_default_membership(conn, me["id"])
    touch_presence(conn, me["id"])
    conn.commit()
    conversations = list_conversations(conn, me)
    return {
        "me": {
            "id": me["id"],
            "full_name": me["full_name"],
            "role": me.get("role"),
            "initials": _initials(me["full_name"]),
            "hue": _hue(me["id"]),
        },
        "contacts": list_contacts(conn, me["id"]),
        "conversations": conversations,
        "totals": _totals(conversations),
        "timezone": settings.timezone,
        "limits": {
            "message_chars": settings.chat_message_max_chars,
            "upload_mb": settings.chat_max_upload_mb,
        },
    }


def _totals(conversations: list[dict[str, Any]]) -> dict[str, int]:
    unread = sum(item["unread"] for item in conversations if not item["muted"])
    mentions = sum(item["mentions"] for item in conversations if not item["muted"])
    return {"unread": unread, "mentions": mentions}


def unread_summary(conn: sqlite3.Connection, me: dict[str, Any]) -> dict[str, int]:
    ensure_default_membership(conn, me["id"])
    touch_presence(conn, me["id"])
    conn.commit()
    rows = conn.execute(
        """SELECT c.id, m.last_read_id, m.muted
           FROM chat_channels c
           JOIN chat_members m ON m.channel_id = c.id AND m.employee_id = ?
           WHERE c.is_archived = 0""",
        (me["id"],),
    ).fetchall()
    totals = {"unread": 0, "mentions": 0}
    for row in rows:
        if row["muted"]:
            continue
        unread, mentions = _unread(conn, row["id"], me["id"], row["last_read_id"])
        totals["unread"] += unread
        totals["mentions"] += mentions
    return totals


# --------------------------------------------------------------------------- #
# Сообщения
# --------------------------------------------------------------------------- #

MESSAGE_SELECT = """
SELECT m.*, e.full_name AS sender_name, e.role AS sender_role,
       r.body AS reply_body, r.deleted_at AS reply_deleted, r.kind AS reply_kind,
       re.full_name AS reply_sender_name,
       a.id AS attachment_id, a.filename AS attachment_filename,
       a.mime AS attachment_mime, a.size AS attachment_size
FROM chat_messages m
LEFT JOIN employees e ON e.id = m.sender_id
LEFT JOIN chat_messages r ON r.id = m.reply_to
LEFT JOIN employees re ON re.id = r.sender_id
LEFT JOIN chat_attachments a ON a.message_id = m.id
"""


def _message(row: sqlite3.Row) -> dict[str, Any]:
    deleted = bool(row["deleted_at"])
    sender = None
    if row["sender_id"]:
        sender = {
            "id": row["sender_id"],
            "full_name": row["sender_name"] or "Сотрудник",
            "role": row["sender_role"],
            "initials": _initials(row["sender_name"] or ""),
            "hue": _hue(row["sender_id"]),
        }
    reply = None
    if row["reply_to"]:
        reply = {
            "id": row["reply_to"],
            "body": "" if row["reply_deleted"] else (row["reply_body"] or "")[:200],
            "sender_name": row["reply_sender_name"] or "Сотрудник",
            "deleted": bool(row["reply_deleted"]),
        }
    attachment = None
    if row["attachment_id"]:
        attachment = {
            "id": row["attachment_id"],
            "filename": row["attachment_filename"],
            "mime": row["attachment_mime"],
            "size": row["attachment_size"],
            "url": f"/chat/attachments/{row['attachment_id']}",
            "is_image": row["attachment_mime"] in INLINE_IMAGE_MIME,
        }
    return {
        "id": row["id"],
        "channel_id": row["channel_id"],
        "kind": row["kind"],
        "body": "" if deleted else row["body"],
        "created_at": row["created_at"],
        "edited_at": row["edited_at"],
        "deleted": deleted,
        "sender": sender,
        "reply_to": reply,
        "mentions": _json_list(row["mentions"]),
        "attachment": attachment,
    }


def _read_up_to(conn: sqlite3.Connection, channel_id: int, me_id: int) -> int:
    row = conn.execute(
        """SELECT COALESCE(MAX(last_read_id), 0) AS value FROM chat_members
           WHERE channel_id = ? AND employee_id <> ?""",
        (channel_id, me_id),
    ).fetchone()
    return int(row["value"] or 0)


def typing_names(conn: sqlite3.Connection, channel_id: int, me_id: int) -> list[str]:
    rows = conn.execute(
        """SELECT e.full_name, m.typing_at
           FROM chat_members m JOIN employees e ON e.id = m.employee_id
           WHERE m.channel_id = ? AND m.employee_id <> ? AND m.typing_at IS NOT NULL""",
        (channel_id, me_id),
    ).fetchall()
    names = [row["full_name"] for row in rows if _seconds_since(row["typing_at"]) <= TYPING_SECONDS]
    return names[:3]


def list_messages(
    conn: sqlite3.Connection,
    channel_id: int,
    me: dict[str, Any],
    *,
    after_id: int = 0,
    before_id: int = 0,
    around_id: int = 0,
    limit: int = 50,
    query: str = "",
) -> dict[str, Any]:
    _require_membership(conn, channel_id, me["id"])
    limit = max(1, min(limit, 100))
    conditions = ["m.channel_id = ?"]
    params: list[Any] = [channel_id]
    has_more_before = False
    has_more_after = False

    if query.strip():
        conditions.append("m.deleted_at IS NULL")
        conditions.append("m.body LIKE ? ESCAPE '\\'")
        params.append(_like(query.strip()))
        if before_id:
            conditions.append("m.id < ?")
            params.append(before_id)
        rows = conn.execute(
            MESSAGE_SELECT + " WHERE " + " AND ".join(conditions) + " ORDER BY m.id DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more_before = len(rows) > limit
        rows = list(reversed(rows[:limit]))
    elif after_id:
        conditions.append("m.id > ?")
        params.append(after_id)
        rows = conn.execute(
            MESSAGE_SELECT + " WHERE " + " AND ".join(conditions) + " ORDER BY m.id ASC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more_after = len(rows) > limit
        rows = rows[:limit]
    elif around_id:
        half = max(1, limit // 2)
        older = conn.execute(
            MESSAGE_SELECT
            + " WHERE "
            + " AND ".join(conditions + ["m.id <= ?"])
            + " ORDER BY m.id DESC LIMIT ?",
            (*params, around_id, half + 1),
        ).fetchall()
        has_more_before = len(older) > half
        older = list(reversed(older[:half]))
        newer_conditions = conditions + ["m.id > ?"]
        newer = conn.execute(
            MESSAGE_SELECT
            + " WHERE "
            + " AND ".join(newer_conditions)
            + " ORDER BY m.id ASC LIMIT ?",
            (*params, around_id, limit - half + 1),
        ).fetchall()
        has_more_after = len(newer) > limit - half
        rows = older + newer[: limit - half]
    else:
        if before_id:
            conditions.append("m.id < ?")
            params.append(before_id)
        rows = conn.execute(
            MESSAGE_SELECT + " WHERE " + " AND ".join(conditions) + " ORDER BY m.id DESC LIMIT ?",
            (*params, limit + 1),
        ).fetchall()
        has_more_before = len(rows) > limit
        rows = list(reversed(rows[:limit]))

    return {
        "messages": [_message(row) for row in rows],
        "read_up_to": _read_up_to(conn, channel_id, me["id"]),
        "typing": typing_names(conn, channel_id, me["id"]),
        "has_more": has_more_before,
        "has_newer": has_more_after,
    }


def _fetch_message(conn: sqlite3.Connection, message_id: int) -> dict[str, Any] | None:
    row = conn.execute(MESSAGE_SELECT + " WHERE m.id = ?", (message_id,)).fetchone()
    return _message(row) if row else None


def default_channel_id(conn: sqlite3.Connection, slug: str = "general") -> int | None:
    row = conn.execute("SELECT id FROM chat_channels WHERE slug = ?", (slug,)).fetchone()
    return int(row["id"]) if row else None


def _send_system(conn: sqlite3.Connection, channel_id: int, body: str) -> int:
    cursor = conn.execute(
        """INSERT INTO chat_messages (channel_id, sender_id, kind, body, mentions, created_at)
           VALUES (?, NULL, 'system', ?, '[]', ?)""",
        (channel_id, body[:500], utc_now()),
    )
    return int(cursor.lastrowid)


def send_message(
    conn: sqlite3.Connection,
    channel_id: int,
    me: dict[str, Any],
    body: str,
    reply_to: int | None = None,
    mentions: list[int] | None = None,
) -> dict[str, Any]:
    _require_membership(conn, channel_id, me["id"])
    text = (body or "").strip()
    if not text:
        raise ChatError("Сообщение не может быть пустым", 422)
    if len(text) > settings.chat_message_max_chars:
        raise ChatError(
            f"Сообщение длиннее {settings.chat_message_max_chars} символов", 422
        )

    reply_id = None
    if reply_to:
        reply = conn.execute(
            "SELECT id FROM chat_messages WHERE id = ? AND channel_id = ?",
            (int(reply_to), channel_id),
        ).fetchone()
        if not reply:
            raise ChatError("Сообщение для ответа не найдено", 422)
        reply_id = int(reply["id"])

    allowed = {member["id"] for member in _members(conn, channel_id)}
    clean_mentions = []
    for value in mentions or []:
        try:
            employee_id = int(value)
        except (TypeError, ValueError):
            continue
        if employee_id in allowed and employee_id not in clean_mentions:
            clean_mentions.append(employee_id)

    cursor = conn.execute(
        """INSERT INTO chat_messages
           (channel_id, sender_id, kind, body, reply_to, mentions, created_at)
           VALUES (?, ?, 'text', ?, ?, ?, ?)""",
        (channel_id, me["id"], text, reply_id, json.dumps(clean_mentions), utc_now()),
    )
    message_id = int(cursor.lastrowid)
    conn.execute(
        "UPDATE chat_members SET last_read_id = ?, typing_at = NULL WHERE channel_id = ? AND employee_id = ?",
        (message_id, channel_id, me["id"]),
    )
    touch_presence(conn, me["id"])
    conn.commit()
    message = _fetch_message(conn, message_id)
    if not message:
        raise ChatError("Не удалось сохранить сообщение", 500)
    return message


def edit_message(
    conn: sqlite3.Connection, message_id: int, me: dict[str, Any], body: str
) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    if not row or row["deleted_at"]:
        raise ChatError("Сообщение не найдено", 404)
    if row["kind"] != "text":
        raise ChatError("Системное сообщение нельзя изменить", 403)
    if row["sender_id"] != me["id"] and me.get("role") != "admin":
        raise ChatError("Изменить можно только своё сообщение", 403)
    text = (body or "").strip()
    if not text:
        raise ChatError("Сообщение не может быть пустым", 422)
    if len(text) > settings.chat_message_max_chars:
        raise ChatError(f"Сообщение длиннее {settings.chat_message_max_chars} символов", 422)
    _require_membership(conn, row["channel_id"], me["id"])
    conn.execute(
        "UPDATE chat_messages SET body = ?, edited_at = ? WHERE id = ?",
        (text, utc_now(), message_id),
    )
    conn.commit()
    message = _fetch_message(conn, message_id)
    if not message:
        raise ChatError("Сообщение не найдено", 404)
    return message


def delete_message(conn: sqlite3.Connection, message_id: int, me: dict[str, Any]) -> dict[str, Any]:
    row = conn.execute("SELECT * FROM chat_messages WHERE id = ?", (message_id,)).fetchone()
    if not row or row["deleted_at"]:
        raise ChatError("Сообщение не найдено", 404)
    membership = _require_membership(conn, row["channel_id"], me["id"])
    is_moderator = membership["role"] == "owner" or me.get("role") == "admin"
    if row["sender_id"] != me["id"] and not is_moderator:
        raise ChatError("Удалить можно только своё сообщение", 403)
    if row["kind"] == "system":
        raise ChatError("Системное сообщение нельзя удалить", 403)

    attachment = conn.execute(
        "SELECT * FROM chat_attachments WHERE message_id = ?", (message_id,)
    ).fetchone()
    conn.execute(
        "UPDATE chat_messages SET body = '', deleted_at = ?, mentions = '[]' WHERE id = ?",
        (utc_now(), message_id),
    )
    if attachment:
        conn.execute("DELETE FROM chat_attachments WHERE id = ?", (attachment["id"],))
        path = Path(settings.chat_upload_dir) / attachment["stored_name"]
        path.unlink(missing_ok=True)
    conn.commit()
    return {"deleted": True, "id": message_id}


def mark_read(
    conn: sqlite3.Connection, channel_id: int, me: dict[str, Any], message_id: int
) -> dict[str, Any]:
    _require_membership(conn, channel_id, me["id"])
    last_id = conn.execute(
        "SELECT COALESCE(MAX(id), 0) AS last FROM chat_messages WHERE channel_id = ?",
        (channel_id,),
    ).fetchone()["last"]
    target = max(0, min(int(message_id), int(last_id)))
    conn.execute(
        """UPDATE chat_members SET last_read_id = MAX(last_read_id, ?)
           WHERE channel_id = ? AND employee_id = ?""",
        (target, channel_id, me["id"]),
    )
    touch_presence(conn, me["id"])
    conn.commit()
    return {"last_read_id": target, "unread": 0}


def set_typing(conn: sqlite3.Connection, channel_id: int, me: dict[str, Any]) -> dict[str, Any]:
    _require_membership(conn, channel_id, me["id"])
    conn.execute(
        "UPDATE chat_members SET typing_at = ? WHERE channel_id = ? AND employee_id = ?",
        (utc_now(), channel_id, me["id"]),
    )
    touch_presence(conn, me["id"])
    conn.commit()
    return {"ok": True, "typing": typing_names(conn, channel_id, me["id"])}


# --------------------------------------------------------------------------- #
# Поиск
# --------------------------------------------------------------------------- #

def _channel_title(conn: sqlite3.Connection, channel_id: int, me_id: int) -> tuple[str, str]:
    channel = conn.execute("SELECT * FROM chat_channels WHERE id = ?", (channel_id,)).fetchone()
    if not channel:
        return "Диалог", "direct"
    members = _members(conn, channel_id)
    return _title_for(channel, members, me_id), channel["kind"]


def search_messages(
    conn: sqlite3.Connection, me: dict[str, Any], query: str, limit: int = 30
) -> list[dict[str, Any]]:
    text = (query or "").strip()
    if len(text) < 2:
        return []
    limit = max(1, min(limit, 60))
    rows = conn.execute(
        """SELECT m.id, m.channel_id, m.body, m.created_at, e.full_name AS sender_name,
                  c.kind AS channel_kind, c.title AS channel_title, c.slug
           FROM chat_messages m
           JOIN chat_channels c ON c.id = m.channel_id
           JOIN chat_members mm ON mm.channel_id = m.channel_id AND mm.employee_id = ?
           LEFT JOIN employees e ON e.id = m.sender_id
           WHERE m.deleted_at IS NULL AND m.body LIKE ? ESCAPE '\\'
           ORDER BY m.id DESC LIMIT ?""",
        (me["id"], _like(text), limit),
    ).fetchall()
    cache: dict[int, tuple[str, str]] = {}
    results = []
    for row in rows:
        if row["channel_id"] not in cache:
            cache[row["channel_id"]] = _channel_title(conn, row["channel_id"], me["id"])
        title, kind = cache[row["channel_id"]]
        results.append(
            {
                "message_id": row["id"],
                "channel_id": row["channel_id"],
                "channel_title": title,
                "channel_kind": kind,
                "sender_name": row["sender_name"] or "Система",
                "snippet": _snippet(row["body"], text),
                "created_at": row["created_at"],
            }
        )
    return results


# --------------------------------------------------------------------------- #
# Вложения
# --------------------------------------------------------------------------- #

def save_attachment(
    conn: sqlite3.Connection,
    channel_id: int,
    me: dict[str, Any],
    filename: str,
    mime: str,
    data: bytes,
    caption: str = "",
    reply_to: int | None = None,
) -> dict[str, Any]:
    _require_membership(conn, channel_id, me["id"])
    max_bytes = settings.chat_max_upload_mb * 1024 * 1024
    if not data:
        raise ChatError("Файл пустой", 422)
    if len(data) > max_bytes:
        raise ChatError(f"Файл больше {settings.chat_max_upload_mb} МБ", 413)

    safe_name = Path(filename or "файл").name
    safe_name = re.sub(r"[\x00-\x1f\x7f]", "", safe_name).strip()[:160] or "файл"
    suffix = Path(safe_name).suffix.lower()
    if suffix in BLOCKED_EXTENSIONS:
        raise ChatError("Такие файлы нельзя отправлять из соображений безопасности", 415)

    text = (caption or "").strip()
    if len(text) > settings.chat_message_max_chars:
        raise ChatError(f"Подпись длиннее {settings.chat_message_max_chars} символов", 422)

    reply_id = None
    if reply_to:
        reply = conn.execute(
            "SELECT id FROM chat_messages WHERE id = ? AND channel_id = ?",
            (int(reply_to), channel_id),
        ).fetchone()
        if reply:
            reply_id = int(reply["id"])

    upload_dir = Path(settings.chat_upload_dir)
    upload_dir.mkdir(parents=True, exist_ok=True)
    stored_name = uuid.uuid4().hex + (suffix if len(suffix) <= 12 else "")
    path = upload_dir / stored_name
    path.write_bytes(data)

    clean_mime = (mime or "").split(";")[0].strip().lower()
    if not re.fullmatch(r"[a-z0-9.+-]+/[a-z0-9.+-]+", clean_mime or ""):
        clean_mime = mimetypes.guess_type(safe_name)[0] or "application/octet-stream"

    try:
        cursor = conn.execute(
            """INSERT INTO chat_messages
               (channel_id, sender_id, kind, body, reply_to, mentions, created_at)
               VALUES (?, ?, 'text', ?, ?, '[]', ?)""",
            (channel_id, me["id"], text, reply_id, utc_now()),
        )
        message_id = int(cursor.lastrowid)
        conn.execute(
            """INSERT INTO chat_attachments (message_id, filename, stored_name, mime, size, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message_id, safe_name, stored_name, clean_mime, len(data), utc_now()),
        )
        conn.execute(
            "UPDATE chat_members SET last_read_id = ?, typing_at = NULL WHERE channel_id = ? AND employee_id = ?",
            (message_id, channel_id, me["id"]),
        )
        touch_presence(conn, me["id"])
        conn.commit()
    except Exception:
        conn.rollback()
        path.unlink(missing_ok=True)
        raise

    message = _fetch_message(conn, message_id)
    if not message:
        raise ChatError("Не удалось сохранить файл", 500)
    return message


def attachment_for_download(
    conn: sqlite3.Connection, attachment_id: int, me: dict[str, Any]
) -> dict[str, Any]:
    row = conn.execute(
        """SELECT a.*, m.channel_id FROM chat_attachments a
           JOIN chat_messages m ON m.id = a.message_id
           WHERE a.id = ?""",
        (attachment_id,),
    ).fetchone()
    if not row:
        raise ChatError("Файл не найден", 404)
    _require_membership(conn, row["channel_id"], me["id"])
    path = Path(settings.chat_upload_dir) / row["stored_name"]
    if not path.exists():
        raise ChatError("Файл не найден", 404)
    return {
        "path": path,
        "filename": row["filename"],
        "mime": row["mime"],
        "size": row["size"],
        "inline": row["mime"] in INLINE_IMAGE_MIME,
    }

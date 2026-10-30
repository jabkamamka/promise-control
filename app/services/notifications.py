"""Уведомления сотрудникам: в интерфейсе и на почту.

Правила простые и объяснимые:

* **скоро срок** — задача взята в работу, до срока осталось не больше
  ``REMINDER_MINUTES_BEFORE`` минут;
* **срок истёк** — задача взята в работу, срок прошёл.

Каждое уведомление создаётся один раз: уникальный индекс
``(employee_id, kind, task_id)`` не даёт продублировать его ни при следующем
проходе планировщика, ни после перезапуска сервиса. Письмо отправляется сразу
после создания записи, а результат (``sent``/``file``/``failed``) сохраняется
в самой записи — видно, что и куда ушло.
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any
from zoneinfo import ZoneInfo

from ..config import settings
from ..utils import parse_iso, utc_now
from . import mailer

DEFAULT_LEAD_MINUTES = 60

KIND_DEADLINE = "deadline_soon"
KIND_OVERDUE = "overdue"

MONTHS = (
    "января", "февраля", "марта", "апреля", "мая", "июня",
    "июля", "августа", "сентября", "октября", "ноября", "декабря",
)


# --------------------------------------------------------------------------- #
# Чтение
# --------------------------------------------------------------------------- #

def list_for(
    conn: sqlite3.Connection,
    employee_id: int,
    limit: int = 20,
    unread_only: bool = False,
) -> list[dict[str, Any]]:
    sql = """SELECT id, task_id, kind, title, body, link, read_at, email_status, created_at
             FROM notifications
             WHERE employee_id = ?"""
    params: list[Any] = [employee_id]
    if unread_only:
        sql += " AND read_at IS NULL"
    sql += " ORDER BY id DESC LIMIT ?"
    params.append(limit)
    return [dict(row) for row in conn.execute(sql, params)]


def unread_count(conn: sqlite3.Connection, employee_id: int) -> int:
    row = conn.execute(
        "SELECT COUNT(*) AS c FROM notifications WHERE employee_id = ? AND read_at IS NULL",
        (employee_id,),
    ).fetchone()
    return int(row["c"] if row else 0)


def mark_read(conn: sqlite3.Connection, employee_id: int, ids: list[int] | None = None) -> int:
    now = utc_now()
    if ids:
        placeholders = ",".join("?" for _ in ids)
        cur = conn.execute(
            f"""UPDATE notifications SET read_at = ?
                WHERE employee_id = ? AND read_at IS NULL AND id IN ({placeholders})""",
            [now, employee_id, *ids],
        )
    else:
        cur = conn.execute(
            "UPDATE notifications SET read_at = ? WHERE employee_id = ? AND read_at IS NULL",
            (now, employee_id),
        )
    conn.commit()
    return cur.rowcount


# --------------------------------------------------------------------------- #
# Создание
# --------------------------------------------------------------------------- #

def create(
    conn: sqlite3.Connection,
    employee_id: int,
    kind: str,
    title: str,
    body: str = "",
    task_id: str | None = None,
    link: str = "/",
) -> dict[str, Any] | None:
    """Создаёт уведомление. Возвращает None, если такое уже было."""
    cur = conn.execute(
        """INSERT OR IGNORE INTO notifications
           (employee_id, task_id, kind, title, body, link, created_at)
           VALUES (?,?,?,?,?,?,?)""",
        (employee_id, task_id, kind, title, body, link, utc_now()),
    )
    conn.commit()
    if cur.rowcount == 0:
        return None
    row = conn.execute("SELECT * FROM notifications WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row) if row else None


def _store_email_result(conn: sqlite3.Connection, notification_id: int, result: mailer.MailResult) -> None:
    conn.execute(
        """UPDATE notifications
           SET email_status = ?, email_error = ?, email_sent_at = ?
           WHERE id = ?""",
        (
            result.status,
            None if result.status in ("sent", "file") else result.detail,
            utc_now() if result.status in ("sent", "file") else None,
            notification_id,
        ),
    )
    conn.commit()


def deliver(
    conn: sqlite3.Connection,
    notification: dict[str, Any],
    email: str | None,
    employee_name: str | None,
) -> mailer.MailResult:
    """Отправляет письмо по уже созданному уведомлению и записывает результат."""
    if not email:
        result = mailer.MailResult("failed", "у сотрудника не указан email")
    else:
        text = _email_text(notification, employee_name)
        subject = f"[Контроль обещаний] {notification['title']}"
        result = mailer.send(email, subject, text, html=_email_html(notification, employee_name))
    _store_email_result(conn, int(notification["id"]), result)
    return result


# --------------------------------------------------------------------------- #
# Тексты
# --------------------------------------------------------------------------- #

def format_due(due_at: str | None) -> str:
    moment = parse_iso(due_at)
    if not moment:
        return "—"
    local = moment.astimezone(ZoneInfo(settings.timezone))
    return f"{local.day} {MONTHS[local.month - 1]}, {local:%H:%M}"


def minutes_left(due_at: str | None, now: dt.datetime | None = None) -> int | None:
    moment = parse_iso(due_at)
    if not moment:
        return None
    base = now or dt.datetime.now(dt.timezone.utc)
    return int((moment - base).total_seconds() // 60)


def human_minutes(value: int) -> str:
    if value <= 0:
        return "меньше минуты"
    if value < 60:
        return f"{value} мин"
    hours, minutes = divmod(value, 60)
    if minutes:
        return f"{hours} ч {minutes} мин"
    return f"{hours} ч"


def _email_text(notification: dict[str, Any], employee_name: str | None) -> str:
    name = (employee_name or "коллега").split()[0] if employee_name else "коллега"
    title = notification["title"]
    body = notification["body"] or ""
    link = f"{settings.public_base_url.rstrip('/')}{notification['link']}"
    return (
        f"Здравствуйте, {name}!\n\n"
        f"{title}\n\n"
        f"{body}\n\n"
        f"Открыть задачу: {link}\n\n"
        "— Сервис контроля обещаний, UralMicro"
    )


def _email_html(notification: dict[str, Any], employee_name: str | None) -> str:
    name = (employee_name or "коллега").split()[0] if employee_name else "коллега"
    body = (notification["body"] or "").replace("\n", "<br />")
    link = f"{settings.public_base_url.rstrip('/')}{notification['link']}"
    return f"""<!doctype html>
<html lang="ru"><body style="margin:0;padding:24px;background:#f2eee5;
 font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;color:#16150f">
  <div style="max-width:520px;margin:0 auto;background:#fffdf8;border:1px solid #e2dbcc;
   border-radius:14px;padding:24px">
    <p style="margin:0 0 16px;font-size:13px;letter-spacing:.08em;text-transform:uppercase;color:#8a8474">
      Контроль обещаний · UralMicro</p>
    <p style="margin:0 0 12px">Здравствуйте, {name}!</p>
    <p style="margin:0 0 12px;font-size:17px;font-weight:600">
      {notification['title']}</p>
    <p style="margin:0 0 18px;color:#3d3a32;line-height:1.5">{body}</p>
    <p style="margin:0"><a href="{link}"
      style="display:inline-block;padding:11px 18px;background:#16150f;color:#fffdf8;
      border-radius:10px;text-decoration:none">Открыть задачу</a></p>
  </div>
</body></html>"""


# --------------------------------------------------------------------------- #
# Планировщик
# --------------------------------------------------------------------------- #

def pending(conn: sqlite3.Connection, limit: int = 200) -> list[dict[str, Any]]:
    """Задачи, которым пора напомнить (ещё без уведомления)."""
    rows = conn.execute(
        """SELECT t.id, t.title, t.object, t.due_at, t.due_hint, t.quote, t.call_id,
                  t.assignee_id, t.assignee_name, e.email, e.full_name
           FROM tasks t
           JOIN employees e ON e.id = t.assignee_id
           WHERE t.status = 'in_progress'
             AND t.assignee_id IS NOT NULL
             AND e.is_active = 1
           ORDER BY t.due_at
           LIMIT ?""",
        (limit,),
    ).fetchall()
    return [dict(row) for row in rows]


def build(
    conn: sqlite3.Connection, task: dict[str, Any], now: dt.datetime | None = None
) -> tuple[str, str, str, str] | None:
    """Определяет, какое уведомление нужно по задаче. None — пока не нужно."""
    base = now or dt.datetime.now(dt.timezone.utc)
    left = minutes_left(task["due_at"], base)
    if left is None:
        return None

    due = format_due(task["due_at"])
    quote = (task.get("quote") or "").strip()
    lines = [f"Срок: {due}"]
    if quote:
        lines.append(f"Из разговора: «{quote}»")
    if task.get("object"):
        lines.append(f"Объект: {task['object']}")
    body = "\n".join(lines)
    link = f"/?task={task['id']}"

    if left < 0:
        return KIND_OVERDUE, f"Срок истёк: «{task['title']}»", body, link
    if settings.reminder_enabled and left <= settings.reminder_minutes_before:
        return (
            KIND_DEADLINE,
            f"Срок через {human_minutes(left)}: «{task['title']}»",
            body,
            link,
        )
    return None


def run_cycle(
    conn: sqlite3.Connection,
    now: dt.datetime | None = None,
    limit: int = 200,
) -> dict[str, Any]:
    """Один проход: создать уведомления и отправить письма.

    Возвращает счётчики — их удобно показывать в /health и в тестах.
    """
    base = now or dt.datetime.now(dt.timezone.utc)
    created: list[dict[str, Any]] = []
    skipped = 0

    for task in pending(conn, limit):
        plan = build(conn, task, base)
        if not plan:
            continue
        kind, title, body, link = plan
        notification = create(conn, task["assignee_id"], kind, title, body, task["id"], link)
        if not notification:
            skipped += 1
            continue
        result = deliver(conn, notification, task["email"], task["full_name"] or task["assignee_name"])
        notification["email_status"] = result.status
        created.append(
            {
                "id": notification["id"],
                "employee_id": notification["employee_id"],
                "task_id": notification["task_id"],
                "kind": notification["kind"],
                "title": notification["title"],
                "email": task["email"],
                "email_status": result.status,
                "email_detail": result.detail,
            }
        )

    emails = sum(1 for item in created if item["email_status"] in ("sent", "file"))
    return {
        "checked_at": base.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "created": len(created),
        "already": skipped,
        "emails": emails,
        "items": created,
    }

"""Задачи: создание, выборка, смена статусов, просрочка, статистика."""
from __future__ import annotations

import json
import sqlite3
import uuid
from datetime import datetime
from typing import Any, Iterable

from ..utils import normalize_text, parse_iso, slugify, utc_now
from .taxonomy import PromiseType

STATUSES = ("created", "in_progress", "done")
STATUS_TITLES = {
    "created": "Создана",
    "in_progress": "В работе",
    "done": "Выполнена",
    "overdue": "Просрочена",
    "not_fulfilled": "Не выполнена",
}

#: Разрешённые переходы. Просрочка — вычисляемый статус, а не хранимый.
TRANSITIONS: dict[str, set[str]] = {
    "created": {"in_progress"},
    "in_progress": {"done", "created"},
    "done": {"in_progress"},
}

SORT_FIELDS = {"due_at", "created_at", "updated_at", "status", "confidence", "operator_id"}


class TaskError(Exception):
    """Ошибка бизнес-правила (невалидный переход и т.п.)."""


# --------------------------------------------------------------------------- #
# Типы обещаний
# --------------------------------------------------------------------------- #

def load_types(conn: sqlite3.Connection) -> list[PromiseType]:
    rows = conn.execute("SELECT * FROM promise_types ORDER BY priority DESC, code").fetchall()
    return [
        PromiseType(
            code=r["code"],
            title=r["title"],
            description=r["description"],
            keywords=json.loads(r["keywords"] or "[]"),
            examples=json.loads(r["examples"] or "[]"),
            is_builtin=bool(r["is_builtin"]),
            priority=r["priority"],
        )
        for r in rows
    ]


def list_types(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    rows = conn.execute(
        """SELECT t.*, (SELECT COUNT(*) FROM tasks WHERE tasks.promise_type = t.code) AS tasks_count
           FROM promise_types t ORDER BY t.is_builtin DESC, t.priority DESC, t.code"""
    ).fetchall()
    out = []
    for r in rows:
        out.append(
            {
                "code": r["code"],
                "title": r["title"],
                "description": r["description"],
                "keywords": json.loads(r["keywords"] or "[]"),
                "examples": json.loads(r["examples"] or "[]"),
                "is_builtin": bool(r["is_builtin"]),
                "priority": r["priority"],
                "created_at": r["created_at"],
                "updated_at": r["updated_at"],
                "tasks_count": r["tasks_count"],
            }
        )
    return out


def create_type(conn: sqlite3.Connection, data: dict[str, Any]) -> dict[str, Any]:
    title = (data.get("title") or "").strip()
    code = (data.get("code") or "").strip() or slugify(title, fallback="custom")
    if conn.execute("SELECT 1 FROM promise_types WHERE code = ?", (code,)).fetchone():
        raise TaskError(f"Тип с кодом «{code}» уже существует")
    now = utc_now()
    priority = data.get("priority") or 78
    conn.execute(
        """INSERT INTO promise_types (code, title, description, keywords, examples,
                                     is_builtin, priority, created_at, updated_at)
           VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)""",
        (
            code,
            title,
            (data.get("description") or "").strip(),
            json.dumps([k.strip() for k in data.get("keywords") or [] if k and k.strip()], ensure_ascii=False),
            json.dumps([e.strip() for e in data.get("examples") or [] if e and e.strip()], ensure_ascii=False),
            int(priority),
            now,
            now,
        ),
    )
    conn.commit()
    return next(t for t in list_types(conn) if t["code"] == code)


def delete_type(conn: sqlite3.Connection, code: str) -> None:
    row = conn.execute("SELECT is_builtin FROM promise_types WHERE code = ?", (code,)).fetchone()
    if not row:
        raise KeyError(code)
    if row["is_builtin"]:
        raise TaskError("Встроенный тип удалить нельзя")
    used = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE promise_type = ?", (code,)).fetchone()["c"]
    if used:
        raise TaskError(f"По типу уже создано задач: {used}. Удаление запрещено")
    conn.execute("DELETE FROM promise_types WHERE code = ?", (code,))
    conn.commit()


# --------------------------------------------------------------------------- #
# Просрочка
# --------------------------------------------------------------------------- #

def mark_overdue(conn: sqlite3.Connection) -> int:
    """Проставляет просрочку задачам с истёкшим сроком (идемпотентно)."""
    now = utc_now()
    rows = conn.execute(
        """SELECT id FROM tasks
           WHERE status != 'done' AND verification_status IS NULL
             AND due_at < ? AND overdue_marked_at IS NULL""",
        (now,),
    ).fetchall()
    for row in rows:
        conn.execute("UPDATE tasks SET overdue_marked_at = ? WHERE id = ?", (now, row["id"]))
        conn.execute(
            "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
            (row["id"], "overdue", None, "overdue", "Срок истёк, задача не закрыта", now),
        )
    if rows:
        conn.commit()
    return len(rows)


def is_overdue(task: dict[str, Any], now: datetime | None = None) -> bool:
    if task["status"] == "done" or task.get("verification_status") == "refuted":
        return False
    due = parse_iso(task["due_at"])
    if not due:
        return False
    return due < (now or datetime.now(due.tzinfo))


def effective_status(task: dict[str, Any]) -> str:
    if task["status"] == "done":
        return "done"
    if task.get("verification_status") == "refuted":
        return "not_fulfilled"
    return "overdue" if is_overdue(task) else task["status"]


# --------------------------------------------------------------------------- #
# Чтение задач
# --------------------------------------------------------------------------- #

_TASK_SELECT = """
SELECT t.*, c.started_at AS call_started_at, c.ended_at AS call_ended_at,
       c.client_phone AS call_client_phone, p.title AS promise_type_title
FROM tasks t
JOIN calls c ON c.id = t.call_id
LEFT JOIN promise_types p ON p.code = t.promise_type
"""


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    task = dict(row)
    task["actions"] = json.loads(task.get("actions") or "[]")
    task["secondary_types"] = json.loads(task.pop("secondary_types", "[]") or "[]")
    task["client_phone"] = task.get("call_client_phone") or task.get("client_phone")
    task["effective_status"] = effective_status(task)
    task["is_overdue"] = task["effective_status"] == "overdue"
    if task.get("confidence") is not None:
        task["confidence"] = float(task["confidence"])
    return task


def get_task(conn: sqlite3.Connection, task_id: str) -> dict[str, Any] | None:
    row = conn.execute(_TASK_SELECT + " WHERE t.id = ?", (task_id,)).fetchone()
    return _row_to_task(row) if row else None


def _build_filters(
    status: str | None,
    promise_type: str | None,
    operator_id: int | None,
    call_id: str | None,
    due_before: str | None,
    due_after: str | None,
    q: str | None,
    verification: str | None = None,
    assignee_id: int | None = None,
) -> tuple[str, list[Any]]:
    clauses: list[str] = []
    params: list[Any] = []

    if status:
        wanted = [s.strip() for s in status.split(",") if s.strip()]
        now = utc_now()
        parts: list[str] = []
        local_params: list[Any] = []
        for state in wanted:
            if state in ("created", "in_progress"):
                # просроченная задача не должна выглядеть как «Создана»;
                # опровергнутая обещанием не считается
                parts.append(
                    "(t.status = ? AND t.due_at >= ? AND "
                    "(t.verification_status IS NULL OR t.verification_status != 'refuted'))"
                )
                local_params.extend([state, now])
            elif state == "done":
                parts.append("t.status = ?")
                local_params.append("done")
            elif state == "overdue":
                parts.append(
                    "(t.status != 'done' AND t.due_at < ? AND "
                    "(t.verification_status IS NULL OR t.verification_status != 'refuted'))"
                )
                local_params.append(now)
            elif state == "not_fulfilled":
                parts.append("(t.status != 'done' AND t.verification_status = 'refuted')")
        if parts:
            clauses.append("(" + " OR ".join(parts) + ")")
            params.extend(local_params)
    if verification:
        wanted = [s.strip() for s in verification.split(",") if s.strip()]
        parts = []
        local_params = []
        for state in wanted:
            if state == "pending":
                parts.append("t.verification_status IS NULL")
            elif state in ("confirmed", "refuted"):
                parts.append("t.verification_status = ?")
                local_params.append(state)
        if parts:
            clauses.append("(" + " OR ".join(parts) + ")")
            params.extend(local_params)
    if assignee_id is not None:
        clauses.append("t.assignee_id = ?")
        params.append(assignee_id)
    if promise_type:
        clauses.append("t.promise_type = ?")
        params.append(promise_type)
    if operator_id is not None:
        clauses.append("t.operator_id = ?")
        params.append(operator_id)
    if call_id:
        clauses.append("t.call_id = ?")
        params.append(call_id)
    if due_before:
        clauses.append("t.due_at <= ?")
        params.append(due_before)
    if due_after:
        clauses.append("t.due_at >= ?")
        params.append(due_after)
    if q:
        clauses.append("t.search_text LIKE ?")
        params.append(f"%{normalize_text(q)}%")
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def list_tasks(
    conn: sqlite3.Connection,
    *,
    status: str | None = None,
    promise_type: str | None = None,
    operator_id: int | None = None,
    call_id: str | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    q: str | None = None,
    verification: str | None = None,
    assignee_id: int | None = None,
    sort: str = "due_at",
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[dict[str, Any]], int]:
    where, params = _build_filters(
        status, promise_type, operator_id, call_id, due_before, due_after, q, verification, assignee_id
    )

    field = sort.lstrip("-")
    direction = "DESC" if sort.startswith("-") else "ASC"
    if field not in SORT_FIELDS:
        field, direction = "due_at", "ASC"

    total = conn.execute(f"SELECT COUNT(*) AS c FROM tasks t{where}", params).fetchone()["c"]
    rows = conn.execute(
        _TASK_SELECT + where + f" ORDER BY t.{field} {direction}, t.created_at ASC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    return [_row_to_task(r) for r in rows], total


# --------------------------------------------------------------------------- #
# Запись задач
# --------------------------------------------------------------------------- #

def new_task_id() -> str:
    return "tsk_" + uuid.uuid4().hex[:12]


def insert_task(conn: sqlite3.Connection, task: dict[str, Any]) -> bool:
    """Вставляет задачу. False — если такой dedupe_key уже был (дубль)."""
    now = utc_now()
    cur = conn.execute(
        """INSERT INTO tasks (id, call_id, operator_id, promise_type, title, object, quote,
                              transcript_index, actions, secondary_types, due_at, due_hint, deadline_source,
                              status, confidence, matched_by, created_at, updated_at, dedupe_key, search_text)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(dedupe_key) DO NOTHING""",
        (
            task["id"],
            task["call_id"],
            task.get("operator_id"),
            task["promise_type"],
            task["title"],
            task.get("object", ""),
            task["quote"],
            task["transcript_index"],
            json.dumps(task.get("actions", []), ensure_ascii=False),
            json.dumps(task.get("secondary_types", []), ensure_ascii=False),
            task["due_at"],
            task.get("due_hint", ""),
            task.get("deadline_source", "default_24h"),
            "created",
            task.get("confidence", 0.5),
            task.get("matched_by", "rule"),
            now,
            now,
            task["dedupe_key"],
            normalize_text(
                " ".join(
                    [
                        task["title"],
                        task.get("object", ""),
                        task["quote"],
                        " ".join(task.get("actions", [])),
                    ]
                )
            ),
        ),
    )
    created = cur.rowcount > 0
    if created:
        conn.execute(
            "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
            (task["id"], "created", None, "created", "Задача создана по звонку", now),
        )
    return created


def update_status(
    conn: sqlite3.Connection,
    task_id: str,
    new_status: str,
    comment: str | None = None,
    employee: dict[str, Any] | None = None,
) -> dict[str, Any]:
    task = get_task(conn, task_id)
    if not task:
        raise KeyError(task_id)
    if new_status not in STATUSES:
        raise TaskError(f"Неизвестный статус «{new_status}»")
    current = task["status"]
    if new_status == current:
        return task
    if new_status not in TRANSITIONS.get(current, set()):
        allowed = ", ".join(sorted(TRANSITIONS.get(current, set()))) or "нет"
        raise TaskError(
            f"Переход «{STATUS_TITLES.get(current, current)}» → «{STATUS_TITLES.get(new_status, new_status)}» "
            f"запрещён. Доступно: {allowed}"
        )
    now = utc_now()
    closed = now if new_status == "done" else None
    conn.execute(
        "UPDATE tasks SET status = ?, updated_at = ?, closed_at = ? WHERE id = ?",
        (new_status, now, closed, task_id),
    )
    # взял в работу — фиксируем сотрудника, если задача ещё ничья
    if new_status == "in_progress" and employee and not task.get("assignee_id"):
        conn.execute(
            "UPDATE tasks SET assignee_id = ?, assignee_name = ?, taken_at = ? WHERE id = ?",
            (employee["id"], employee["full_name"], now, task_id),
        )
        conn.execute(
            "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
            (task_id, "taken", None, None, f"Взял в работу: {employee['full_name']}", now),
        )
    conn.execute(
        "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
        (task_id, "status_changed", current, new_status, comment, now),
    )
    conn.commit()
    return get_task(conn, task_id)  # type: ignore[return-value]


def list_events(conn: sqlite3.Connection, task_id: str) -> list[dict[str, Any]]:
    rows = conn.execute("SELECT * FROM task_events WHERE task_id = ? ORDER BY id", (task_id,)).fetchall()
    return [dict(r) for r in rows]


def assign_task(conn: sqlite3.Connection, task_id: str, employee: dict[str, Any]) -> dict[str, Any]:
    """Сотрудник берёт задачу в работу. Задача становится «В работе», за ним закрепляется."""
    task = get_task(conn, task_id)
    if not task:
        raise KeyError(task_id)
    if task["status"] == "done":
        raise TaskError("Задача уже выполнена — верните её в работу, если нужно переделать")

    current_assignee = task.get("assignee_id")
    if current_assignee and current_assignee != employee["id"]:
        raise TaskError(f"Задачу уже взял {task.get('assignee_name') or 'другой сотрудник'}")

    now = utc_now()
    changed = task["status"] != "in_progress"
    if changed and "in_progress" not in TRANSITIONS.get(task["status"], set()):
        raise TaskError("Эту задачу нельзя взять в работу из текущего статуса")

    conn.execute(
        """UPDATE tasks
           SET status = 'in_progress', assignee_id = ?, assignee_name = ?, taken_at = COALESCE(taken_at, ?),
               updated_at = ?
           WHERE id = ?""",
        (employee["id"], employee["full_name"], now, now, task_id),
    )
    if changed:
        conn.execute(
            "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
            (task_id, "status_changed", task["status"], "in_progress", "Взял в работу", now),
        )
    conn.execute(
        "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
        (task_id, "taken", None, None, f"Исполнитель: {employee['full_name']}", now),
    )
    conn.commit()
    return get_task(conn, task_id)  # type: ignore[return-value]


# --------------------------------------------------------------------------- #
# Статистика
# --------------------------------------------------------------------------- #

def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    mark_overdue(conn)
    calls_total = conn.execute("SELECT COUNT(*) AS c FROM calls").fetchone()["c"]
    tasks_total = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    by_status = {s: 0 for s in STATUSES}
    for row in conn.execute("SELECT status, COUNT(*) AS c FROM tasks GROUP BY status"):
        by_status[row["status"]] = row["c"]
    by_type = {}
    for row in conn.execute("SELECT promise_type, COUNT(*) AS c FROM tasks GROUP BY promise_type"):
        by_type[row["promise_type"]] = row["c"]
    by_verification = {"confirmed": 0, "refuted": 0, "pending": 0}
    for row in conn.execute(
        """SELECT COALESCE(verification_status, 'pending') AS state, COUNT(*) AS c
           FROM tasks GROUP BY state"""
    ):
        by_verification[row["state"]] = row["c"]
    overdue = conn.execute(
        """SELECT COUNT(*) AS c FROM tasks
           WHERE status != 'done' AND due_at < ?
             AND (verification_status IS NULL OR verification_status != 'refuted')""",
        (utc_now(),),
    ).fetchone()["c"]
    today = utc_now()[:10]
    due_today = conn.execute(
        """SELECT COUNT(*) AS c FROM tasks
           WHERE status != 'done' AND due_at >= ? AND due_at < ?
             AND (verification_status IS NULL OR verification_status != 'refuted')""",
        (f"{today}T00:00:00Z", f"{today}T23:59:59Z"),
    ).fetchone()["c"]
    avg = round(tasks_total / calls_total, 2) if calls_total else 0.0
    return {
        "calls_total": calls_total,
        "tasks_total": tasks_total,
        "by_status": by_status,
        "by_type": by_type,
        "by_verification": by_verification,
        "overdue": overdue,
        "not_fulfilled": by_verification["refuted"],
        "due_today": due_today,
        "avg_promises_per_call": avg,
    }

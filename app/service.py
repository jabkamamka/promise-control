"""Бизнес-логика сервиса контроля обещаний."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Any

from . import config, db
from .calls import CallFormatError, ParsedCall, extract_calls, parse_call
from .detector import BUILTIN_TYPES, DetectedPromise, PromiseType, detect_promises

STATUS_LABELS = {
    "created": "Создана",
    "in_progress": "В работе",
    "done": "Выполнена",
    "overdue": "Просрочена",
}
OPEN_STATUSES = ("created", "in_progress")
ALLOWED_TRANSITIONS = {
    "created": {"in_progress", "done"},
    "in_progress": {"done"},
    "overdue": {"in_progress", "done"},
    "done": {"in_progress"},
}


class ServiceError(Exception):
    """Ошибка бизнес-правила; код ответа задаётся в API."""

    def __init__(self, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.status_code = status_code


# ---------------------------------------------------------------- типы обещаний


def seed_types() -> None:
    with db.connect() as conn:
        for ptype in BUILTIN_TYPES:
            conn.execute(
                """INSERT INTO promise_types
                   (code, name, description, examples, keywords, patterns, action, is_builtin, active, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1, ?)
                   ON CONFLICT(code) DO UPDATE SET
                       name = excluded.name,
                       description = excluded.description,
                       examples = excluded.examples,
                       keywords = excluded.keywords,
                       patterns = excluded.patterns,
                       action = excluded.action
                """,
                (
                    ptype.code,
                    ptype.name,
                    ptype.description,
                    json.dumps(ptype.examples, ensure_ascii=False),
                    json.dumps(ptype.keywords, ensure_ascii=False),
                    json.dumps(ptype.patterns, ensure_ascii=False),
                    ptype.action,
                    db.iso(db.utcnow()),
                ),
            )


def row_to_type(row: sqlite3.Row) -> PromiseType:
    return PromiseType(
        code=row["code"],
        name=row["name"],
        description=row["description"],
        action=row["action"] or row["name"],
        patterns=db.loads(row["patterns"], []),
        keywords=db.loads(row["keywords"], []),
        examples=db.loads(row["examples"], []),
        is_builtin=bool(row["is_builtin"]),
    )


def load_types(include_inactive: bool = False) -> list[PromiseType]:
    query = "SELECT * FROM promise_types"
    if not include_inactive:
        query += " WHERE active = 1"
    query += " ORDER BY is_builtin DESC, code"
    with db.connect() as conn:
        return [row_to_type(r) for r in conn.execute(query).fetchall()]


def list_types() -> list[dict[str, Any]]:
    with db.connect() as conn:
        return db.rows_to_dicts(conn.execute(
            "SELECT * FROM promise_types ORDER BY is_builtin DESC, code"
        ).fetchall())


def _slugify(name: str) -> str:
    translit = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
        "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
        "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "c",
        "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
        "я": "ya",
    }
    slug = "".join(translit.get(ch, ch) for ch in name.lower())
    slug = re.sub(r"[^a-z0-9]+", "_", slug).strip("_")
    return slug[:40] or "custom_type"


def create_type(payload: dict[str, Any]) -> dict[str, Any]:
    name = (payload.get("name") or "").strip()
    description = (payload.get("description") or "").strip()
    if not name:
        raise ServiceError("Поле name обязательно", 422)
    if not description:
        raise ServiceError(
            "Поле description обязательно: по нему сервис понимает смысл нового типа обещания",
            422,
        )

    code = (payload.get("code") or _slugify(name)).strip().lower()
    code = re.sub(r"[^a-z0-9_]+", "_", code)[:40] or _slugify(name)

    keywords = [str(k).strip() for k in payload.get("keywords") or [] if str(k).strip()]
    patterns = [str(p) for p in payload.get("patterns") or [] if str(p).strip()]
    examples = [str(e) for e in payload.get("examples") or [] if str(e).strip()]

    # Без опорных слов тип не сможет сработать, а угадывать их из описания
    # опасно: случайное «перезвонить» создаст дубль задачи к встроенному типу.
    if not keywords and not patterns:
        raise ServiceError(
            "Укажите keywords (опорные слова) или patterns (регулярные выражения), "
            "иначе тип не сможет находить обещания и будет дублировать другие типы",
            422,
        )

    for pattern in patterns:
        try:
            re.compile(pattern, re.IGNORECASE)
        except re.error as exc:
            raise ServiceError(f"Некорректный pattern {pattern!r}: {exc}", 422) from exc

    with db.connect() as conn:
        exists = conn.execute("SELECT 1 FROM promise_types WHERE code = ?", (code,)).fetchone()
        if exists:
            raise ServiceError(f"Тип с кодом {code!r} уже существует", 409)
        conn.execute(
            """INSERT INTO promise_types
               (code, name, description, examples, keywords, patterns, action, is_builtin, active, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, 1, ?)""",
            (
                code, name, description,
                json.dumps(examples, ensure_ascii=False),
                json.dumps(keywords, ensure_ascii=False),
                json.dumps(patterns, ensure_ascii=False),
                (payload.get("action") or name).strip(),
                db.iso(db.utcnow()),
            ),
        )
    return {"code": code, "name": name, "description": description,
            "keywords": keywords, "patterns": patterns, "examples": examples,
            "is_builtin": False, "active": True}


def set_type_active(code: str, active: bool) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM promise_types WHERE code = ?", (code,)).fetchone()
        if not row:
            raise ServiceError(f"Тип {code!r} не найден", 404)
        if row["is_builtin"] and not active:
            raise ServiceError("Встроенный тип нельзя отключить", 409)
        conn.execute("UPDATE promise_types SET active = ? WHERE code = ?", (1 if active else 0, code))
    return {"code": code, "active": active}


# --------------------------------------------------------------------- звонки


def ingest(payload: Any) -> dict[str, Any]:
    """Принимает массив звонков, ищет обещания и создаёт задачи."""
    try:
        raw_calls = extract_calls(payload)
    except CallFormatError as exc:
        raise ServiceError(str(exc), 422) from exc

    now = db.utcnow()
    report: dict[str, Any] = {
        "received": len(raw_calls),
        "accepted": 0,
        "duplicates": 0,
        "tasks_created": 0,
        "errors": [],
        "calls": [],
    }
    types = load_types()

    for raw in raw_calls:
        try:
            call = parse_call(raw, now=now)
        except CallFormatError as exc:
            report["errors"].append({"call": raw.get("id"), "error": str(exc)})
            continue

        with db.connect() as conn:
            exists = conn.execute("SELECT 1 FROM calls WHERE id = ?", (call.external_id,)).fetchone()
            if exists:
                report["duplicates"] += 1
                report["calls"].append({"id": call.external_id, "status": "duplicate", "tasks_created": 0})
                continue

            promises = detect_promises(call.segments, types, call.ended_at, config.DEFAULT_DUE_HOURS)
            conn.execute(
                """INSERT INTO calls (id, operator_id, phone, started_at, ended_at,
                                      segments_json, payload_json, received_at, tasks_count)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    call.external_id, call.operator_id, call.phone,
                    db.iso(call.started_at), db.iso(call.ended_at),
                    json.dumps([s.__dict__ for s in call.segments], ensure_ascii=False, default=str),
                    json.dumps(raw, ensure_ascii=False, default=str),
                    db.iso(now), len(promises),
                ),
            )
            created = _insert_tasks(conn, call, promises, now)
            report["accepted"] += 1
            report["tasks_created"] += created
            report["calls"].append(
                {"id": call.external_id, "status": "accepted", "promises": len(promises), "tasks_created": created}
            )

    return report


def _insert_tasks(conn: sqlite3.Connection, call: ParsedCall, promises: list[DetectedPromise],
                  now: datetime) -> int:
    created = 0
    for promise in promises:
        cursor = conn.execute(
            """INSERT OR IGNORE INTO tasks
               (call_id, operator_id, phone, type_code, title, quote, comment, confidence,
                due_at, due_source, due_phrase, status, created_at, updated_at, dedupe_key)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, ?, ?)""",
            (
                call.external_id, call.operator_id, call.phone, promise.type_code,
                promise.title, promise.quote, promise.comment, promise.confidence,
                db.iso(promise.due_at), promise.due_source, promise.due_phrase,
                db.iso(now), db.iso(now), promise.dedupe_key,
            ),
        )
        if cursor.rowcount:
            created += 1
            conn.execute(
                "INSERT INTO task_events (task_id, from_status, to_status, note, at) VALUES (?, NULL, ?, ?, ?)",
                (cursor.lastrowid, "created", "Задача создана по звонку", db.iso(now)),
            )
    return created


def reprocess(call_id: str) -> dict[str, Any]:
    """Повторный разбор звонка: создаёт только недостающие задачи, дубли не появляются."""
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if not row:
        raise ServiceError(f"Звонок {call_id!r} не найден", 404)

    call = parse_call(json.loads(row["payload_json"]), now=db.utcnow())
    promises = detect_promises(call.segments, load_types(), call.ended_at, config.DEFAULT_DUE_HOURS)
    with db.connect() as conn:
        created = _insert_tasks(conn, call, promises, db.utcnow())
        total = conn.execute("SELECT COUNT(*) AS c FROM tasks WHERE call_id = ?", (call_id,)).fetchone()["c"]
        conn.execute("UPDATE calls SET tasks_count = ? WHERE id = ?", (total, call_id))
    return {"call_id": call_id, "promises": len(promises), "tasks_created": created, "tasks_total": total}


def list_calls(limit: int = 50, offset: int = 0) -> dict[str, Any]:
    with db.connect() as conn:
        total = conn.execute("SELECT COUNT(*) AS c FROM calls").fetchone()["c"]
        rows = conn.execute(
            "SELECT id, operator_id, phone, started_at, ended_at, received_at, tasks_count "
            "FROM calls ORDER BY received_at DESC LIMIT ? OFFSET ?",
            (limit, offset),
        ).fetchall()
    return {"items": db.rows_to_dicts(rows), "total": total, "limit": limit, "offset": offset}


def get_call(call_id: str) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
        if not row:
            raise ServiceError(f"Звонок {call_id!r} не найден", 404)
        tasks = conn.execute("SELECT * FROM tasks WHERE call_id = ? ORDER BY id", (call_id,)).fetchall()
    data = dict(row)
    data["segments"] = db.loads(data.pop("segments_json"), [])
    data.pop("payload_json", None)
    data["tasks"] = [serialize_task(t) for t in tasks]
    return data


# --------------------------------------------------------------------- задачи


def serialize_task(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    data = dict(row)
    data["status_label"] = STATUS_LABELS.get(data["status"], data["status"])
    data["is_overdue"] = data["status"] == "overdue"
    data["due_at"] = data["due_at"]
    return data


def sweep_overdue() -> int:
    """Переводит просроченные незакрытые задачи в статус overdue. Возвращает количество."""
    now_iso = db.iso(db.utcnow())
    changed = 0
    with db.connect() as conn:
        rows = conn.execute(
            "SELECT id, status FROM tasks WHERE status IN ('created', 'in_progress') AND due_at <= ?",
            (now_iso,),
        ).fetchall()
        for row in rows:
            conn.execute(
                "UPDATE tasks SET status = 'overdue', updated_at = ? WHERE id = ?",
                (now_iso, row["id"]),
            )
            conn.execute(
                "INSERT INTO task_events (task_id, from_status, to_status, note, at) VALUES (?, ?, ?, ?, ?)",
                (row["id"], row["status"], "overdue", "Срок истёк — статус выставлен автоматически", now_iso),
            )
            changed += 1
    return changed


def list_tasks(filters: dict[str, Any]) -> dict[str, Any]:
    sweep_overdue()

    where: list[str] = []
    params: list[Any] = []

    status = filters.get("status")
    if status:
        values = [s.strip() for s in str(status).split(",") if s.strip()]
        bad = [s for s in values if s not in STATUS_LABELS]
        if bad:
            raise ServiceError(f"Неизвестный статус: {', '.join(bad)}", 422)
        where.append(f"status IN ({','.join('?' * len(values))})")
        params.extend(values)

    if filters.get("operator_id"):
        where.append("operator_id = ?")
        params.append(str(filters["operator_id"]))

    if filters.get("type_code"):
        where.append("type_code = ?")
        params.append(str(filters["type_code"]))

    if filters.get("call_id"):
        where.append("call_id = ?")
        params.append(str(filters["call_id"]))

    if filters.get("due_before"):
        where.append("due_at <= ?")
        params.append(_normalize_dt(filters["due_before"]))

    if filters.get("due_after"):
        where.append("due_at >= ?")
        params.append(_normalize_dt(filters["due_after"]))

    if filters.get("overdue") in (True, "true", "1", 1):
        # Просрочка уже материализована в статус фоновой проверкой выше.
        where.append("status = 'overdue'")

    if filters.get("q"):
        where.append("(title LIKE ? OR quote LIKE ?)")
        needle = f"%{filters['q']}%"
        params.extend([needle, needle])

    clause = (" WHERE " + " AND ".join(where)) if where else ""

    sort = str(filters.get("sort") or "due_at")
    direction = "DESC" if sort.startswith("-") else "ASC"
    column = sort.lstrip("-")
    if column not in {"due_at", "created_at", "status", "id", "confidence"}:
        column = "due_at"
    order = f"ORDER BY {column} {direction}, id {direction}"

    limit = max(1, min(int(filters.get("limit") or 50), 500))
    offset = max(0, int(filters.get("offset") or 0))

    with db.connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) AS c FROM tasks{clause}", params).fetchone()["c"]
        rows = conn.execute(
            f"SELECT * FROM tasks{clause} {order} LIMIT ? OFFSET ?", [*params, limit, offset]
        ).fetchall()

    return {
        "items": [serialize_task(r) for r in rows],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


def _normalize_dt(value: Any) -> str:
    from .calls import parse_dt

    dt = parse_dt(value)
    if dt is None:
        raise ServiceError(f"Не удалось разобрать дату: {value!r}", 422)
    return db.iso(dt)


def get_task(task_id: int) -> dict[str, Any]:
    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise ServiceError(f"Задача {task_id} не найдена", 404)
        events = conn.execute(
            "SELECT from_status, to_status, note, at FROM task_events WHERE task_id = ? ORDER BY id",
            (task_id,),
        ).fetchall()
    data = serialize_task(row)
    data["events"] = db.rows_to_dicts(events)
    return data


def change_status(task_id: int, new_status: str, note: str | None = None,
                  due_at: str | None = None) -> dict[str, Any]:
    if new_status not in STATUS_LABELS:
        raise ServiceError(f"Неизвестный статус {new_status!r}", 422)
    if new_status == "overdue":
        raise ServiceError("Статус «Просрочена» выставляется автоматически", 409)

    now = db.utcnow()
    now_iso = db.iso(now)

    new_due: datetime | None = None
    if due_at:
        from .calls import parse_dt

        new_due = parse_dt(due_at)
        if new_due is None:
            raise ServiceError(f"Не удалось разобрать срок: {due_at!r}", 422)
        if new_due <= now:
            raise ServiceError("Новый срок должен быть в будущем", 422)

    with db.connect() as conn:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
        if not row:
            raise ServiceError(f"Задача {task_id} не найдена", 404)
        old = row["status"]
        if old == new_status and new_due is None:
            return serialize_task(row)
        if new_status != old and new_status not in ALLOWED_TRANSITIONS.get(old, set()):
            raise ServiceError(f"Недопустимый переход {STATUS_LABELS.get(old, old)} → {STATUS_LABELS[new_status]}", 409)
        # Просроченную нельзя «вернуть в работу» со старым сроком: иначе следующая
        # проверка снова сделает её просроченной. Нужен новый срок.
        if old == "overdue" and new_status == "in_progress" and new_due is None:
            raise ServiceError(
                "Просроченная задача возвращается в работу только с новым сроком: передайте due_at",
                422,
            )

        closed_at = now_iso if new_status == "done" else None
        if new_due is not None:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, closed_at = ?, due_at = ?, "
                "due_source = 'manual', due_phrase = NULL WHERE id = ?",
                (new_status, now_iso, closed_at, db.iso(new_due), task_id),
            )
        else:
            conn.execute(
                "UPDATE tasks SET status = ?, updated_at = ?, closed_at = ? WHERE id = ?",
                (new_status, now_iso, closed_at, task_id),
            )
        note_text = note or "Смена статуса через API"
        if new_due is not None:
            note_text += f"; новый срок: {db.iso(new_due)}"
        conn.execute(
            "INSERT INTO task_events (task_id, from_status, to_status, note, at) VALUES (?, ?, ?, ?, ?)",
            (task_id, old, new_status, note_text, now_iso),
        )
        updated = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    return serialize_task(updated)


def stats() -> dict[str, Any]:
    sweep_overdue()
    with db.connect() as conn:
        by_status = {r["status"]: r["c"] for r in conn.execute(
            "SELECT status, COUNT(*) AS c FROM tasks GROUP BY status").fetchall()}
        by_type = {r["type_code"]: r["c"] for r in conn.execute(
            "SELECT type_code, COUNT(*) AS c FROM tasks GROUP BY type_code").fetchall()}
        calls_total = conn.execute("SELECT COUNT(*) AS c FROM calls").fetchone()["c"]
        tasks_total = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    return {
        "calls_total": calls_total,
        "tasks_total": tasks_total,
        "by_status": {STATUS_LABELS[s]: by_status.get(s, 0) for s in STATUS_LABELS},
        "by_type": by_type,
        "avg_promises_per_call": round(tasks_total / calls_total, 2) if calls_total else 0.0,
    }

"""Приём звонков: валидация, идемпотентность, создание задач."""
from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from pydantic import ValidationError

from ..schemas import CallIn
from ..utils import normalize_text, parse_iso, utc_now
from .deadline import get_tz, parse_deadline
from .detect import DetectedPromise, call_end_for, detect_promises
from .llm import detect_with_llm
from .tasks import insert_task, load_types, mark_overdue, new_task_id
from .verify import verify_phone


def _merge_llm(
    call_dict: dict[str, Any], promises: list[DetectedPromise], types
) -> list[DetectedPromise]:
    """Второй проход LLM: подтверждает найденное и добавляет пропущенное."""
    llm_promises = detect_with_llm(call_dict, types)
    if not llm_promises:
        return promises

    by_index = {p.transcript_index: p for p in promises}
    titles = {t.code: t.title for t in types}
    tz = get_tz()
    call_end = call_end_for(call_dict, tz)
    added: dict[int, str] = {}

    for item in llm_promises:
        existing = by_index.get(item.index)
        if existing is not None:
            if existing.promise_type == item.type_code:
                existing.confidence = round(min(0.99, existing.confidence + 0.05), 2)
                existing.matched_by = "rule+llm"
            continue
        if item.index in added:
            continue
        added[item.index] = item.type_code
        promises.append(
            DetectedPromise(
                promise_type=item.type_code,
                title=titles.get(item.type_code, item.type_code),
                quote=item.quote,
                transcript_index=item.index,
                actions=[],
                object="",
                due=parse_deadline(item.quote, call_end, tz),
                confidence=0.6,
                matched_by="llm",
            )
        )
    return promises


def _dedupe_key(call_id: str, promise_type: str, index: int, quote: str) -> str:
    raw = f"{call_id}|{promise_type}|{index}|{normalize_text(quote)}".encode("utf-8")
    return hashlib.sha1(raw).hexdigest()


def normalize_payload(payload: Any) -> list[dict[str, Any]]:
    """Поддерживаем три формата: массив, один звонок, {"calls": [...]}."""
    if payload is None:
        return []
    if isinstance(payload, list):
        return [p for p in payload if isinstance(p, dict)]
    if isinstance(payload, dict):
        if isinstance(payload.get("calls"), list):
            return [p for p in payload["calls"] if isinstance(p, dict)]
        if "id" in payload:
            return [payload]
        # Telegram-подобная обёртка или иной контейнер
        for key in ("data", "items", "results"):
            if isinstance(payload.get(key), list):
                return [p for p in payload[key] if isinstance(p, dict)]
    return []


def _as_operator_id(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def process_call(conn: sqlite3.Connection, raw: dict[str, Any], types=None) -> dict[str, Any]:
    """Обрабатывает один звонок. Возвращает результат для отчёта."""
    try:
        call = CallIn.model_validate(raw)
    except ValidationError as exc:
        return {
            "call_id": str(raw.get("id") or "unknown"),
            "status": "error",
            "tasks_created": 0,
            "promises_found": 0,
            "tasks_verified": 0,
            "error": _short_validation_error(exc),
        }

    existing = conn.execute("SELECT 1 FROM calls WHERE id = ?", (call.id,)).fetchone()
    if existing:
        return {
            "call_id": call.id,
            "status": "duplicate",
            "tasks_created": 0,
            "promises_found": 0,
            "tasks_verified": 0,
            "error": None,
        }

    types = types or load_types(conn)
    call_dict = {
        "id": call.id,
        "operator_id": _as_operator_id(call.operator_id),
        "client_phone": call.client_phone,
        "started_at": call.started_at,
        "ended_at": call.ended_at,
        "transcript": [r.model_dump() for r in call.transcript],
    }
    promises = detect_promises(call_dict, types)
    promises = _merge_llm(call_dict, promises, types)

    now = utc_now()
    created = 0
    verified = 0
    try:
        conn.execute(
            """INSERT INTO calls (id, operator_id, client_phone, started_at, ended_at, transcript,
                                  received_at, processed_at, promise_count, status, raw)
               VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
            (
                call.id,
                call_dict["operator_id"],
                call.client_phone,
                call.started_at,
                call.ended_at,
                json.dumps(call_dict["transcript"], ensure_ascii=False),
                now,
                now,
                len(promises),
                "processed",
                json.dumps(raw, ensure_ascii=False),
            ),
        )
        for promise in promises:
            created += int(
                insert_task(
                    conn,
                    {
                        "id": new_task_id(),
                        "call_id": call.id,
                        "operator_id": call_dict["operator_id"],
                        "promise_type": promise.promise_type,
                        "title": promise.title,
                        "object": promise.object,
                        "quote": promise.quote,
                        "transcript_index": promise.transcript_index,
                        "actions": promise.actions,
                        "secondary_types": promise.secondary_types,
                        "due_at": promise.due_at,
                        "due_hint": promise.due.hint,
                        "deadline_source": promise.due.source,
                        "confidence": promise.confidence,
                        "matched_by": promise.matched_by,
                        "dedupe_key": _dedupe_key(
                            call.id, promise.promise_type, promise.transcript_index, promise.quote
                        ),
                    },
                )
            )
        verified = verify_phone(conn, call.client_phone)
        conn.commit()
    except Exception as exc:  # pragma: no cover - защита от неожиданной ошибки БД
        conn.rollback()
        return {
            "call_id": call.id,
            "status": "error",
            "tasks_created": 0,
            "promises_found": len(promises),
            "tasks_verified": 0,
            "error": f"Ошибка сохранения: {exc}",
        }

    return {
        "call_id": call.id,
        "status": "processed",
        "tasks_created": created,
        "promises_found": len(promises),
        "tasks_verified": verified,
        "error": None,
    }


def ingest_payload(conn: sqlite3.Connection, payload: Any) -> dict[str, Any]:
    calls = normalize_payload(payload)
    types = load_types(conn)
    results = [process_call(conn, raw, types) for raw in calls]
    mark_overdue(conn)

    processed = sum(1 for r in results if r["status"] == "processed")
    duplicates = sum(1 for r in results if r["status"] == "duplicate")
    failed = sum(1 for r in results if r["status"] == "error")
    return {
        "received": len(calls),
        "processed": processed,
        "duplicates": duplicates,
        "failed": failed,
        "tasks_created": sum(r["tasks_created"] for r in results),
        "tasks_verified": sum(r.get("tasks_verified", 0) for r in results),
        "calls": results,
    }


def reanalyze_call(conn: sqlite3.Connection, call_id: str) -> dict[str, Any] | None:
    """Повторный поиск обещаний с учётом новых типов. Существующие задачи не дублируются."""
    row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if not row:
        return None
    transcript = json.loads(row["transcript"] or "[]")
    types = load_types(conn)
    call_dict = {
        "id": row["id"],
        "operator_id": row["operator_id"],
        "client_phone": row["client_phone"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "transcript": transcript,
    }
    promises = detect_promises(call_dict, types)
    created = 0
    for promise in promises:
        created += int(
            insert_task(
                conn,
                {
                    "id": new_task_id(),
                    "call_id": call_id,
                    "operator_id": row["operator_id"],
                    "promise_type": promise.promise_type,
                    "title": promise.title,
                    "object": promise.object,
                    "quote": promise.quote,
                    "transcript_index": promise.transcript_index,
                    "actions": promise.actions,
                    "secondary_types": promise.secondary_types,
                    "due_at": promise.due_at,
                    "due_hint": promise.due.hint,
                    "deadline_source": promise.due.source,
                    "confidence": promise.confidence,
                    "matched_by": promise.matched_by,
                    "dedupe_key": _dedupe_key(
                        call_id, promise.promise_type, promise.transcript_index, promise.quote
                    ),
                },
            )
        )
    conn.execute(
        "UPDATE calls SET promise_count = ?, processed_at = ? WHERE id = ?",
        (len(promises), utc_now(), call_id),
    )
    verified = verify_phone(conn, row["client_phone"])
    conn.commit()
    return {
        "call_id": call_id,
        "promises_found": len(promises),
        "tasks_created": created,
        "tasks_verified": verified,
    }


def _short_validation_error(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:3]:
        loc = ".".join(str(p) for p in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg')}")
    return "; ".join(parts)

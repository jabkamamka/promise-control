"""HTTP-слой: вебхук звонков и чтение звонков."""
from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

from ..config import settings
from ..db import get_db
from ..schemas import CallList, CallOut, IngestResponse, TaskOut
from ..services.ingest import ingest_payload, normalize_payload, reanalyze_call
from ..services.tasks import get_task, list_tasks, mark_overdue

router = APIRouter(tags=["calls"])


@router.post("/webhook/calls", response_model=IngestResponse, summary="Приём звонков от программы-отправителя")
async def webhook_calls(
    request: Request,
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    conn: sqlite3.Connection = Depends(get_db),
) -> IngestResponse:
    return await _handle_webhook(request, x_webhook_token, conn)


@router.post("/calls", response_model=IngestResponse, include_in_schema=False)
async def webhook_calls_compat(
    request: Request,
    x_webhook_token: str | None = Header(default=None, alias="X-Webhook-Token"),
    conn: sqlite3.Connection = Depends(get_db),
) -> IngestResponse:
    """Совместимость: если отправитель настроен на /calls вместо /webhook/calls."""
    return await _handle_webhook(request, x_webhook_token, conn)


async def _handle_webhook(
    request: Request,
    x_webhook_token: str | None,
    conn: sqlite3.Connection,
) -> IngestResponse:
    if settings.webhook_token and x_webhook_token != settings.webhook_token:
        raise HTTPException(status_code=401, detail="Неверный или отсутствующий X-Webhook-Token")

    try:
        payload = await request.json()
    except json.JSONDecodeError:
        raise HTTPException(status_code=400, detail="Тело запроса должно быть JSON")

    if not normalize_payload(payload):
        raise HTTPException(
            status_code=400,
            detail='Ожидается массив звонков, один звонок или {"calls": [...]}',
        )

    result = ingest_payload(conn, payload)
    return IngestResponse(**result)


@router.get("/api/v1/calls", response_model=CallList, summary="Список принятых звонков")
def calls_list(
    operator_id: int | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
) -> CallList:
    where, params = "", []
    if operator_id is not None:
        where, params = " WHERE operator_id = ?", [operator_id]
    total = conn.execute(f"SELECT COUNT(*) AS c FROM calls{where}", params).fetchone()["c"]
    rows = conn.execute(
        f"SELECT * FROM calls{where} ORDER BY received_at DESC LIMIT ? OFFSET ?",
        [*params, limit, offset],
    ).fetchall()
    items = [_call_to_out(conn, r, include_tasks=False) for r in rows]
    return CallList(items=items, total=total, limit=limit, offset=offset)


@router.get("/api/v1/calls/{call_id}", response_model=CallOut, summary="Звонок с задачами")
def call_detail(call_id: str, conn: sqlite3.Connection = Depends(get_db)) -> CallOut:
    row = conn.execute("SELECT * FROM calls WHERE id = ?", (call_id,)).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    return _call_to_out(conn, row, include_tasks=True)


@router.post("/api/v1/calls/{call_id}/reanalyze", summary="Повторный поиск обещаний")
def call_reanalyze(call_id: str, conn: sqlite3.Connection = Depends(get_db)) -> JSONResponse:
    result = reanalyze_call(conn, call_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Звонок не найден")
    return JSONResponse(result)


def _call_to_out(conn: sqlite3.Connection, row: sqlite3.Row, include_tasks: bool) -> CallOut:
    data: dict[str, Any] = {
        "id": row["id"],
        "operator_id": row["operator_id"],
        "client_phone": row["client_phone"],
        "started_at": row["started_at"],
        "ended_at": row["ended_at"],
        "received_at": row["received_at"],
        "processed_at": row["processed_at"],
        "promise_count": row["promise_count"],
        "status": row["status"],
        "transcript": json.loads(row["transcript"] or "[]"),
        "tasks": [],
    }
    if include_tasks:
        tasks, _ = list_tasks(conn, call_id=row["id"], limit=200)
        data["tasks"] = [TaskOut(**t) for t in tasks]
    return CallOut(**data)

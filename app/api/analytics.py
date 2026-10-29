"""HTTP-слой: аналитика и выгрузка. Новые методы, существующие не меняются."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query
from fastapi.responses import PlainTextResponse

from ..db import get_db
from ..services.analytics import build_analytics
from ..services.export import filename, tasks_csv

router = APIRouter(prefix="/api/v1", tags=["analytics"])


@router.get("/analytics", summary="Сводка для руководителя смены")
def analytics_view(
    days: int = Query(default=14, ge=1, le=90, description="Сколько дней показывать на графике"),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    return build_analytics(conn, days=days)


@router.get("/tasks-export", summary="Выгрузка задач в CSV (Excel)")
def tasks_export(
    status: str | None = None,
    type: str | None = None,
    operator_id: int | None = None,
    call_id: str | None = None,
    due_before: str | None = None,
    due_after: str | None = None,
    q: str | None = None,
    verification: str | None = None,
    sort: str = "due_at",
    conn: sqlite3.Connection = Depends(get_db),
) -> PlainTextResponse:
    csv_text = tasks_csv(
        conn,
        status=status,
        promise_type=type,
        operator_id=operator_id,
        call_id=call_id,
        due_before=due_before,
        due_after=due_after,
        q=q,
        verification=verification,
        sort=sort,
    )
    return PlainTextResponse(
        content=csv_text,
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename()}"'},
    )

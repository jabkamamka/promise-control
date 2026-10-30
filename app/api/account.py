"""Личный кабинет: тариф, привязка оператора, «мои обещания», демо-подписка."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from ..db import get_db
from ..services import users
from ..services.tasks import list_tasks
from .auth import current_user

router = APIRouter(tags=["account"])

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


class OperatorIn(BaseModel):
    operator_id: int | None = Field(None, examples=[7])


@router.get("/account", include_in_schema=False)
def account_page() -> FileResponse:
    return FileResponse(WEB_DIR / "account.html")


@router.get("/api/v1/me", summary="Профиль: тариф, реклама, оператор")
def me(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    user = current_user(request, conn)
    if not user:
        return {"authenticated": False, "plan": None, "ads": True}
    return {"authenticated": True, **users.user_public(user)}


@router.patch("/api/v1/me", summary="Привязать оператора к аккаунту")
def update_me(payload: OperatorIn, request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    user = current_user(request, conn)
    if not user:
        raise HTTPException(status_code=401, detail="Нужен вход")
    updated = users.bind_operator(conn, user["id"], payload.operator_id)
    conn.commit()
    return {"authenticated": True, **users.user_public(updated)}


@router.get("/api/v1/me/tasks", summary="Мои обещания (задачи оператора)")
def my_tasks(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    user = current_user(request, conn)
    if not user:
        raise HTTPException(status_code=401, detail="Нужен вход")
    if user["operator_id"] is None:
        return {"items": [], "total": 0, "operator_id": None,
                "hint": "Привяжите operator_id в профиле — задачи подтянутся по номеру оператора"}
    items, total = list_tasks(conn, operator_id=int(user["operator_id"]), limit=100)
    return {"items": items, "total": total, "operator_id": user["operator_id"]}


@router.post("/api/v1/billing/subscribe", summary="Оформить подписку (демо-режим, без оплаты)")
def subscribe(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    user = current_user(request, conn)
    if not user:
        raise HTTPException(status_code=401, detail="Нужен вход")
    updated = users.set_plan(conn, user["id"], "pro")
    conn.commit()
    return {
        "plan": updated["plan"],
        "ads": False,
        # Честно: платёжного провайдера нет, это демонстрация механики.
        "mock_payment": True,
        "note": "Демо-режим: оплата не списывается, тариф включён локально",
    }


@router.post("/api/v1/billing/cancel", summary="Отменить подписку")
def cancel(request: Request, conn: sqlite3.Connection = Depends(get_db)) -> dict:
    users.ensure_schema(conn)
    user = current_user(request, conn)
    if not user:
        raise HTTPException(status_code=401, detail="Нужен вход")
    updated = users.set_plan(conn, user["id"], "free")
    conn.commit()
    return {"plan": updated["plan"], "ads": True}

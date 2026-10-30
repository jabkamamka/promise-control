"""HTTP-слой уведомлений: список для сотрудника, отметки о прочтении, ручной проход.

Письма отправляет сам сервис (планировщик или `POST /scan`), отдельный бот не нужен.
"""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, Query

from ..api.auth import require_employee
from ..db import get_db
from ..services import mailer, notifications

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])


@router.get("", summary="Уведомления сотрудника")
def list_notifications(
    unread: bool = Query(default=False, description="Только непрочитанные"),
    limit: int = Query(default=20, ge=1, le=100),
    employee: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    items = notifications.list_for(conn, employee["id"], limit, unread)
    return {
        "items": items,
        "unread": notifications.unread_count(conn, employee["id"]),
        "email": mailer.describe(),
    }


@router.post("/read", summary="Отметить уведомления прочитанными")
def mark_read(
    payload: dict | None = None,
    employee: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    ids = None
    if payload:
        raw = payload.get("ids")
        if isinstance(raw, list):
            ids = [int(value) for value in raw if str(value).isdigit()]
    changed = notifications.mark_read(conn, employee["id"], ids)
    return {"marked": changed, "unread": notifications.unread_count(conn, employee["id"])}


@router.post("/scan", summary="Проверить сроки и разослать уведомления сейчас")
def scan(
    employee: dict = Depends(require_employee),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict:
    result = notifications.run_cycle(conn)
    result["email"] = mailer.describe()
    return result


@router.post("/test", summary="Отправить проверочное письмо себе")
def send_test_email(employee: dict = Depends(require_employee)) -> dict:
    """Проверка настроек почты: результат видно сразу, без ожидания сроков."""
    result = mailer.send(
        employee["email"],
        "Проверка почты — Контроль обещаний",
        "Это проверочное письмо. Если вы его видите, уведомления о сроках тоже дойдут.",
    )
    return {
        "status": result.status,
        "detail": result.detail,
        "to": employee["email"],
        "email": mailer.describe(),
    }

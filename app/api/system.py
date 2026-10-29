"""Служебные методы: health и статистика."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends

from ..config import settings
from ..db import get_db
from ..schemas import HealthOut, StatsOut
from ..services.tasks import stats
from ..utils import utc_now

router = APIRouter(tags=["system"])


@router.get("/health", response_model=HealthOut, summary="Проверка живости")
def health(conn: sqlite3.Connection = Depends(get_db)) -> HealthOut:
    types = conn.execute("SELECT COUNT(*) AS c FROM promise_types").fetchone()["c"]
    tasks_count = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    return HealthOut(
        status="ok",
        version=settings.app_version,
        time=utc_now(),
        database="sqlite",
        timezone=settings.timezone,
        types=types,
        tasks=tasks_count,
    )


@router.get("/api/v1/stats", response_model=StatsOut, summary="Сводка по задачам")
def stats_view(conn: sqlite3.Connection = Depends(get_db)) -> StatsOut:
    return StatsOut(**stats(conn))

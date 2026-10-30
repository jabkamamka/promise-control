"""Аналитика по сотрудникам: сколько взяли, закрыли, просрочили и как быстро."""

from __future__ import annotations

import datetime as dt
import sqlite3
from typing import Any

from ..config import settings
from ..utils import parse_iso, utc_now
from .deadline import get_tz

OPEN_STATUSES = ("created", "in_progress")


def build_employees(conn: sqlite3.Connection, days: int = 30) -> dict[str, Any]:
    """Сводка по каждому сотруднику за окно дней (по дате взятия задачи)."""
    tz = get_tz(settings.timezone)
    now = dt.datetime.now(dt.timezone.utc)
    start = now - dt.timedelta(days=days)
    start_iso = start.replace(microsecond=0).isoformat().replace("+00:00", "Z")

    employees = conn.execute(
        """SELECT id, email, full_name, role, is_active, email_confirmed_at
           FROM employees ORDER BY full_name"""
    ).fetchall()

    rows = conn.execute(
        """SELECT assignee_id, status, due_at, taken_at, created_at, closed_at,
                  verification_status
           FROM tasks
           WHERE assignee_id IS NOT NULL"""
    ).fetchall()

    buckets: dict[int, dict[str, Any]] = {}
    for row in rows:
        employee_id = row["assignee_id"]
        bucket = buckets.setdefault(
            employee_id,
            {
                "taken": 0,
                "in_progress": 0,
                "done": 0,
                "overdue": 0,
                "on_time": 0,
                "refuted": 0,
                "confirmed": 0,
                "close_hours": [],
            },
        )
        taken_at = parse_iso(row["taken_at"]) or parse_iso(row["created_at"])
        if not taken_at or taken_at < start:
            continue

        bucket["taken"] += 1
        status = row["status"]
        due = parse_iso(row["due_at"])
        if status == "done":
            bucket["done"] += 1
            closed = parse_iso(row["closed_at"])
            if closed and due and closed <= due:
                bucket["on_time"] += 1
            if closed and taken_at and closed >= taken_at:
                bucket["close_hours"].append((closed - taken_at).total_seconds() / 3600)
        else:
            if status in OPEN_STATUSES:
                bucket["in_progress"] += 1
            if due and due < now:
                bucket["overdue"] += 1

        if row["verification_status"] == "refuted":
            bucket["refuted"] += 1
        elif row["verification_status"] == "confirmed":
            bucket["confirmed"] += 1

    result = []
    for employee in employees:
        stats = buckets.get(employee["id"], {})
        taken = stats.get("taken", 0)
        done = stats.get("done", 0)
        hours = stats.get("close_hours", [])
        result.append(
            {
                "id": employee["id"],
                "full_name": employee["full_name"],
                "email": employee["email"],
                "role": employee["role"],
                "is_active": bool(employee["is_active"]),
                "email_confirmed": bool(employee["email_confirmed_at"]),
                "taken": taken,
                "in_progress": stats.get("in_progress", 0),
                "done": done,
                "overdue": stats.get("overdue", 0),
                "on_time": stats.get("on_time", 0),
                "confirmed": stats.get("confirmed", 0),
                "refuted": stats.get("refuted", 0),
                "done_share": round(done / taken * 100, 1) if taken else 0.0,
                "on_time_share": round(stats.get("on_time", 0) / done * 100, 1) if done else 0.0,
                "avg_close_hours": round(sum(hours) / len(hours), 1) if hours else None,
            }
        )

    result.sort(key=lambda item: (item["taken"], item["done"]), reverse=True)
    totals = {
        "employees": len([item for item in result if item["taken"]]),
        "taken": sum(item["taken"] for item in result),
        "done": sum(item["done"] for item in result),
        "overdue": sum(item["overdue"] for item in result),
        "in_progress": sum(item["in_progress"] for item in result),
    }
    return {
        "generated_at": utc_now(),
        "timezone": settings.timezone,
        "period_days": days,
        "window_start": start_iso,
        "totals": totals,
        "employees": result,
    }

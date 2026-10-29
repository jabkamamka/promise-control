"""Аналитика: агрегаты по задачам для панели руководителя смены.

Модуль новый и ничего не меняет в существующих: читает те же таблицы
и считает сводки. Дни считаются в часовом поясе сервиса (APP_TIMEZONE).
"""
from __future__ import annotations

import datetime as dt
import sqlite3
from collections import Counter, defaultdict
from typing import Any

from ..config import settings
from ..utils import parse_iso, utc_now
from .deadline import get_tz

OPEN_STATUSES = ("created", "in_progress")


def _local_date(value: str | None, tz: dt.tzinfo) -> dt.date | None:
    moment = parse_iso(value)
    return moment.astimezone(tz).date() if moment else None


def build_analytics(conn: sqlite3.Connection, days: int = 14) -> dict[str, Any]:
    tz = get_tz(settings.timezone)
    today = dt.datetime.now(tz).date()
    # Окно вокруг сегодняшнего дня: видно и прошедшие, и предстоящие сроки
    half = days // 2
    start = today - dt.timedelta(days=half)
    window = [start + dt.timedelta(days=offset) for offset in range(days)]
    window_set = set(window)
    horizon_end = window[-1]

    rows = conn.execute(
        """SELECT t.id, t.promise_type, t.status, t.due_at, t.created_at, t.closed_at,
                  t.operator_id, t.verification_status, p.title AS type_title
           FROM tasks t
           LEFT JOIN promise_types p ON p.code = t.promise_type"""
    ).fetchall()
    calls_total = conn.execute("SELECT COUNT(*) AS c FROM calls").fetchone()["c"]

    by_status: Counter[str] = Counter()
    by_type: Counter[str] = Counter()
    by_type_title: dict[str, str] = {}
    by_verification: Counter[str] = Counter()
    operators: dict[int, dict[str, int]] = defaultdict(lambda: {"open": 0, "overdue": 0, "done": 0})
    created_series: Counter[dt.date] = Counter()
    closed_series: Counter[dt.date] = Counter()
    due_series: Counter[dt.date] = Counter()
    close_hours: list[float] = []
    overdue = 0
    not_fulfilled = 0
    due_today = 0

    for row in rows:
        status = row["status"]
        by_status[status] += 1
        by_type[row["promise_type"]] += 1
        if row["type_title"]:
            by_type_title[row["promise_type"]] = row["type_title"]

        verification = row["verification_status"]
        by_verification[verification or "pending"] += 1
        if verification == "refuted":
            not_fulfilled += 1

        due = parse_iso(row["due_at"])
        is_overdue = status != "done" and verification != "refuted" and due is not None and due < dt.datetime.now(dt.timezone.utc)
        if is_overdue:
            overdue += 1

        due_day = _local_date(row["due_at"], tz)
        if status != "done" and verification != "refuted" and due_day:
            if due_day in window_set:
                due_series[due_day] += 1
            if due_day == today:
                due_today += 1

        operator = row["operator_id"]
        if operator is not None:
            if status == "done":
                operators[operator]["done"] += 1
            else:
                operators[operator]["open"] += 1
                if is_overdue:
                    operators[operator]["overdue"] += 1

        created_day = _local_date(row["created_at"], tz)
        if created_day and created_day in window_set:
            created_series[created_day] += 1
        if status == "done" and row["closed_at"]:
            closed_day = _local_date(row["closed_at"], tz)
            if closed_day and closed_day in window_set:
                closed_series[closed_day] += 1
            opened = parse_iso(row["created_at"])
            closed = parse_iso(row["closed_at"])
            if opened and closed and closed >= opened:
                close_hours.append((closed - opened).total_seconds() / 3600)

    series = []
    for day in window:
        series.append(
            {
                "date": day.isoformat(),
                "weekday": day.isoweekday(),
                "created": created_series.get(day, 0),
                "closed": closed_series.get(day, 0),
                "due": due_series.get(day, 0),
            }
        )

    close_hours.sort()
    median = close_hours[len(close_hours) // 2] if close_hours else None
    avg = round(sum(close_hours) / len(close_hours), 1) if close_hours else None

    tasks_total = len(rows)
    return {
        "generated_at": utc_now(),
        "timezone": settings.timezone,
        "period_days": days,
        "totals": {
            "calls": calls_total,
            "tasks": tasks_total,
            "closed": by_status.get("done", 0),
            "overdue": overdue,
            "not_fulfilled": not_fulfilled,
            "due_today": due_today,
            "open": sum(by_status.get(s, 0) for s in OPEN_STATUSES),
            "overdue_share": round(overdue / tasks_total * 100, 1) if tasks_total else 0.0,
            "closed_share": round(by_status.get("done", 0) / tasks_total * 100, 1) if tasks_total else 0.0,
        },
        "by_status": {key: by_status.get(key, 0) for key in ("created", "in_progress", "done")},
        "by_verification": {
            key: by_verification.get(key, 0) for key in ("pending", "confirmed", "refuted")
        },
        "by_type": sorted(
            (
                {"code": code, "title": by_type_title.get(code, code), "count": count}
                for code, count in by_type.items()
            ),
            key=lambda item: item["count"],
            reverse=True,
        ),
        "series": series,
        "operators": sorted(
            (
                {"operator_id": operator, **counts}
                for operator, counts in operators.items()
            ),
            key=lambda item: (item["open"], item["overdue"]),
            reverse=True,
        )[:15],
        "close_time": {
            "closed_count": len(close_hours),
            "avg_hours": avg,
            "median_hours": round(median, 1) if median is not None else None,
        },
    }

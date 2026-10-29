"""Демо-прогресс: часть задач закрыта и взята в работу, чтобы аналитика была живой.

Только для демонстрации. Не влияет на тесты: вызывается флагом из seed_demo.py.
Закрытые задачи получают `closed_at` относительно окончания звонка (а не момента
загрузки), поэтому график выполнения распределён по дням.
"""
from __future__ import annotations

import datetime as dt
import random
import sqlite3

from ..utils import parse_iso, to_iso, utc_now


def apply_progress(conn: sqlite3.Connection, seed: int = 42) -> dict[str, int]:
    # Задача создаётся сразу после звонка, а не в момент демо-загрузки:
    # иначе closed_at оказывается раньше created_at и график ломается.
    conn.execute(
        """UPDATE tasks
           SET created_at = (SELECT c.ended_at FROM calls c WHERE c.id = tasks.call_id)
           WHERE EXISTS (SELECT 1 FROM calls c WHERE c.id = tasks.call_id AND c.ended_at IS NOT NULL)"""
    )
    conn.commit()

    rows = conn.execute(
        """SELECT t.id, t.created_at, t.due_at, t.status, c.ended_at AS call_ended_at
           FROM tasks t
           JOIN calls c ON c.id = t.call_id
           WHERE t.status = 'created'
           ORDER BY c.ended_at, t.due_at"""
    ).fetchall()
    if not rows:
        return {"done": 0, "in_progress": 0}

    rng = random.Random(seed)
    now = dt.datetime.now(dt.timezone.utc)
    fresh_edge = now - dt.timedelta(days=2)
    done = in_progress = 0

    for index, row in enumerate(rows):
        ended = parse_iso(row["call_ended_at"]) or now
        is_old = ended < fresh_edge

        # старые обещания в основном закрыты, свежие — ещё в работе
        should_close = (index % 4 != 0) if is_old else (index % 7 == 0)
        should_take = (not should_close) and (index % 3 == 0)

        if should_close:
            closed = ended + dt.timedelta(hours=rng.uniform(0.4, 9.0))
            closed = min(closed, now)
            created = parse_iso(row["created_at"]) or ended
            if closed <= created:
                continue
            conn.execute(
                "UPDATE tasks SET status='done', closed_at=?, updated_at=? WHERE id=?",
                (to_iso(closed), to_iso(closed), row["id"]),
            )
            conn.execute(
                "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
                (row["id"], "status_changed", "created", "done", "Демо: задача выполнена", to_iso(closed)),
            )
            done += 1
        elif should_take:
            conn.execute(
                "UPDATE tasks SET status='in_progress', updated_at=? WHERE id=?",
                (utc_now(), row["id"]),
            )
            conn.execute(
                "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) VALUES (?,?,?,?,?,?)",
                (row["id"], "status_changed", "created", "in_progress", "Демо: взята в работу", utc_now()),
            )
            in_progress += 1

    conn.commit()
    return {"done": done, "in_progress": in_progress}

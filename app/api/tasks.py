"""HTTP-слой: задачи оператора."""
from __future__ import annotations

import sqlite3

from fastapi import APIRouter, Depends, HTTPException, Query

from ..db import get_db
from ..schemas import TaskEvent, TaskList, TaskOut, TaskStatusUpdate
from ..services.tasks import (
    TaskError,
    get_task,
    list_events,
    list_tasks,
    mark_overdue,
    update_status,
)

router = APIRouter(prefix="/api/v1/tasks", tags=["tasks"])


@router.get("", response_model=TaskList, summary="Список задач с фильтрами")
def tasks_list(
    status: str | None = Query(default=None, description="created,in_progress,done,overdue (можно несколько)"),
    promise_type: str | None = Query(default=None, alias="type"),
    operator_id: int | None = None,
    call_id: str | None = None,
    due_before: str | None = Query(default=None, description="ISO-8601, включительно"),
    due_after: str | None = Query(default=None, description="ISO-8601, включительно"),
    q: str | None = Query(default=None, description="Поиск по названию, цитате и объекту"),
    sort: str = Query(default="due_at", description="due_at, -due_at, created_at, status, confidence"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    conn: sqlite3.Connection = Depends(get_db),
) -> TaskList:
    mark_overdue(conn)
    items, total = list_tasks(
        conn,
        status=status,
        promise_type=promise_type,
        operator_id=operator_id,
        call_id=call_id,
        due_before=due_before,
        due_after=due_after,
        q=q,
        sort=sort,
        limit=limit,
        offset=offset,
    )
    return TaskList(items=[TaskOut(**t) for t in items], total=total, limit=limit, offset=offset)


@router.get("/{task_id}", response_model=TaskOut, summary="Задача по id")
def task_detail(task_id: str, conn: sqlite3.Connection = Depends(get_db)) -> TaskOut:
    mark_overdue(conn)
    task = get_task(conn, task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return TaskOut(**task)


@router.patch("/{task_id}", response_model=TaskOut, summary="Сменить статус задачи")
def task_update(
    task_id: str,
    payload: TaskStatusUpdate,
    conn: sqlite3.Connection = Depends(get_db),
) -> TaskOut:
    return _apply_status(task_id, payload, conn)


@router.patch("/{task_id}/status", response_model=TaskOut, include_in_schema=False)
def task_update_compat(
    task_id: str,
    payload: TaskStatusUpdate,
    conn: sqlite3.Connection = Depends(get_db),
) -> TaskOut:
    """Совместимость: PATCH /tasks/{id}/status."""
    return _apply_status(task_id, payload, conn)


def _apply_status(task_id: str, payload: TaskStatusUpdate, conn: sqlite3.Connection) -> TaskOut:
    try:
        task = update_status(conn, task_id, payload.status, payload.comment)
    except KeyError:
        raise HTTPException(status_code=404, detail="Задача не найдена")
    except TaskError as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    return TaskOut(**task)


@router.get("/{task_id}/events", response_model=list[TaskEvent], summary="История задачи")
def task_events(task_id: str, conn: sqlite3.Connection = Depends(get_db)) -> list[TaskEvent]:
    if not get_task(conn, task_id):
        raise HTTPException(status_code=404, detail="Задача не найдена")
    return [TaskEvent(**e) for e in list_events(conn, task_id)]

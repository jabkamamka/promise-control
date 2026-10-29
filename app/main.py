"""HTTP-слой сервиса контроля обещаний (FastAPI)."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from typing import Any

from fastapi import Body, FastAPI, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field

from . import config, db, service

log = logging.getLogger("promise-service")

app = FastAPI(
    title="Сервис контроля обещаний",
    description=(
        "Принимает расшифровки звонков, находит обещания оператора, создаёт задачи "
        "со сроком и ведёт их статусы. Кейс УралМикро, хакатон 2026."
    ),
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ------------------------------------------------------------------- модели API


class PromiseTypeIn(BaseModel):
    name: str = Field(..., examples=["Перезвонить в отдел"])
    description: str = Field(..., examples=["Оператор обещает соединить клиента с профильным отделом."])
    code: str | None = Field(None, examples=["transfer_to_department"])
    keywords: list[str] = Field(default_factory=list, examples=[["соединю", "переключу"]])
    patterns: list[str] = Field(default_factory=list, examples=[[r"\bпереключу\b"]])
    examples: list[str] = Field(default_factory=list)
    action: str | None = Field(None, examples=["Соединить клиента с отделом"])


class StatusIn(BaseModel):
    status: str = Field(..., examples=["in_progress"])
    note: str | None = Field(None, examples=["Взял в работу"])


# ---------------------------------------------------------------- инфраструктура


@app.exception_handler(service.ServiceError)
async def _service_error_handler(request: Request, exc: service.ServiceError) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.on_event("startup")
async def on_startup() -> None:
    db.init_db()
    service.seed_types()
    app.state.sweeper = asyncio.create_task(_sweeper())
    log.info("Сервис запущен, БД: %s", config.DB_PATH)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    task = getattr(app.state, "sweeper", None)
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


async def _sweeper() -> None:
    while True:
        try:
            changed = await asyncio.to_thread(service.sweep_overdue)
            if changed:
                log.info("Просрочено задач: %s", changed)
        except Exception:  # noqa: BLE001 - фоновая задача не должна падать
            log.exception("Ошибка при обновлении просроченных задач")
        await asyncio.sleep(config.SWEEP_INTERVAL_SECONDS)


# ------------------------------------------------------------------------ корень


@app.get("/", tags=["service"])
def root() -> dict[str, Any]:
    return {
        "service": "Сервис контроля обещаний",
        "version": "1.0.0",
        "docs": "/docs",
        "endpoints": [
            "POST /webhook/calls — приём звонков от программы-отправителя",
            "GET /tasks — список задач с фильтрами",
            "PATCH /tasks/{id}/status — смена статуса",
            "POST /promise-types — добавление нового типа обещания",
            "GET /stats — сводка",
        ],
    }


@app.get("/health", tags=["service"])
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/dashboard", include_in_schema=False)
def dashboard() -> FileResponse:
    """Простая панель оператора: список задач, фильтры и смена статуса."""
    path = config.BASE_DIR / "static" / "dashboard.html"
    if not path.exists():
        raise HTTPException(status_code=404, detail="Панель не найдена")
    return FileResponse(path)


# ------------------------------------------------------------------------ звонки


@app.post("/webhook/calls", tags=["calls"])
async def webhook_calls(payload: Any = Body(...)) -> dict[str, Any]:
    """Основной вход: массив звонков (или {"calls": [...]}) от программы-отправителя."""
    return service.ingest(payload)


@app.post("/calls", tags=["calls"])
async def post_calls(payload: Any = Body(...)) -> dict[str, Any]:
    """Алиас вебхука: удобно, если отправщик настроен на /calls."""
    return service.ingest(payload)


@app.get("/calls", tags=["calls"])
def get_calls(limit: int = Query(50, ge=1, le=500), offset: int = Query(0, ge=0)) -> dict[str, Any]:
    return service.list_calls(limit, offset)


@app.get("/calls/{call_id}", tags=["calls"])
def get_call(call_id: str) -> dict[str, Any]:
    return service.get_call(call_id)


@app.post("/calls/{call_id}/reprocess", tags=["calls"])
def reprocess_call(call_id: str) -> dict[str, Any]:
    """Повторный разбор звонка: добавляет только новые задачи, дубли не создаёт."""
    return service.reprocess(call_id)


# ----------------------------------------------------------------------- задачи


@app.get("/tasks", tags=["tasks"])
def get_tasks(
    status: str | None = Query(None, description="created,in_progress,done,overdue (можно списком)"),
    operator_id: str | None = Query(None),
    type_code: str | None = Query(None),
    call_id: str | None = Query(None),
    due_before: str | None = Query(None, description="ISO-дата или unix-время"),
    due_after: str | None = Query(None),
    overdue: bool | None = Query(None),
    q: str | None = Query(None, description="Поиск по заголовку и цитате"),
    sort: str = Query("due_at", description="due_at | -due_at | created_at | -created_at"),
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
) -> dict[str, Any]:
    return service.list_tasks({
        "status": status, "operator_id": operator_id, "type_code": type_code, "call_id": call_id,
        "due_before": due_before, "due_after": due_after, "overdue": overdue, "q": q,
        "sort": sort, "limit": limit, "offset": offset,
    })


@app.get("/tasks/{task_id}", tags=["tasks"])
def get_task(task_id: int) -> dict[str, Any]:
    return service.get_task(task_id)


@app.patch("/tasks/{task_id}/status", tags=["tasks"])
def patch_status(task_id: int, body: StatusIn) -> dict[str, Any]:
    return service.change_status(task_id, body.status, body.note)


@app.post("/tasks/{task_id}/status", tags=["tasks"])
def post_status(task_id: int, body: StatusIn) -> dict[str, Any]:
    """Алиас PATCH — на случай, если клиент умеет только POST."""
    return service.change_status(task_id, body.status, body.note)


# -------------------------------------------------------------- типы обещаний


@app.get("/promise-types", tags=["promise-types"])
def get_types() -> dict[str, Any]:
    items = service.list_types()
    return {"items": items, "total": len(items)}


@app.post("/promise-types", status_code=201, tags=["promise-types"])
def add_type(body: PromiseTypeIn) -> dict[str, Any]:
    """Добавляет новый тип обещания по смысловому описанию."""
    return service.create_type(body.model_dump())


@app.patch("/promise-types/{code}", tags=["promise-types"])
def toggle_type(code: str, active: bool) -> dict[str, Any]:
    return service.set_type_active(code, active)


# ----------------------------------------------------------------------- сводка


@app.get("/stats", tags=["service"])
def get_stats() -> dict[str, Any]:
    return service.stats()

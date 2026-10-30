"""Сборка приложения FastAPI."""
from __future__ import annotations

import asyncio
import contextlib
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, PlainTextResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

from .api import analytics, auth as auth_api, calls, notifications as notifications_api, system, tasks, types
from .config import settings
from .db import connect, init_db
from .services import auth as auth_service
from .services import notifications as notify_service

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.auto_seed:
        _seed_if_empty()
    worker = asyncio.create_task(_notification_loop()) if settings.notify_enabled else None
    try:
        yield
    finally:
        if worker:
            worker.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await worker


def _seed_if_empty() -> None:
    """Публичное демо: если база пустая, загрузить сохранённый снимок звонков из API."""
    import json

    from .db import connect
    from .services.ingest import ingest_payload

    path = Path(__file__).resolve().parent.parent / "data" / "sample_calls.json"
    with connect() as conn:
        existing = conn.execute("SELECT COUNT(*) AS c FROM calls").fetchone()["c"]
        if existing or not path.exists():
            return
        calls = json.loads(path.read_text(encoding="utf-8"))
        result = ingest_payload(conn, calls)
    print(f"[auto-seed] звонков {result['received']}, задач {result['tasks_created']}")


async def _notification_loop() -> None:
    """Раз в минуту проверяет сроки и рассылает уведомления."""
    await asyncio.sleep(max(0, settings.notify_start_delay_seconds))
    while True:
        try:
            result = await asyncio.to_thread(_run_notification_cycle)
            if result["created"]:
                print(
                    f"[notify] уведомлений {result['created']}, писем {result['emails']}",
                    flush=True,
                )
        except Exception as error:  # планировщик не должен падать из-за одной ошибки
            print(f"[notify] ошибка: {error}", flush=True)
        await asyncio.sleep(max(5, settings.notify_interval_seconds))


def _run_notification_cycle() -> dict:
    with connect() as conn:
        return notify_service.run_cycle(conn)


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    description=(
        "Сервис контроля обещаний: принимает расшифровки звонков, находит обещания оператора, "
        "превращает их в задачи со сроком и ведёт статусы до выполнения.\n\n"
        "Кейс УралМикро, хакатон 2026."
    ),
    lifespan=lifespan,
)

# Демонстрационный сервис: фронтенд может обращаться к API с любого адреса.
# В продакшене список origin нужно сузить.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def guard_static_html(request, call_next):
    """HTML-страницы отдаются только маршрутами с проверкой входа.

    Иначе панель открывалась бы в обход шлюза по /static/index.html.
    """
    path = request.url.path.lower()
    if path.startswith("/static/") and path.endswith((".html", ".htm")):
        return PlainTextResponse("Страница доступна только через / и после входа", status_code=404)
    return await call_next(request)


@app.middleware("http")
async def no_cache_static(request, call_next):
    """Динамика не должна кэшироваться: иначе браузер держит старый JS и старые
    ответы API — панель показывает устаревшие цифры, а страница ломается."""
    response = await call_next(request)
    content_type = response.headers.get("content-type", "")
    path = request.url.path
    if path.startswith("/static/") or content_type.startswith("text/html"):
        response.headers["Cache-Control"] = "no-cache, must-revalidate"
    elif path.startswith("/api/") or path.startswith("/webhook/"):
        response.headers["Cache-Control"] = "no-store"
    return response


app.include_router(calls.router)
app.include_router(tasks.router)
app.include_router(types.router)
app.include_router(system.router)
app.include_router(analytics.router)
app.include_router(auth_api.router)
app.include_router(notifications_api.router)

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index(request: Request):
    """Панель открывается только после входа."""
    if not _current_employee(request):
        return RedirectResponse("/login?next=/", status_code=303)
    return FileResponse(WEB_DIR / "index.html")


@app.get("/analytics", include_in_schema=False)
def analytics_page(request: Request):
    employee = _current_employee(request)
    if not employee:
        return RedirectResponse("/login?next=/analytics", status_code=303)
    if employee.get("role") != "admin":
        return RedirectResponse("/?denied=analytics", status_code=303)
    return FileResponse(WEB_DIR / "analytics.html")


@app.get("/login", include_in_schema=False)
def login_page(request: Request):
    if _current_employee(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(WEB_DIR / "login.html")


@app.get("/register", include_in_schema=False)
def register_page(request: Request):
    if _current_employee(request):
        return RedirectResponse("/", status_code=303)
    return FileResponse(WEB_DIR / "register.html")


def _current_employee(request: Request) -> dict | None:
    conn = connect()
    try:
        return auth_service.employee_by_session(conn, request.cookies.get("sid"))
    finally:
        conn.close()

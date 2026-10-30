"""Сборка приложения FastAPI."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import analytics, calls, system, tasks, types
from .config import settings
from .db import init_db

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    if settings.auto_seed:
        _seed_if_empty()
    yield


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

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


@app.get("/analytics", include_in_schema=False)
def analytics_page() -> FileResponse:
    """Отдельная страница аналитики: не трогает основной интерфейс."""
    return FileResponse(WEB_DIR / "analytics.html")

"""Сборка приложения FastAPI."""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from .api import calls, system, tasks, types
from .config import settings
from .db import init_db

WEB_DIR = Path(__file__).resolve().parent / "web"


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    yield


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

app.include_router(calls.router)
app.include_router(tasks.router)
app.include_router(types.router)
app.include_router(system.router)

if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")

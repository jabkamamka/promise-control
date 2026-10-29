"""Настройки сервиса. Значения можно переопределять переменными окружения."""

from __future__ import annotations

import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

# Каталог для файла базы данных SQLite.
DATA_DIR = Path(os.getenv("PROMISE_DATA_DIR", BASE_DIR / "data"))

# Путь к файлу базы. По умолчанию data/promises.db рядом с проектом.
DB_PATH = Path(os.getenv("PROMISE_DB_PATH", DATA_DIR / "promises.db"))

# Часовой пояс, в котором трактуются «наивные» даты из звонков.
DEFAULT_TZ = os.getenv("PROMISE_TZ", "Asia/Yekaterinburg")

# Срок по умолчанию, если в разговоре срок не назван.
DEFAULT_DUE_HOURS = int(os.getenv("PROMISE_DEFAULT_DUE_HOURS", "24"))

# Как часто фоновая задача переводит просроченные задачи в статус overdue.
SWEEP_INTERVAL_SECONDS = int(os.getenv("PROMISE_SWEEP_INTERVAL", "30"))

# Опциональная LLM-проверка (OpenAI-совместимый endpoint). По умолчанию выключена.
LLM_BASE_URL = os.getenv("PROMISE_LLM_BASE_URL", "").rstrip("/")
LLM_API_KEY = os.getenv("PROMISE_LLM_API_KEY", "")
LLM_MODEL = os.getenv("PROMISE_LLM_MODEL", "")
LLM_TIMEOUT = float(os.getenv("PROMISE_LLM_TIMEOUT", "20"))


def ensure_dirs() -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)

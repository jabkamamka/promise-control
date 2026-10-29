"""Настройки сервиса.

Все значения читаются из переменных окружения (и из файла .env рядом с проектом).
Ничего обязательного нет: сервис запускается «из коробки» на SQLite и правилах.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent


def _load_dotenv(path: Path) -> None:
    """Минимальный загрузчик .env (без внешних зависимостей)."""
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        os.environ.setdefault(key, value)


_load_dotenv(BASE_DIR / ".env")


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    app_name: str = os.environ.get("APP_NAME", "Сервис контроля обещаний")
    app_version: str = "1.0.0"

    #: Путь к файлу БД SQLite. Можно указать :memory: в тестах.
    database_path: str = os.environ.get(
        "DATABASE_PATH", str(BASE_DIR / "data" / "promises.db")
    )

    #: Часовой пояс, в котором произносятся сроки («завтра в десять утра»).
    timezone: str = os.environ.get("APP_TIMEZONE", "Asia/Yekaterinburg")

    #: Срок по умолчанию, если в реплике не удалось найти дату (часы).
    default_due_hours: int = _env_int("DEFAULT_DUE_HOURS", 24)

    #: Горизонт «прямо сейчас» в минутах.
    immediate_minutes: int = _env_int("IMMEDIATE_MINUTES", 15)

    #: Необязательный общий секрет для вебхука: если задан, требуется заголовок X-Webhook-Token.
    webhook_token: str | None = os.environ.get("WEBHOOK_TOKEN") or None

    #: Необязательный LLM (OpenAI-совместимый). По умолчанию выключен.
    llm_enabled: bool = _env_bool("LLM_ENABLED", False)
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = os.environ.get("LLM_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    llm_timeout: float = float(os.environ.get("LLM_TIMEOUT", "25"))

    #: Ограничения выдачи списков.
    page_limit_default: int = 50
    page_limit_max: int = 200


settings = Settings()

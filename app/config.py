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

    #: API партнёра: откуда кнопка «Загрузить ещё из API» берёт свежие расшифровки.
    #: Без токена кнопка отключена, остальной сервис работает как обычно.
    api_base: str = os.environ.get("URALMICRO_API_BASE", "https://utmn-api.uralmicro.ru/api/v1")
    api_service_token: str = os.environ.get("URALMICRO_SERVICE_TOKEN", "").strip()

    #: Необязательный LLM (OpenAI-совместимый). По умолчанию выключен.
    llm_enabled: bool = _env_bool("LLM_ENABLED", False)
    llm_base_url: str = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
    llm_api_key: str = os.environ.get("LLM_API_KEY", "")
    llm_model: str = os.environ.get("LLM_MODEL", "gpt-4o-mini")
    llm_timeout: float = float(os.environ.get("LLM_TIMEOUT", "25"))

    #: Ограничения выдачи списков.
    page_limit_default: int = 50
    page_limit_max: int = 200

    #: Публичное демо на бесплатном хостинге: при пустой базе загрузить сохранённый
    #: снимок звонков из API (data/sample_calls.json). По умолчанию выключено.
    auto_seed: bool = _env_bool("AUTO_SEED", False)

    #: Адреса с правами администратора (через запятую). Им доступна аналитика.
    admin_emails: str = os.environ.get("ADMIN_EMAILS", "").strip()

    #: Публичный адрес сервиса: подставляется в ссылки внутри писем.
    public_base_url: str = os.environ.get("PUBLIC_BASE_URL", "http://127.0.0.1:8080")

    #: Внутренний мессенджер: куда складывать вложения и какие ограничения держать.
    chat_upload_dir: str = os.environ.get("CHAT_UPLOAD_DIR", str(BASE_DIR / "data" / "chat"))
    chat_max_upload_mb: int = _env_int("CHAT_MAX_UPLOAD_MB", 10)
    chat_message_max_chars: int = _env_int("CHAT_MESSAGE_MAX_CHARS", 4000)

    #: Напоминания сотрудникам: за сколько минут до срока и включены ли они.
    reminder_enabled: bool = _env_bool("REMINDER_ENABLED", True)
    reminder_minutes_before: int = _env_int("REMINDER_MINUTES_BEFORE", 60)

    #: Фоновая рассылка уведомлений (в интерфейс и на почту).
    notify_enabled: bool = _env_bool("NOTIFY_ENABLED", True)
    notify_interval_seconds: int = _env_int("NOTIFY_INTERVAL_SECONDS", 60)
    notify_start_delay_seconds: int = _env_int("NOTIFY_START_DELAY_SECONDS", 5)

    #: Почта: как отправлять письма.
    #: auto — SMTP, если задан SMTP_HOST, иначе файл в data/outbox (удобно без сети);
    #: smtp — только SMTP; file — только файл (письма не уходят наружу).
    email_enabled: bool = _env_bool("EMAIL_ENABLED", True)
    email_transport: str = os.environ.get("EMAIL_TRANSPORT", "auto").strip().lower()
    email_from: str = os.environ.get(
        "EMAIL_FROM", "Контроль обещаний <no-reply@promise-control.local>"
    )
    email_outbox: str = os.environ.get("EMAIL_OUTBOX", str(BASE_DIR / "data" / "outbox"))

    smtp_host: str = os.environ.get("SMTP_HOST", "")
    smtp_port: int = _env_int("SMTP_PORT", 0)
    smtp_user: str = os.environ.get("SMTP_USER", "")
    smtp_password: str = os.environ.get("SMTP_PASSWORD", "")
    #: starttls | ssl | none | auto (по домену почты)
    smtp_security: str = os.environ.get("SMTP_SECURITY", "auto").strip().lower()
    smtp_timeout: int = _env_int("SMTP_TIMEOUT", 15)

    #: Демо без реальных ящиков: все письма уходят на этот адрес.
    email_redirect_to: str = os.environ.get("EMAIL_REDIRECT_TO", "").strip()

    #: Переадресовывать только эти домены (через запятую). Пусто — переадресовывать всё.
    email_redirect_domains: str = os.environ.get("EMAIL_REDIRECT_DOMAINS", "").strip()


settings = Settings()

"""Общие фикстуры тестов.

Важно: переменные окружения выставляются ДО импорта приложения, потому что
настройки читаются один раз при импорте app.config.
"""
from __future__ import annotations

import os
from urllib.parse import urlparse
import tempfile

os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(prefix="promise-test-"), "test.db"))
os.environ.setdefault("APP_TIMEZONE", "Asia/Yekaterinburg")
os.environ.setdefault(
    "EMAIL_OUTBOX", os.path.join(tempfile.mkdtemp(prefix="promise-mail-"), "outbox")
)
os.environ["EMAIL_ENABLED"] = "1"
os.environ["EMAIL_TRANSPORT"] = "file"
# Никакой переадресации и SMTP из локального .env: письма должны уходить на адрес сотрудника.
os.environ["EMAIL_REDIRECT_TO"] = ""
os.environ["SMTP_HOST"] = ""
os.environ["SMTP_USER"] = ""
os.environ["SMTP_PASSWORD"] = ""
os.environ["NOTIFY_ENABLED"] = "0"  # планировщик не должен вмешиваться в тесты
os.environ["ADMIN_EMAILS"] = "admin@example.com"
os.environ.pop("WEBHOOK_TOKEN", None)
os.environ["LLM_ENABLED"] = "0"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.db import connect, init_db  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    init_db()
    with connect() as conn:
        conn.executescript(
            "DELETE FROM notifications; DELETE FROM task_events; DELETE FROM tasks; DELETE FROM calls;"
            "DELETE FROM sessions; DELETE FROM employees;"
            "DELETE FROM chat_attachments; DELETE FROM chat_messages; DELETE FROM chat_members;"
            "DELETE FROM chat_presence; DELETE FROM chat_channels WHERE is_default = 0;"
        )
        conn.execute("DELETE FROM promise_types WHERE is_builtin = 0")
        conn.commit()
    with TestClient(app) as test_client:
        yield test_client


@pytest.fixture()
def conn():
    init_db()
    connection = connect()
    connection.executescript("DELETE FROM task_events; DELETE FROM tasks; DELETE FROM calls;")
    connection.commit()
    try:
        yield connection
    finally:
        connection.close()


@pytest.fixture()
def sample_calls():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "sample_calls.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def extra_calls():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "sample_calls_extra.json"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.fixture()
def verification_calls():
    import json
    from pathlib import Path

    path = Path(__file__).resolve().parent.parent / "data" / "sample_verification.json"
    return json.loads(path.read_text(encoding="utf-8"))


def make_call(call_id="call-1", transcript=None, ended_at="2033-10-29T10:00:00Z", operator_id=7):
    return {
        "id": call_id,
        "operator_id": operator_id,
        "client_phone": "+70000000000",
        "started_at": "2033-10-29T09:56:00Z",
        "ended_at": ended_at,
        "transcript": transcript or [],
    }


def login_employee(client, email="tester@example.com", name="Тестовый Сотрудник"):
    """Регистрирует сотрудника и подтверждает почту по ссылке из письма."""
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "secret-pass", "full_name": name},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    assert data["needs_confirmation"] is True

    link = data.get("dev_link")
    assert link, "в файловом режиме ссылка подтверждения должна возвращаться"
    path = urlparse(link).path + "?" + urlparse(link).query
    confirmed = client.get(path, follow_redirects=False)
    assert confirmed.status_code == 303, confirmed.text

    employee = client.get("/auth/me").json()["employee"]
    assert employee is not None, "после подтверждения должна быть сессия"
    return employee


ADMIN_EMAIL = "admin@example.com"


def login_admin(client):
    """Регистрирует и подтверждает администратора (аналитика только ему)."""
    return login_employee(client, email=ADMIN_EMAIL, name="Администратор Смены")

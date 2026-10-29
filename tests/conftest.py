"""Общие фикстуры тестов.

Важно: переменные окружения выставляются ДО импорта приложения, потому что
настройки читаются один раз при импорте app.config.
"""
from __future__ import annotations

import os
import tempfile

os.environ.setdefault("DATABASE_PATH", os.path.join(tempfile.mkdtemp(prefix="promise-test-"), "test.db"))
os.environ.setdefault("APP_TIMEZONE", "Asia/Yekaterinburg")
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
        conn.executescript("DELETE FROM task_events; DELETE FROM tasks; DELETE FROM calls;")
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


def make_call(call_id="call-1", transcript=None, ended_at="2026-10-29T10:00:00Z", operator_id=7):
    return {
        "id": call_id,
        "operator_id": operator_id,
        "client_phone": "+70000000000",
        "started_at": "2026-10-29T09:56:00Z",
        "ended_at": ended_at,
        "transcript": transcript or [],
    }

"""Вход, сессия, тариф и реклама: сквозные проверки через API."""

from __future__ import annotations


def login(client, email: str = "operator@example.com"):
    """Просит ссылку и логинится по ней. Возвращает клиент с cookie."""
    response = client.post("/api/v1/auth/email/request", json={"email": email})
    assert response.status_code == 200
    body = response.json()
    assert body["delivery"] in {"dev", "smtp"}
    if body["delivery"] == "dev":
        assert body["dev_link"], "в dev-режиме ссылка должна возвращаться"
        confirm = client.get(body["dev_link"], follow_redirects=False)
        assert confirm.status_code == 303
    return client


def test_email_login_sets_session(client):
    login(client)
    me = client.get("/api/v1/auth/me").json()
    assert me["authenticated"] is True
    assert me["email"] == "operator@example.com"
    assert me["plan"] == "free"
    assert me["ads"] is True


def test_bad_email_rejected(client):
    response = client.post("/api/v1/auth/email/request", json={"email": "not-an-email"})
    assert response.status_code == 422


def test_billing_removes_ads(client):
    login(client)
    subscribed = client.post("/api/v1/billing/subscribe").json()
    assert subscribed["plan"] == "pro"
    assert subscribed["mock_payment"] is True

    me = client.get("/api/v1/auth/me").json()
    assert me["plan"] == "pro"
    assert me["ads"] is False

    client.post("/api/v1/billing/cancel")
    assert client.get("/api/v1/auth/me").json()["plan"] == "free"


def test_logout(client):
    login(client)
    client.post("/api/v1/auth/logout")
    assert client.get("/api/v1/auth/me").json()["authenticated"] is False


def test_telegram_code_login(client):
    from app.db import connect
    from app.services import users

    with connect() as conn:
        users.ensure_schema(conn)
        code = users.issue_telegram_code(conn, 555001)
        conn.commit()

    response = client.post("/api/v1/auth/telegram/claim", json={"code": code})
    assert response.status_code == 200
    me = client.get("/api/v1/auth/me").json()
    assert me["authenticated"] is True
    assert me["telegram_id"] == 555001


def test_telegram_code_is_one_time(client):
    from app.db import connect
    from app.services import users

    with connect() as conn:
        users.ensure_schema(conn)
        code = users.issue_telegram_code(conn, 555002)
        conn.commit()

    assert client.post("/api/v1/auth/telegram/claim", json={"code": code}).status_code == 200
    assert client.post("/api/v1/auth/telegram/claim", json={"code": code}).status_code == 400


def test_public_host_does_not_leak_dev_link(client):
    """На публичном домене dev-ссылка не возвращается: иначе вход без пароля."""
    response = client.post(
        "/api/v1/auth/email/request",
        json={"email": "someone@example.com"},
        headers={"host": "promise.example.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["delivery"] == "disabled"
    assert body["dev_link"] is None
    assert "Telegram" in body["message"]


def test_my_tasks_requires_login(client):
    assert client.get("/api/v1/me/tasks").status_code == 401


def test_operator_binding_filters_tasks(client):
    login(client, "op7@example.com")
    client.patch("/api/v1/me", json={"operator_id": 7})

    from tests.conftest import make_call

    call = make_call(call_id="acc-call", transcript=[
        {"speaker": "operator", "text": "Я перезвоню вам через час."},
    ])
    client.post("/webhook/calls", json=[call])

    tasks = client.get("/api/v1/me/tasks").json()
    assert tasks["operator_id"] == 7
    assert tasks["total"] >= 1
    assert all(item["operator_id"] == 7 for item in tasks["items"])

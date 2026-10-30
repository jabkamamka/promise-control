"""Сотрудники: регистрация по почте, вход, сессии, взятие задачи."""
from __future__ import annotations

from conftest import login_employee, make_call

CALLBACK = [{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]


def test_register_and_me(client):
    employee = login_employee(client, email="anna@example.com", name="Анна Смирнова")
    assert employee["email"] == "anna@example.com"
    assert employee["full_name"] == "Анна Смирнова"
    assert "telegram_id" not in employee

    me = client.get("/auth/me").json()
    assert me["employee"]["id"] == employee["id"]


def test_register_rejects_bad_email(client):
    response = client.post(
        "/auth/register",
        json={"email": "не-почта", "password": "secret-pass", "full_name": "Боб"},
    )
    assert response.status_code == 422


def test_register_rejects_short_password(client):
    response = client.post(
        "/auth/register",
        json={"email": "short@example.com", "password": "123", "full_name": "Боб"},
    )
    assert response.status_code == 422


def test_duplicate_email_rejected(client):
    login_employee(client, email="dup@example.com")
    response = client.post(
        "/auth/register",
        json={"email": "DUP@example.com", "password": "secret-pass", "full_name": "Дубль"},
    )
    assert response.status_code == 409


def test_email_is_case_insensitive(client):
    login_employee(client, email="Case@Example.com")
    client.post("/auth/logout", json={})
    response = client.post(
        "/auth/login", json={"email": "case@example.com", "password": "secret-pass"}
    )
    assert response.status_code == 200


def test_login_by_password(client):
    login_employee(client, email="pass@example.com")
    client.post("/auth/logout", json={})

    assert (
        client.post(
            "/auth/login", json={"email": "pass@example.com", "password": "nope"}
        ).status_code
        == 401
    )
    ok = client.post(
        "/auth/login", json={"email": "pass@example.com", "password": "secret-pass"}
    )
    assert ok.status_code == 200
    assert client.get("/auth/me").json()["employee"]["email"] == "pass@example.com"


def test_login_unknown_email(client):
    response = client.post(
        "/auth/login", json={"email": "nobody@example.com", "password": "secret-pass"}
    )
    assert response.status_code == 401


def test_logout(client):
    login_employee(client, email="out@example.com")
    assert client.post("/auth/logout", json={}).status_code == 200
    assert client.get("/auth/me").json()["employee"] is None


def test_telegram_endpoints_removed(client):
    assert client.post("/auth/codes", json={"kind": "register"}).status_code in (404, 405)
    assert client.post("/auth/login-code", json={"code": "123456"}).status_code in (404, 405)


def test_password_change_revokes_sessions(client):
    login_employee(client, email="change@example.com")
    response = client.post(
        "/auth/password",
        json={"current_password": "secret-pass", "new_password": "new-secret-pass"},
    )
    assert response.status_code == 200

    client.post("/auth/logout", json={})
    assert (
        client.post(
            "/auth/login", json={"email": "change@example.com", "password": "secret-pass"}
        ).status_code
        == 401
    )
    assert (
        client.post(
            "/auth/login", json={"email": "change@example.com", "password": "new-secret-pass"}
        ).status_code
        == 200
    )


def test_password_change_requires_login(client):
    response = client.post(
        "/auth/password", json={"current_password": "a", "new_password": "secret-pass"}
    )
    assert response.status_code == 401


def test_take_task_requires_login(client):
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    task = client.get("/api/v1/tasks").json()["items"][0]

    assert client.post(f"/api/v1/tasks/{task['id']}/take").status_code == 401
    assert client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"}).status_code == 401


def test_take_task_assigns_employee(client):
    login_employee(client, email="worker@example.com", name="Пётр Иванов")
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    task = client.get("/api/v1/tasks").json()["items"][0]

    taken = client.post(f"/api/v1/tasks/{task['id']}/take")
    assert taken.status_code == 200
    body = taken.json()
    assert body["status"] == "in_progress"
    assert body["assignee_name"] == "Пётр Иванов"
    assert body["taken_at"] is not None

    mine = client.get("/api/v1/tasks?assignee_id=me").json()
    assert mine["total"] == 1

    events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    assert any(e["event"] == "taken" for e in events)


def test_second_employee_cannot_steal_task(client):
    login_employee(client, email="first@example.com", name="Первый Сотрудник")
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    task = client.get("/api/v1/tasks").json()["items"][0]
    assert client.post(f"/api/v1/tasks/{task['id']}/take").status_code == 200
    client.post("/auth/logout", json={})

    login_employee(client, email="second@example.com", name="Второй Сотрудник")
    conflict = client.post(f"/api/v1/tasks/{task['id']}/take")
    assert conflict.status_code == 409
    assert "Первый Сотрудник" in conflict.json()["detail"]


def test_status_change_sets_assignee(client):
    login_employee(client, email="setter@example.com", name="Светлана Ким")
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    task = client.get("/api/v1/tasks").json()["items"][0]

    moved = client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"})
    assert moved.status_code == 200
    assert moved.json()["assignee_name"] == "Светлана Ким"

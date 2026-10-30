"""Профиль сотрудника: смена имени и почты, подтверждение нового адреса."""
from __future__ import annotations

import sqlite3
from urllib.parse import urlparse

from app.db import connect
from app.services import auth
from conftest import login_employee


def _employee_row(email: str) -> sqlite3.Row:
    with connect() as conn:
        return conn.execute("SELECT * FROM employees WHERE email = ?", (email,)).fetchone()


def test_change_name_only(client):
    login_employee(client, name="Старое Имя")

    response = client.patch("/auth/me", json={"full_name": "Новое Имя"})

    assert response.status_code == 200
    body = response.json()
    assert body["employee"]["full_name"] == "Новое Имя"
    assert body["employee"]["email"] == "tester@example.com"
    assert body["email_changed"] is False
    assert client.get("/auth/me").json()["employee"]["full_name"] == "Новое Имя"


def test_name_is_normalized_and_trimmed(client):
    login_employee(client, name="Старое Имя")

    body = client.patch("/auth/me", json={"full_name": "  Иван   Петров  "}).json()

    assert body["employee"]["full_name"] == "Иван Петров"


def test_short_name_is_rejected(client):
    login_employee(client)

    response = client.patch("/auth/me", json={"full_name": "Я"})

    assert response.status_code == 422


def test_change_email_requires_confirmation(client):
    login_employee(client)

    response = client.patch("/auth/me", json={"email": "new.address@example.com"})

    assert response.status_code == 200
    body = response.json()
    assert body["email_changed"] is True
    assert body["needs_confirmation"] is True
    assert body["employee"]["email"] == "new.address@example.com"
    assert body["employee"]["email_confirmed"] is False
    assert "Подтвердите" in body["message"]
    assert body.get("dev_link"), "в файловом режиме ссылка должна возвращаться"

    # сессия и роль переживают смену адреса
    me = client.get("/auth/me").json()["employee"]
    assert me["email"] == "new.address@example.com"
    assert me["role"] == "operator"

    with connect() as conn:
        token = conn.execute(
            "SELECT COUNT(*) AS c FROM login_tokens WHERE email = ? AND purpose = 'confirm'",
            ("new.address@example.com",),
        ).fetchone()["c"]
    assert token == 1, "должна быть выдана ссылка подтверждения на новый адрес"


def test_email_is_confirmed_by_link_from_letter(client):
    login_employee(client)
    link = client.patch("/auth/me", json={"email": "another@example.com"}).json()["dev_link"]

    path = urlparse(link).path + "?" + urlparse(link).query
    confirmed = client.get(path, follow_redirects=False)

    assert confirmed.status_code == 303
    me = client.get("/auth/me").json()["employee"]
    assert me["email"] == "another@example.com"
    assert me["email_confirmed"] is True


def test_taken_email_is_rejected(client):
    login_employee(client, email="first@example.com", name="Первый")
    client.post("/auth/logout")
    login_employee(client, email="second@example.com", name="Второй")

    response = client.patch("/auth/me", json={"email": "first@example.com"})

    assert response.status_code == 409
    assert "занят" in response.json()["detail"]
    assert client.get("/auth/me").json()["employee"]["email"] == "second@example.com"


def test_invalid_email_is_rejected(client):
    login_employee(client)

    response = client.patch("/auth/me", json={"email": "не-почта"})

    assert response.status_code == 422


def test_same_email_does_not_reset_confirmation(client):
    login_employee(client)

    body = client.patch("/auth/me", json={"email": "TESTER@example.com"}).json()

    assert body["email_changed"] is False
    assert body["employee"]["email_confirmed"] is True


def test_empty_patch_is_rejected(client):
    login_employee(client)

    response = client.patch("/auth/me", json={})

    assert response.status_code == 400


def test_profile_requires_login(client):
    response = client.patch("/auth/me", json={"full_name": "Кто-то"})

    assert response.status_code == 401


def test_update_profile_service_keeps_confirmation_for_name(conn):
    employee = auth.register(conn, "svc@example.com", "password123", "Сергей Тестов")
    conn.execute("UPDATE employees SET email_confirmed_at = '2026-10-30T09:00:00Z' WHERE id = ?", (employee["id"],))
    conn.commit()
    fresh = conn.execute("SELECT * FROM employees WHERE id = ?", (employee["id"],)).fetchone()

    updated, email_changed = auth.update_profile(conn, dict(fresh), full_name="Сергей Новый")

    assert email_changed is False
    assert updated["full_name"] == "Сергей Новый"
    assert updated["email_confirmed_at"] == "2026-10-30T09:00:00Z"

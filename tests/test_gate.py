"""Шлюз авторизации: без входа страницы сайта недоступны."""
from __future__ import annotations

from conftest import login_admin, login_employee


def test_page_requires_login(client):
    for path in ("/", "/analytics"):
        response = client.get(path, follow_redirects=False)
        assert response.status_code == 303, path
        assert response.headers["location"].startswith("/login?next="), path


def test_login_page_is_open(client):
    assert client.get("/login", follow_redirects=False).status_code == 200
    assert client.get("/register", follow_redirects=False).status_code == 200


def test_pages_open_after_login(client):
    login_employee(client, email="gate@example.com")
    assert client.get("/", follow_redirects=False).status_code == 200
    # аналитика — только администратору
    denied = client.get("/analytics", follow_redirects=False)
    assert denied.status_code == 303
    assert denied.headers["location"] == "/?denied=analytics"


def test_analytics_page_for_admin(client):
    login_admin(client)
    assert client.get("/analytics", follow_redirects=False).status_code == 200


def test_login_page_redirects_when_logged_in(client):
    login_employee(client, email="gate2@example.com")
    response = client.get("/login", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"


def test_pages_close_after_logout(client):
    login_employee(client, email="gate3@example.com")
    assert client.get("/", follow_redirects=False).status_code == 200
    assert client.post("/auth/logout", json={}).status_code == 200
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"].startswith("/login")


def test_next_keeps_target(client):
    response = client.get("/analytics", follow_redirects=False)
    assert response.headers["location"] == "/login?next=/analytics"

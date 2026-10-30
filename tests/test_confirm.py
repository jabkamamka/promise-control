"""Обязательное подтверждение почты при регистрации."""
from __future__ import annotations

from urllib.parse import urlparse


def register(client, email="confirm@example.com", name="Новый Сотрудник"):
    response = client.post(
        "/auth/register",
        json={"email": email, "password": "secret-pass", "full_name": name},
    )
    assert response.status_code == 200, response.text
    data = response.json()
    link = data["dev_link"]
    parsed = urlparse(link)
    return data, parsed.path + "?" + parsed.query


def test_register_does_not_log_in(client):
    data, _path = register(client)
    assert data["needs_confirmation"] is True
    assert data["employee"]["email_confirmed"] is False
    assert client.get("/auth/me").json()["employee"] is None


def test_password_login_blocked_before_confirmation(client):
    register(client, email="blocked@example.com")
    response = client.post(
        "/auth/login", json={"email": "blocked@example.com", "password": "secret-pass"}
    )
    assert response.status_code == 403
    assert "не подтверждена" in response.json()["detail"]


def test_confirm_link_opens_panel(client):
    _data, path = register(client, email="opened@example.com")
    response = client.get(path, follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/?confirmed=1"

    me = client.get("/auth/me").json()["employee"]
    assert me["email"] == "opened@example.com"
    assert me["email_confirmed"] is True


def test_confirmed_account_can_login_by_password(client):
    _data, path = register(client, email="later@example.com")
    client.get(path, follow_redirects=False)
    client.post("/auth/logout", json={})

    response = client.post(
        "/auth/login", json={"email": "later@example.com", "password": "secret-pass"}
    )
    assert response.status_code == 200
    assert response.json()["employee"]["email_confirmed"] is True


def test_confirm_link_is_single_use(client):
    _data, path = register(client, email="once-confirm@example.com")
    assert client.get(path, follow_redirects=False).status_code == 303
    second = client.get(path, follow_redirects=False)
    assert second.status_code == 303
    assert "/login" in second.headers["location"]


def test_resend_replaces_link(client):
    _data, first = register(client, email="resend@example.com")
    resent = client.post("/auth/email/resend-confirm", json={"email": "resend@example.com"})
    assert resent.status_code == 200
    assert resent.json()["ok"] is True

    second = urlparse(resent.json()["dev_link"])
    assert client.get(first, follow_redirects=False).headers["location"].startswith("/login")
    assert (
        client.get(second.path + "?" + second.query, follow_redirects=False).status_code == 303
    )


def test_resend_is_silent_for_unknown_email(client):
    response = client.post("/auth/email/resend-confirm", json={"email": "nobody@example.com"})
    assert response.status_code == 200
    assert response.json()["ok"] is True
    assert "dev_link" not in response.json()


def test_link_login_confirms_password_account(client):
    _data, _path = register(client, email="viacode@example.com")
    start = client.post("/auth/email/start", json={"email": "viacode@example.com"})
    assert start.status_code == 200
    code = start.json()["dev_code"]

    logged = client.post(
        "/auth/email/verify", json={"email": "viacode@example.com", "code": code}
    )
    assert logged.status_code == 200
    assert logged.json()["employee"]["email_confirmed"] is True

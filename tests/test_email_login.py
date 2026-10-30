"""Вход по ссылке на почту: без пароля, одноразово, с кодом на случай копирования."""
from __future__ import annotations

from email import policy
from email.parser import BytesParser
from pathlib import Path
from urllib.parse import urlparse

from app.config import settings


def outbox_letters() -> list[dict]:
    letters = []
    for path in sorted(Path(settings.email_outbox).glob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body = message.get_body(preferencelist=("plain",))
        html = message.get_body(preferencelist=("html",))
        letters.append(
            {
                "to": str(message["To"]),
                "subject": str(message["Subject"]),
                "text": body.get_content() if body else "",
                "html": html.get_content() if html else "",
            }
        )
    return letters


def start(client, email: str, name: str | None = None) -> dict:
    payload = {"email": email}
    if name:
        payload["full_name"] = name
    response = client.post("/auth/email/start", json=payload)
    assert response.status_code == 200, response.text
    data = response.json()
    # Ссылка в письме абсолютная (PUBLIC_BASE_URL), а тестовый клиент живёт на testserver.
    parsed = urlparse(data["dev_link"])
    data["dev_path"] = parsed.path + ("?" + parsed.query if parsed.query else "")
    return data


def test_start_sends_link_and_code(client):
    data = start(client, "link@example.com")
    assert data["ok"] is True
    assert data["created"] is True
    assert data["email_status"] == "file"
    assert data["dev_link"].startswith(settings.public_base_url)
    assert len(data["dev_code"]) == 6

    letter = [row for row in outbox_letters() if row["to"] == "link@example.com"][-1]
    assert "Вход в «Контроль обещаний»" in letter["subject"]
    assert "Войти в сервис" in letter["html"]
    assert data["dev_code"] in letter["text"]
    assert "15 минут" in letter["text"]


def test_login_by_link_creates_session(client):
    data = start(client, "bylink@example.com")
    response = client.get(data["dev_path"], follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert client.get("/auth/me").json()["employee"]["email"] == "bylink@example.com"


def test_login_by_code(client):
    data = start(client, "bycode@example.com")
    response = client.post(
        "/auth/email/verify", json={"email": "bycode@example.com", "code": data["dev_code"]}
    )
    assert response.status_code == 200, response.text
    assert response.json()["employee"]["email"] == "bycode@example.com"


def test_wrong_code_has_attempts(client):
    start(client, "attempts@example.com")
    response = client.post(
        "/auth/email/verify", json={"email": "attempts@example.com", "code": "000000"}
    )
    assert response.status_code == 400
    assert "Осталось попыток" in response.json()["detail"]


def test_link_is_single_use(client):
    data = start(client, "once-link@example.com")
    assert client.get(data["dev_path"], follow_redirects=False).status_code == 303
    second = client.get(data["dev_path"], follow_redirects=False)
    assert second.status_code == 303
    assert "/login" in second.headers["location"]


def test_code_is_single_use(client):
    data = start(client, "once-code@example.com")
    payload = {"email": "once-code@example.com", "code": data["dev_code"]}
    assert client.post("/auth/email/verify", json=payload).status_code == 200
    client.post("/auth/logout", json={})
    assert client.post("/auth/email/verify", json=payload).status_code == 400


def test_new_link_invalidates_previous(client):
    first = start(client, "refresh@example.com")
    second = start(client, "refresh@example.com")
    assert first["dev_link"] != second["dev_link"]
    assert client.get(first["dev_path"], follow_redirects=False).status_code == 303
    assert "/login" in client.get(first["dev_path"], follow_redirects=False).headers["location"]
    assert (
        client.post(
            "/auth/email/verify", json={"email": "refresh@example.com", "code": second["dev_code"]}
        ).status_code
        == 200
    )


def test_rate_limit(client):
    start(client, "flood@example.com")
    start(client, "flood@example.com")
    start(client, "flood@example.com")
    response = client.post("/auth/email/start", json={"email": "flood@example.com"})
    assert response.status_code == 429


def test_existing_employee_uses_same_account(client):
    first = start(client, "same@example.com", "Анна Смирнова")
    client.get(first["dev_path"], follow_redirects=False)
    client.post("/auth/logout", json={})
    second = start(client, "same@example.com")
    assert second["created"] is False
    assert second["employee"]["full_name"] == "Анна Смирнова"


def test_name_from_email_for_new_employee(client):
    data = start(client, "ivan.petrov@example.com")
    assert data["employee"]["full_name"] == "Ivan Petrov"


def test_bad_email_rejected(client):
    assert client.post("/auth/email/start", json={"email": "не-почта"}).status_code == 422


def test_expired_link_rejected(client):
    from app.db import connect
    from app.utils import utc_now

    data = start(client, "expired@example.com")
    with connect() as conn:
        conn.execute(
            "UPDATE login_tokens SET expires_at = ? WHERE email = ?",
            (utc_now(), "expired@example.com"),
        )
        conn.commit()
    response = client.get(data["dev_path"], follow_redirects=False)
    assert response.status_code == 303
    assert "error=400" in response.headers["location"]

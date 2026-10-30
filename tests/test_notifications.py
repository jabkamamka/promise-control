"""Уведомления: в интерфейсе и на почте, без дублей."""
from __future__ import annotations

import datetime as dt
from email import policy
from email.parser import BytesParser
from pathlib import Path

from app.config import settings
from conftest import login_employee

SOON = [{"speaker": "operator", "text": "Перезвоню вам через тридцать минут и скажу сроки."}]
FAR = [{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]


def outbox_letters() -> list[dict]:
    """Разобранные письма из outbox: кому, тема, текст."""
    letters = []
    for path in sorted(Path(settings.email_outbox).glob("*.eml")):
        message = BytesParser(policy=policy.default).parsebytes(path.read_bytes())
        body = message.get_body(preferencelist=("plain",))
        letters.append(
            {
                "to": str(message["To"]),
                "subject": str(message["Subject"]),
                "text": body.get_content() if body else "",
            }
        )
    return letters


def call_in(call_id: str, transcript, minutes_from_now: int) -> dict:
    ended = dt.datetime.now(dt.timezone.utc) + dt.timedelta(minutes=minutes_from_now)
    started = ended - dt.timedelta(minutes=4)
    return {
        "id": call_id,
        "operator_id": 7,
        "client_phone": "+70000000000",
        "started_at": started.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "ended_at": ended.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "transcript": transcript,
    }


def take_first(client) -> dict:
    task = client.get("/api/v1/tasks?limit=1").json()["items"][0]
    return client.post(f"/api/v1/tasks/{task['id']}/take").json()


def test_notifications_require_login(client):
    assert client.get("/api/v1/notifications").status_code == 401
    assert client.post("/api/v1/notifications/scan").status_code == 401


def test_soon_deadline_creates_site_and_email(client):
    login_employee(client, email="soon@example.com", name="Скоро Сотрудник")
    client.post("/webhook/calls", json=[call_in("c-soon", SOON, 0)])
    task = take_first(client)

    result = client.post("/api/v1/notifications/scan").json()
    assert result["created"] == 1
    assert result["emails"] == 1

    data = client.get("/api/v1/notifications").json()
    assert data["unread"] == 1
    item = data["items"][0]
    assert item["kind"] == "deadline_soon"
    assert item["task_id"] == task["id"]
    assert "Срок через" in item["title"]
    assert item["link"] == f"/?task={task['id']}"
    assert item["email_status"] == "file"

    outbox = Path(settings.email_outbox)
    letters = outbox_letters()
    assert letters, "письмо должно быть записано в outbox"
    letter = letters[-1]
    assert letter["to"] == "soon@example.com"
    assert "Срок через" in letter["subject"]
    assert task["title"] in letter["subject"]
    assert outbox.exists()


def test_email_contains_task_and_link(client):
    login_employee(client, email="letter@example.com", name="Иван Петров")
    client.post("/webhook/calls", json=[call_in("c-letter", SOON, 0)])
    task = take_first(client)
    client.post("/api/v1/notifications/scan")

    letters = [item for item in outbox_letters() if item["to"] == "letter@example.com"]
    assert letters, "письмо сотруднику не найдено"
    text = letters[-1]["text"]
    assert "Здравствуйте, Иван" in text
    assert "/?task=" + task["id"] in text
    assert "Срок:" in text


def test_far_deadline_makes_no_notification(client):
    login_employee(client, email="far@example.com")
    client.post("/webhook/calls", json=[call_in("c-far", FAR, 0)])
    take_first(client)

    result = client.post("/api/v1/notifications/scan").json()
    assert result["created"] == 0
    assert client.get("/api/v1/notifications").json()["items"] == []


def test_no_notification_without_assignee(client):
    login_employee(client, email="free@example.com")
    client.post("/webhook/calls", json=[call_in("c-free", SOON, 0)])
    assert client.post("/api/v1/notifications/scan").json()["created"] == 0


def test_notification_is_not_duplicated(client):
    login_employee(client, email="once@example.com")
    client.post("/webhook/calls", json=[call_in("c-once", SOON, 0)])
    take_first(client)

    first = client.post("/api/v1/notifications/scan").json()
    assert first["created"] == 1

    second = client.post("/api/v1/notifications/scan").json()
    assert second["created"] == 0
    assert second["already"] == 1

    assert len(client.get("/api/v1/notifications").json()["items"]) == 1


def test_overdue_notification(client):
    login_employee(client, email="late@example.com")
    # звонок был 2 часа назад, обещали через 30 минут → срок прошёл
    client.post("/webhook/calls", json=[call_in("c-late", SOON, -120)])
    task = take_first(client)
    assert task["effective_status"] == "overdue"

    result = client.post("/api/v1/notifications/scan").json()
    assert result["created"] == 1
    item = client.get("/api/v1/notifications").json()["items"][0]
    assert item["kind"] == "overdue"
    assert "Срок истёк" in item["title"]


def test_done_task_is_not_notified(client):
    login_employee(client, email="done@example.com")
    client.post("/webhook/calls", json=[call_in("c-done", SOON, 0)])
    task = take_first(client)
    client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})

    assert client.post("/api/v1/notifications/scan").json()["created"] == 0


def test_mark_read_and_counter(client):
    login_employee(client, email="read@example.com")
    client.post("/webhook/calls", json=[call_in("c-read", SOON, 0)])
    take_first(client)
    client.post("/api/v1/notifications/scan")

    listing = client.get("/api/v1/notifications").json()
    assert listing["unread"] == 1

    marked = client.post("/api/v1/notifications/read", json={}).json()
    assert marked["marked"] == 1
    assert marked["unread"] == 0

    assert client.get("/api/v1/notifications?unread=1").json()["items"] == []


def test_notifications_are_personal(client):
    login_employee(client, email="one@example.com", name="Первый")
    client.post("/webhook/calls", json=[call_in("c-one", SOON, 0)])
    take_first(client)
    client.post("/api/v1/notifications/scan")
    client.post("/auth/logout", json={})

    login_employee(client, email="two@example.com", name="Второй")
    data = client.get("/api/v1/notifications").json()
    assert data["items"] == []
    assert data["unread"] == 0

"""Тесты внутреннего мессенджера."""
from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient

from app.main import app
from conftest import login_employee


@contextmanager
def other_employee(email: str, name: str):
    """Второй сотрудник со своей сессией (отдельный TestClient)."""
    with TestClient(app) as client:
        employee = login_employee(client, email=email, name=name)
        yield client, employee


def bootstrap(client) -> dict:
    response = client.get("/chat/bootstrap")
    assert response.status_code == 200, response.text
    return response.json()


def conversation_id(client, kind="direct", peer_ids=None, title="") -> int:
    response = client.post(
        "/chat/conversations",
        json={"kind": kind, "title": title, "employee_ids": peer_ids or []},
    )
    assert response.status_code == 200, response.text
    return response.json()["conversation"]["id"]


def messages(client, channel_id: int, **params) -> dict:
    response = client.get(f"/chat/conversations/{channel_id}/messages", params=params)
    return response


def send(client, channel_id: int, body: str, **extra) -> dict:
    response = client.post(
        f"/chat/conversations/{channel_id}/messages", json={"body": body, **extra}
    )
    assert response.status_code == 200, response.text
    return response.json()["message"]


def test_chat_requires_login(client):
    assert client.get("/chat", follow_redirects=False).status_code == 303
    assert client.get("/chat/bootstrap").status_code == 401
    assert client.get("/chat/summary").status_code == 401


def test_default_channels_for_new_employee(client):
    login_employee(client)
    data = bootstrap(client)
    assert data["me"]["full_name"] == "Тестовый Сотрудник"
    kinds = {item["kind"] for item in data["conversations"]}
    assert kinds == {"channel"}
    titles = {item["title"] for item in data["conversations"]}
    assert {"Общий", "Операторы", "Срочное"} <= titles
    assert data["totals"] == {"unread": 0, "mentions": 0}
    assert data["timezone"] == "Asia/Yekaterinburg"


def test_direct_dialog_and_reply(client):
    me = login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        first = conversation_id(client, peer_ids=[peer["id"]])
        again = conversation_id(client, peer_ids=[peer["id"]])
        assert first == again, "личный диалог не должен дублироваться"

        message = send(client, first, "Привет, Пётр!")
        assert message["body"] == "Привет, Пётр!"
        assert message["sender"]["id"] == me["id"]

        peer_data = bootstrap(peer_client)
        direct = next(item for item in peer_data["conversations"] if item["id"] == first)
        assert direct["title"] == "Тестовый Сотрудник"
        assert direct["unread"] == 1

        peer_messages = messages(peer_client, first)
        assert peer_messages.status_code == 200
        assert peer_messages.json()["messages"][-1]["body"] == "Привет, Пётр!"

        read = peer_client.post(f"/chat/conversations/{first}/read", json={"message_id": message["id"]})
        assert read.status_code == 200

        seen = messages(client, first).json()
        assert seen["read_up_to"] >= message["id"]
        assert bootstrap(peer_client)["totals"]["unread"] == 0

        reply = send(peer_client, first, "Привет!", reply_to=message["id"])
        assert reply["reply_to"]["body"] == "Привет, Пётр!"
        assert reply["reply_to"]["sender_name"] == "Тестовый Сотрудник"

        updates = messages(client, first, after_id=message["id"]).json()
        assert [item["id"] for item in updates["messages"]] == [reply["id"]]
        assert updates["read_up_to"] >= reply["id"]


def test_edit_and_delete_permissions(client):
    login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        channel = conversation_id(client, peer_ids=[peer["id"]])
        message = send(client, channel, "Черновик")

        denied = peer_client.patch(f"/chat/messages/{message['id']}", json={"body": "Взлом"})
        assert denied.status_code == 403

        edited = client.patch(f"/chat/messages/{message['id']}", json={"body": "Готово"})
        assert edited.status_code == 200
        assert edited.json()["message"]["body"] == "Готово"
        assert edited.json()["message"]["edited_at"]

        deleted = client.delete(f"/chat/messages/{message['id']}")
        assert deleted.status_code == 200
        assert deleted.json()["deleted"] is True

        after = messages(peer_client, channel).json()["messages"][-1]
        assert after["deleted"] is True
        assert after["body"] == ""
        assert peer_client.delete(f"/chat/messages/{message['id']}").status_code == 404


def test_group_access_and_membership(client):
    login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        with other_employee("third@example.com", "Светлана Сидорова") as (third_client, third):
            group = conversation_id(
                client, kind="group", title="Смена утра", peer_ids=[peer["id"]]
            )
            assert messages(peer_client, group).status_code == 200
            assert messages(third_client, group).status_code == 403

            denied = peer_client.post(
                f"/chat/conversations/{group}/members", json={"employee_ids": [third["id"]]}
            )
            assert denied.status_code == 403, "приглашать может только владелец"

            added = client.post(
                f"/chat/conversations/{group}/members", json={"employee_ids": [third["id"]]}
            )
            assert added.status_code == 200
            assert messages(third_client, group).status_code == 200

            send(client, group, "Всем привет")
            assert bootstrap(third_client)["totals"]["unread"] >= 1

            left = peer_client.post(f"/chat/conversations/{group}/leave")
            assert left.status_code == 200
            assert messages(peer_client, group).status_code == 403


def test_mentions_are_counted(client):
    login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        group = conversation_id(client, kind="group", title="Задачи", peer_ids=[peer["id"]])
        send(client, group, "@Пётр Петров посмотри задачу", mentions=[peer["id"]])
        data = bootstrap(peer_client)
        item = next(conv for conv in data["conversations"] if conv["id"] == group)
        assert item["mentions"] == 1
        assert data["totals"]["mentions"] == 1


def test_search_respects_membership(client):
    login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        with other_employee("third@example.com", "Светлана Сидорова") as (third_client, third):
            channel = conversation_id(client, peer_ids=[peer["id"]])
            send(client, channel, "Уникальное слово флокуляция")
            found = client.get("/chat/search", params={"q": "флокуляция"})
            assert found.status_code == 200
            assert found.json()["results"][0]["channel_id"] == channel
            assert found.json()["results"][0]["sender_name"] == "Тестовый Сотрудник"
            assert third_client.get("/chat/search", params={"q": "флокуляция"}).json()["results"] == []


def test_attachment_roundtrip_and_blocked_types(client):
    login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        channel = conversation_id(client, peer_ids=[peer["id"]])
        response = client.post(
            f"/chat/conversations/{channel}/attachments",
            params={"filename": "смета.txt", "caption": "Смотрите смету"},
            content="строка 1\nстрока 2".encode("utf-8"),
            headers={"Content-Type": "text/plain"},
        )
        assert response.status_code == 200, response.text
        message = response.json()["message"]
        attachment = message["attachment"]
        assert attachment["filename"] == "смета.txt"
        assert attachment["size"] > 0
        assert message["body"] == "Смотрите смету"

        downloaded = peer_client.get(attachment["url"])
        assert downloaded.status_code == 200
        assert downloaded.content.startswith("строка 1".encode("utf-8"))

        denied = client.post(
            f"/chat/conversations/{channel}/attachments",
            params={"filename": "page.html"},
            content=b"<script>alert(1)</script>",
            headers={"Content-Type": "text/html"},
        )
        assert denied.status_code == 415

        svg = client.post(
            f"/chat/conversations/{channel}/attachments",
            params={"filename": "logo.svg"},
            content=b"<svg></svg>",
            headers={"Content-Type": "image/svg+xml"},
        )
        assert svg.status_code == 415


def test_typing_and_mute(client):
    login_employee(client)
    with other_employee("peer@example.com", "Пётр Петров") as (peer_client, peer):
        channel = conversation_id(client, peer_ids=[peer["id"]])
        assert peer_client.post(f"/chat/conversations/{channel}/typing").status_code == 200
        assert "Пётр Петров" in messages(client, channel).json()["typing"]

        send(peer_client, channel, "Есть вопрос")
        assert bootstrap(client)["totals"]["unread"] == 1
        muted = client.post(f"/chat/conversations/{channel}/mute", json={"muted": True})
        assert muted.status_code == 200
        assert muted.json()["conversation"]["muted"] is True
        assert bootstrap(client)["totals"]["unread"] == 0

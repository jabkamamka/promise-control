"""Совместимость с настоящей программой-отправителем.

Схема взята из бинарника sender_windows_amd64.exe (JSON-теги Go-структур):
    id, operator_id:int64, client_phone, started_at, ended_at,
    transcript: [{speaker, text}]

Тест фиксирует, что сервис принимает именно такой payload и не ломается на
числовом operator_id.
"""

from datetime import datetime, timedelta, timezone


def sender_call(call_id: str = "sender-001") -> dict:
    end = datetime.now(timezone.utc) - timedelta(minutes=5)
    return {
        "id": call_id,
        "operator_id": 101,
        "client_phone": "+7 912 345-67-89",
        "started_at": (end - timedelta(minutes=6)).isoformat(),
        "ended_at": end.isoformat(),
        "transcript": [
            {"speaker": "оператор", "text": "УралМикро, Анна, добрый день."},
            {"speaker": "клиент", "text": "Здравствуйте, нужен счёт."},
            {"speaker": "оператор", "text": "Я перезвоню вам через час и отправлю счёт на почту."},
        ],
    }


def test_sender_payload_is_accepted(client):
    response = client.post("/webhook/calls", json=[sender_call()])
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["tasks_created"] == 2

    call = client.get("/calls/sender-001").json()
    assert call["operator_id"] == "101"
    assert call["phone"] == "+7 912 345-67-89"
    assert [s["role"] for s in call["segments"]] == ["operator", "client", "operator"]


def test_sender_payload_is_idempotent(client):
    client.post("/webhook/calls", json=[sender_call("sender-002")])
    again = client.post("/webhook/calls", json=[sender_call("sender-002")]).json()
    assert again["duplicates"] == 1
    assert again["tasks_created"] == 0

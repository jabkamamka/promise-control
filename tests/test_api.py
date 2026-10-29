"""Сквозные тесты API: приём звонков, задачи, статусы, фильтры, новые типы."""

from datetime import datetime, timedelta, timezone

CALL = {
    "id": "call-001",
    "operator_id": "op-1",
    "phone": "+7 900 000-00-01",
    "started_at": "2026-10-29T14:58:00+05:00",
    "ended_at": "2026-10-29T15:00:00+05:00",
    "transcript": [
        {"role": "operator", "text": "Добрый день, это Анна из УралМикро."},
        {"role": "client", "text": "Здравствуйте, хочу уточнить по счёту."},
        {"role": "operator", "text": "Я перезвоню вам через час и отправлю договор на почту."},
    ],
}

OLD_CALL = {
    "id": "call-old",
    "operator_id": "op-2",
    "phone": "+7 900 000-00-02",
    "started_at": "2026-10-27T09:28:00+05:00",
    "ended_at": "2026-10-27T09:30:00+05:00",
    "transcript": [
        {"role": "operator", "text": "Уточню информацию и вернусь с ответом до конца дня."},
    ],
}


def test_webhook_creates_tasks_and_is_idempotent(client):
    response = client.post("/webhook/calls", json=[CALL])
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["tasks_created"] == 2

    again = client.post("/webhook/calls", json=[CALL]).json()
    assert again["duplicates"] == 1
    assert again["tasks_created"] == 0

    tasks = client.get("/tasks").json()
    assert tasks["total"] == 2


def test_filters_and_status_flow(client):
    client.post("/webhook/calls", json=[CALL])
    tasks = client.get("/tasks", params={"operator_id": "op-1", "status": "created"}).json()["items"]
    assert len(tasks) == 2

    task_id = tasks[0]["id"]
    started = client.patch(f"/tasks/{task_id}/status", json={"status": "in_progress", "note": "Взял в работу"})
    assert started.status_code == 200
    assert started.json()["status"] == "in_progress"

    done = client.patch(f"/tasks/{task_id}/status", json={"status": "done"})
    assert done.json()["status"] == "done"

    history = client.get(f"/tasks/{task_id}").json()["events"]
    assert [e["to_status"] for e in history] == ["created", "in_progress", "done"]


def test_overdue_is_set_automatically(client):
    client.post("/webhook/calls", json=[OLD_CALL])
    items = client.get("/tasks", params={"operator_id": "op-2"}).json()["items"]
    assert items and items[0]["status"] == "overdue"
    assert items[0]["status_label"] == "Просрочена"


def test_manual_overdue_is_rejected(client):
    client.post("/webhook/calls", json=[CALL])
    task_id = client.get("/tasks").json()["items"][0]["id"]
    response = client.patch(f"/tasks/{task_id}/status", json={"status": "overdue"})
    assert response.status_code == 409


def test_illegal_transition(client):
    client.post("/webhook/calls", json=[CALL])
    task_id = client.get("/tasks").json()["items"][0]["id"]
    client.patch(f"/tasks/{task_id}/status", json={"status": "done"})
    response = client.patch(f"/tasks/{task_id}/status", json={"status": "done"})
    assert response.status_code == 200  # идемпотентно


def test_new_promise_type_by_semantic_description(client):
    created = client.post("/promise-types", json={
        "name": "Переключить на отдел",
        "description": "Оператор обещает соединить клиента с профильным специалистом.",
        "keywords": ["переключу", "соединю"],
        "action": "Соединить клиента со специалистом",
    })
    assert created.status_code == 201
    code = created.json()["code"]

    call = dict(CALL, id="call-002", transcript=[
        {"role": "operator", "text": "Сейчас переключу вас на отдел продаж."},
    ])
    client.post("/webhook/calls", json=[call])
    items = client.get("/tasks", params={"type_code": code}).json()
    assert items["total"] == 1


def test_stats(client):
    client.post("/webhook/calls", json=[CALL, OLD_CALL])
    stats = client.get("/stats").json()
    assert stats["calls_total"] == 2
    assert stats["tasks_total"] == 3
    assert stats["by_status"]["Просрочена"] == 1


def test_bad_payload(client):
    assert client.post("/webhook/calls", json={"foo": "bar"}).status_code == 422
    assert client.post("/webhook/calls", json=[{"operator_id": "x"}]).json()["errors"]

"""Сквозные тесты API: приём звонков, задачи, статусы, фильтры, новые типы.

Время звонков считается от текущего момента, иначе тесты начнут падать,
когда «сегодняшние» звонки из фикстуры окажутся в прошлом.
"""

from datetime import datetime, timedelta, timezone


def make_call(call_id: str = "call-001", operator: str = "op-1",
              minutes_ago: int = 2, transcript: list[dict] | None = None) -> dict:
    end = datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)
    start = end - timedelta(minutes=2)
    return {
        "id": call_id,
        "operator_id": operator,
        "phone": "+7 900 000-00-01",
        "started_at": start.isoformat(timespec="seconds"),
        "ended_at": end.isoformat(timespec="seconds"),
        "transcript": transcript or [
            {"role": "operator", "text": "Добрый день, это Анна из УралМикро."},
            {"role": "client", "text": "Здравствуйте, хочу уточнить по счёту."},
            {"role": "operator", "text": "Я перезвоню вам через час и отправлю договор на почту."},
        ],
    }


def make_old_call() -> dict:
    return make_call(
        call_id="call-old",
        operator="op-2",
        minutes_ago=60 * 48,
        transcript=[{
            "role": "operator",
            "text": "Уточню информацию и вернусь с ответом до конца дня.",
        }],
    )


def test_webhook_creates_tasks_and_is_idempotent(client):
    response = client.post("/webhook/calls", json=[make_call()])
    assert response.status_code == 200
    body = response.json()
    assert body["accepted"] == 1
    assert body["tasks_created"] == 2

    again = client.post("/webhook/calls", json=[make_call()]).json()
    assert again["duplicates"] == 1
    assert again["tasks_created"] == 0

    tasks = client.get("/tasks").json()
    assert tasks["total"] == 2


def test_filters_and_status_flow(client):
    call = make_call()
    client.post("/webhook/calls", json=[call])
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
    client.post("/webhook/calls", json=[make_old_call()])
    items = client.get("/tasks", params={"operator_id": "op-2"}).json()["items"]
    assert items and items[0]["status"] == "overdue"
    assert items[0]["status_label"] == "Просрочена"


def test_manual_overdue_is_rejected(client):
    client.post("/webhook/calls", json=[make_call()])
    task_id = client.get("/tasks").json()["items"][0]["id"]
    response = client.patch(f"/tasks/{task_id}/status", json={"status": "overdue"})
    assert response.status_code == 409


def test_done_is_idempotent(client):
    client.post("/webhook/calls", json=[make_call()])
    task_id = client.get("/tasks").json()["items"][0]["id"]
    client.patch(f"/tasks/{task_id}/status", json={"status": "done"})
    response = client.patch(f"/tasks/{task_id}/status", json={"status": "done"})
    assert response.status_code == 200


def test_new_promise_type_by_semantic_description(client):
    created = client.post("/promise-types", json={
        "name": "Переключить на отдел",
        "description": "Оператор обещает соединить клиента с профильным специалистом.",
        "keywords": ["переключу", "соединю"],
        "action": "Соединить клиента со специалистом",
    })
    assert created.status_code == 201
    code = created.json()["code"]

    call = make_call("call-002", transcript=[
        {"role": "operator", "text": "Сейчас переключу вас на отдел продаж."},
    ])
    client.post("/webhook/calls", json=[call])
    items = client.get("/tasks", params={"type_code": code}).json()
    assert items["total"] == 1


def test_stats(client):
    client.post("/webhook/calls", json=[make_call(), make_old_call()])
    stats = client.get("/stats").json()
    assert stats["calls_total"] == 2
    assert stats["tasks_total"] == 3
    assert stats["by_status"]["Просрочена"] == 1


def test_bad_payload(client):
    assert client.post("/webhook/calls", json={"foo": "bar"}).status_code == 422
    response = client.post("/webhook/calls", json=[{"operator_id": "x"}])
    assert response.status_code == 200
    assert response.json()["errors"]

"""Сквозные тесты API: вебхук → задачи → статусы → фильтры."""
from __future__ import annotations

import datetime as dt

from conftest import login_employee, make_call

CALLBACK = [{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]
DOCS = [{"speaker": "operator", "text": "Отправлю счёт на почту сегодня."}]


def test_webhook_batch_creates_tasks(client):
    payload = [
        make_call("c-1", CALLBACK),
        make_call("c-2", DOCS, operator_id=8),
    ]
    response = client.post("/webhook/calls", json=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["received"] == 2
    assert body["processed"] == 2
    assert body["tasks_created"] == 2

    tasks = client.get("/api/v1/tasks").json()
    assert tasks["total"] == 2
    assert {t["call_id"] for t in tasks["items"]} == {"c-1", "c-2"}


def test_webhook_is_idempotent(client):
    payload = [make_call("c-1", CALLBACK)]
    first = client.post("/webhook/calls", json=payload).json()
    second = client.post("/webhook/calls", json=payload).json()

    assert first["tasks_created"] == 1
    assert second["duplicates"] == 1
    assert second["tasks_created"] == 0
    assert client.get("/api/v1/tasks").json()["total"] == 1


def test_webhook_accepts_single_call_and_wrapper(client):
    single = client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    assert single.status_code == 200 and single.json()["processed"] == 1

    wrapped = client.post("/webhook/calls", json={"calls": [make_call("c-2", DOCS)]})
    assert wrapped.status_code == 200 and wrapped.json()["processed"] == 1


def test_webhook_rejects_unknown_shape(client):
    assert client.post("/webhook/calls", json={"foo": 1}).status_code == 400


def test_broken_call_does_not_break_batch(client):
    payload = [make_call("c-1", CALLBACK), {"operator_id": 1, "transcript": []}]
    body = client.post("/webhook/calls", json=payload).json()
    assert body["processed"] == 1
    assert body["failed"] == 1
    assert body["calls"][1]["status"] == "error"


def test_status_flow_and_events(client):
    login_employee(client)
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    task = client.get("/api/v1/tasks").json()["items"][0]
    task_id = task["id"]
    assert task["status"] == "created"
    assert task["effective_status"] == "created"

    in_progress = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "in_progress"})
    assert in_progress.status_code == 200
    assert in_progress.json()["status"] == "in_progress"

    done = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done", "comment": "Перезвонил"})
    assert done.status_code == 200
    assert done.json()["closed_at"] is not None

    events = client.get(f"/api/v1/tasks/{task_id}/events").json()
    changed = [e["to_status"] for e in events if e["event"] == "status_changed"]
    assert changed == ["in_progress", "done"]
    assert any(e["event"] == "created" for e in events)
    assert any(e["event"] == "taken" for e in events)
    assert events[-1]["comment"] == "Перезвонил"


def test_invalid_transition_is_rejected(client):
    login_employee(client)
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    task_id = client.get("/api/v1/tasks").json()["items"][0]["id"]

    response = client.patch(f"/api/v1/tasks/{task_id}", json={"status": "done"})
    assert response.status_code == 409
    assert "запрещён" in response.json()["detail"]


def test_unknown_task_returns_404(client):
    login_employee(client)
    assert client.get("/api/v1/tasks/nope").status_code == 404
    assert client.patch("/api/v1/tasks/nope", json={"status": "in_progress"}).status_code == 404


def test_filters_by_type_operator_and_text(client):
    client.post(
        "/webhook/calls",
        json=[
            make_call("c-1", CALLBACK, operator_id=10),
            make_call("c-2", DOCS, operator_id=11),
        ],
    )
    by_type = client.get("/api/v1/tasks?type=documents").json()
    assert by_type["total"] == 1
    assert by_type["items"][0]["call_id"] == "c-2"

    by_operator = client.get("/api/v1/tasks?operator_id=10").json()
    assert by_operator["total"] == 1
    assert by_operator["items"][0]["call_id"] == "c-1"

    by_text = client.get("/api/v1/tasks?q=счёт").json()
    assert by_text["total"] == 1


def test_overdue_is_computed_and_logged(client):
    old_end = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ")
    call = make_call(
        "c-old",
        [{"speaker": "operator", "text": "Перезвоню вам через час."}],
        ended_at=old_end,
    )
    client.post("/webhook/calls", json=[call])

    overdue = client.get("/api/v1/tasks?status=overdue").json()
    assert overdue["total"] == 1
    task = overdue["items"][0]
    assert task["effective_status"] == "overdue"
    assert task["is_overdue"] is True

    events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    assert any(e["event"] == "overdue" for e in events)

    assert client.get("/api/v1/tasks?status=created").json()["total"] == 0


def test_deadline_filters(client):
    client.post("/webhook/calls", json=[make_call("c-1", CALLBACK)])
    future = "2034-12-31T00:00:00Z"
    assert client.get(f"/api/v1/tasks?due_before={future}").json()["total"] == 1
    assert client.get("/api/v1/tasks?due_before=2020-01-01T00:00:00Z").json()["total"] == 0


def test_types_crud(client):
    types = client.get("/api/v1/promise-types").json()
    assert len(types) == 7
    assert {t["code"] for t in types} >= {"callback", "documents", "clarification"}

    created = client.post(
        "/api/v1/promise-types",
        json={
            "title": "Согласовать скидку",
            "description": "Оператор обещает согласовать скидку с руководителем и вернуться",
            "keywords": ["скидк", "согласую"],
            "examples": ["Согласую скидку и перезвоню"],
        },
    )
    assert created.status_code == 201
    code = created.json()["code"]
    assert code == "soglasovat-skidku"

    duplicate = client.post("/api/v1/promise-types", json={"code": code, "title": "Дубль"})
    assert duplicate.status_code == 409

    assert client.delete(f"/api/v1/promise-types/{code}").status_code == 204
    assert client.delete("/api/v1/promise-types/callback").status_code == 409


def test_reanalyze_is_idempotent(client):
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    before = client.get("/api/v1/tasks").json()["total"]
    result = client.post("/api/v1/calls/c-1/reanalyze").json()
    assert result["tasks_created"] == 0
    assert client.get("/api/v1/tasks").json()["total"] == before
    assert client.post("/api/v1/calls/unknown/reanalyze").status_code == 404


def test_call_detail_contains_transcript_and_tasks(client):
    client.post("/webhook/calls", json=make_call("c-1", CALLBACK))
    call = client.get("/api/v1/calls/c-1").json()
    assert call["promise_count"] == 1
    assert len(call["transcript"]) == 1
    assert len(call["tasks"]) == 1
    assert call["tasks"][0]["promise_type"] == "callback"


def test_compat_aliases(client):
    login_employee(client)
    alias = client.post("/calls", json=make_call("c-alias", CALLBACK))
    assert alias.status_code == 200
    assert alias.json()["processed"] == 1

    task_id = client.get("/api/v1/tasks").json()["items"][0]["id"]
    moved = client.patch(f"/api/v1/tasks/{task_id}/status", json={"status": "in_progress"})
    assert moved.status_code == 200
    assert moved.json()["status"] == "in_progress"


def test_stats_and_health(client):
    client.post("/webhook/calls", json=[make_call("c-1", CALLBACK), make_call("c-2", DOCS)])
    stats = client.get("/api/v1/stats").json()
    assert stats["calls_total"] == 2
    assert stats["tasks_total"] == 2
    assert stats["by_status"]["created"] == 2
    assert stats["by_type"]["callback"] == 1

    health = client.get("/health").json()
    assert health["status"] == "ok"
    assert health["types"] == 7

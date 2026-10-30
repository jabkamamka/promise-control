"""Проверка исполнения обещаний по следующим звонкам клиента."""
from __future__ import annotations
from conftest import login_employee  # noqa: E402

import sqlite3

from app.db import _migrate
from app.services.verify import find_evidence

PHONE = "+79990000001"
OTHER_PHONE = "+79990000002"

CALLBACK_QUOTE = "Перезвоню вам завтра в десять утра."
DOCS_QUOTE = "Отправлю счёт на почту сегодня."


def _call(
    call_id: str,
    transcript: list[dict[str, str]],
    *,
    phone: str = PHONE,
    started: str,
    ended: str,
) -> dict:
    return {
        "id": call_id,
        "operator_id": 7,
        "client_phone": phone,
        "started_at": started,
        "ended_at": ended,
        "transcript": transcript,
    }


def _first_call(quote: str = CALLBACK_QUOTE, *, phone: str = PHONE, call_id: str = "c-1") -> dict:
    return _call(
        call_id,
        [{"speaker": "operator", "text": quote}],
        phone=phone,
        started="2033-10-29T10:00:00Z",
        ended="2033-10-29T10:05:00Z",
    )


def _follow_up(
    text: str,
    *,
    phone: str = PHONE,
    call_id: str = "c-2",
    started: str = "2033-10-30T09:00:00Z",
    ended: str = "2033-10-30T09:02:00Z",
) -> dict:
    return _call(
        call_id,
        [{"speaker": "client", "text": text}],
        phone=phone,
        started=started,
        ended=ended,
    )


def _task_by_call(client, call_id: str) -> dict:
    items = client.get("/api/v1/tasks?limit=200").json()["items"]
    return next(task for task in items if task["call_id"] == call_id)


def test_confirmed_promise_is_closed_and_logged(client):
    body = client.post(
        "/webhook/calls",
        json=[_first_call(), _follow_up("Да, перезвонили, спасибо.")],
    ).json()
    assert body["tasks_verified"] == 1

    task = _task_by_call(client, "c-1")
    assert task["promise_type"] == "callback"
    assert task["status"] == "done"
    assert task["effective_status"] == "done"
    assert task["verification_status"] == "confirmed"
    assert task["verified_call_id"] == "c-2"
    assert "перезвонили" in task["verification_quote"]
    assert task["closed_at"] is not None

    events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    verified = [event for event in events if event["event"] == "verified"]
    assert len(verified) == 1
    assert verified[0]["from_status"] == "created"
    assert verified[0]["to_status"] == "done"
    assert "c-2" in verified[0]["comment"]

    stats = client.get("/api/v1/stats").json()
    assert stats["by_verification"]["confirmed"] == 1
    assert stats["not_fulfilled"] == 0


def test_refuted_promise_is_not_fulfilled(client):
    body = client.post(
        "/webhook/calls",
        json=[
            _first_call(DOCS_QUOTE),
            _follow_up(
                "Мне обещали выставить счёт за октябрь, а он не пришёл.",
                started="2033-11-05T09:00:00Z",
                ended="2033-11-05T09:02:00Z",
            ),
        ],
    ).json()
    assert body["tasks_verified"] == 1

    task = _task_by_call(client, "c-1")
    assert task["promise_type"] == "documents"
    assert task["status"] == "created"
    assert task["effective_status"] == "not_fulfilled"
    assert task["is_overdue"] is False
    assert task["verification_status"] == "refuted"
    assert task["verified_call_id"] == "c-2"

    events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    verified = [event for event in events if event["event"] == "verified"]
    assert len(verified) == 1
    assert verified[0]["to_status"] is None
    assert "не исполнено" in verified[0]["comment"]

    assert client.get("/api/v1/tasks?status=not_fulfilled").json()["total"] == 1
    assert client.get("/api/v1/tasks?status=overdue").json()["total"] == 0
    assert client.get("/api/v1/tasks?status=created").json()["total"] == 0
    assert client.get("/api/v1/tasks?verification=refuted").json()["total"] == 1
    assert client.get("/api/v1/tasks?verification=confirmed").json()["total"] == 0
    assert client.get("/api/v1/tasks?verification=pending").json()["total"] == 0

    stats = client.get("/api/v1/stats").json()
    assert stats["not_fulfilled"] == 1
    assert stats["overdue"] == 0
    assert stats["by_verification"]["refuted"] == 1


def test_unclear_reply_keeps_task_open(client):
    client.post(
        "/webhook/calls",
        json=[
            _first_call(),
            _follow_up(
                "Получилось, спасибо.",
                started="2033-10-29T12:00:00Z",
                ended="2033-10-29T12:02:00Z",
            ),
        ],
    )

    task = _task_by_call(client, "c-1")
    assert task["status"] == "created"
    assert task["effective_status"] == "created"
    assert task["verification_status"] is None
    assert task["verified_call_id"] is None
    assert client.get("/api/v1/tasks?verification=pending").json()["total"] == 1

    events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    assert not any(event["event"] == "verified" for event in events)


def test_refutation_wins_over_confirmation(client):
    client.post(
        "/webhook/calls",
        json=[_first_call(), _follow_up("Перезвонили, но не дозвонились.")],
    )
    task = _task_by_call(client, "c-1")
    assert task["verification_status"] == "refuted"
    assert task["effective_status"] == "not_fulfilled"


def test_questions_imperatives_and_operator_words_are_ignored(client):
    client.post(
        "/webhook/calls",
        json=[
            _first_call(),
            _call(
                "c-2",
                [
                    {"speaker": "client", "text": "Вы мне перезвонили?"},
                    {"speaker": "operator", "text": "Да, перезвонили, спасибо."},
                    {"speaker": "client", "text": "Давайте проверим, что мастер приехал."},
                ],
                started="2033-10-30T09:00:00Z",
                ended="2033-10-30T09:02:00Z",
            ),
        ],
    )
    task = _task_by_call(client, "c-1")
    assert task["verification_status"] is None
    assert task["status"] == "created"


def test_other_phone_does_not_verify(client):
    client.post(
        "/webhook/calls",
        json=[_first_call(), _follow_up("Да, перезвонили, спасибо.", phone=OTHER_PHONE)],
    )
    task = _task_by_call(client, "c-1")
    assert task["verification_status"] is None
    assert task["status"] == "created"


def test_visit_is_confirmed_while_unrelated_fix_stays_open(client):
    client.post(
        "/webhook/calls",
        json=[
            _call(
                "c-1",
                [
                    {"speaker": "operator", "text": "Оформлю повторный выезд мастера завтра."},
                    {"speaker": "operator", "text": "Исправлю адрес в заказе в течение дня."},
                ],
                started="2033-10-29T10:00:00Z",
                ended="2033-10-29T10:05:00Z",
            ),
            _follow_up("Мастер приезжал, но ничего не сделал."),
        ],
    )
    tasks = client.get("/api/v1/tasks?limit=200").json()["items"]
    by_type = {task["promise_type"]: task for task in tasks if task["call_id"] == "c-1"}
    assert by_type["visit"]["verification_status"] == "confirmed"
    assert by_type["visit"]["status"] == "done"
    assert by_type["fix"]["verification_status"] is None
    assert by_type["fix"]["status"] == "created"


def test_latest_open_task_of_type_is_verified(client):
    client.post(
        "/webhook/calls",
        json=[
            _first_call(),
            _call(
                "c-2",
                [{"speaker": "operator", "text": "Перезвоню вам в пятницу в три часа."}],
                started="2033-10-30T09:00:00Z",
                ended="2033-10-30T09:05:00Z",
            ),
            _follow_up(
                "Да, перезвонили, спасибо.",
                call_id="c-3",
                started="2033-11-01T09:00:00Z",
                ended="2033-11-01T09:02:00Z",
            ),
        ],
    )
    first = _task_by_call(client, "c-1")
    second = _task_by_call(client, "c-2")
    assert first["verification_status"] is None
    assert second["verification_status"] == "confirmed"
    assert second["status"] == "done"


def test_out_of_order_calls_are_verified(client):
    body = client.post(
        "/webhook/calls",
        json=[
            _follow_up("Да, перезвонили, спасибо."),
            _first_call(),
        ],
    ).json()
    assert body["tasks_verified"] == 1

    task = _task_by_call(client, "c-1")
    assert task["verification_status"] == "confirmed"
    assert task["status"] == "done"


def test_replay_does_not_duplicate_verification(client):
    payload = [_first_call(), _follow_up("Да, перезвонили, спасибо.")]
    client.post("/webhook/calls", json=payload)
    task = _task_by_call(client, "c-1")
    before = client.get(f"/api/v1/tasks/{task['id']}/events").json()

    repeat = client.post("/webhook/calls", json=payload).json()
    assert repeat["duplicates"] == 2
    assert repeat["tasks_verified"] == 0
    after = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    assert [event["event"] for event in after] == [event["event"] for event in before]
    assert sum(1 for event in after if event["event"] == "verified") == 1


def test_done_task_is_not_verified(client):
    login_employee(client)
    client.post("/webhook/calls", json=[_first_call()])
    task = _task_by_call(client, "c-1")
    client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "in_progress"})
    client.patch(f"/api/v1/tasks/{task['id']}", json={"status": "done"})

    client.post("/webhook/calls", json=[_follow_up("Да, перезвонили, спасибо.")])
    task = _task_by_call(client, "c-1")
    assert task["status"] == "done"
    assert task["verification_status"] is None
    events = client.get(f"/api/v1/tasks/{task['id']}/events").json()
    assert not any(event["event"] == "verified" for event in events)


def test_evidence_guards():
    def evidence(text: str, type_code: str = "callback"):
        return find_evidence([{"speaker": "client", "text": text}], type_code)

    assert evidence("Вы мне перезвонили?") is None
    assert evidence("Да, перезвонили, спасибо.") is not None
    assert evidence("Мне вчера обещали позвонить, и тишина").status == "refuted"
    assert evidence("Перезвонили, но не дозвонились.").status == "refuted"
    assert evidence("Получилось, спасибо.") is None

    assert evidence("Счёт пришёл, спасибо.", "documents").status == "confirmed"
    refute = evidence("Мне обещали выставить счёт за октябрь, а он не пришёл.", "documents")
    assert refute.status == "refuted"
    assert evidence("Мы подали заявление на перерасчёт, ответа нет.", "documents") is None

    assert evidence("Мастер приезжал, но ничего не сделал.", "visit").status == "confirmed"
    assert evidence("Давайте проверим, что мастер действительно приехал.", "visit") is None
    assert evidence("Мастер не приехал.", "visit").status == "refuted"


def test_migration_adds_verification_columns():
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("CREATE TABLE tasks (id TEXT PRIMARY KEY)")
    _migrate(conn)
    _migrate(conn)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(tasks)")}
    assert {
        "verification_status",
        "verified_at",
        "verified_call_id",
        "verification_quote",
    } <= columns
    conn.close()

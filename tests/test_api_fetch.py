"""Кнопка «Загрузить ещё из API»: порция 10–20 задач, отсев повторов, ошибки."""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services import api_source
from app.services.ingest import ingest_payload
from conftest import login_employee

#: Четыре реплики с разными типами обещаний: короткий звонок даёт до четырёх задач.
PROMISES = [
    "Перезвоню вам завтра в десять утра.",
    "Отправлю счёт на почту сегодня.",
    "Уточню у логистов и вернусь с ответом завтра.",
    "Исправлю адрес прямо сейчас.",
]


def api_call(index: int, promises: int = 3, call_id: str | None = None) -> dict:
    """Звонок в формате API.

    Свой телефон и своя первая реплика на каждый звонок: иначе проверка исполнения
    склеит клиентов, а отсев повторов примет разные звонки за один и тот же разговор.
    """
    transcript = [{"speaker": "client", "text": f"Здравствуйте, у меня вопрос номер {index}."}]
    transcript += [{"speaker": "operator", "text": text} for text in PROMISES[:promises]]
    return {
        "id": call_id or f"API{index:04d}",
        "operator_id": 3 + index % 10,
        "client_phone": f"+7900{index:07d}",
        "started_at": "2026-10-30T09:00:00Z",
        "ended_at": "2026-10-30T09:05:00Z",
        "transcript": transcript,
    }


# ------------------------------- сервисный слой -------------------------------


def test_pull_lands_between_10_and_20_tasks(conn):
    pages = [api_call(i) for i in range(12)]

    batch = api_source.pull(conn, 10, 15, 20, fetcher=lambda attempts: pages)

    assert 10 <= batch["planned"] <= 20
    assert 0 < len(batch["calls"]) < len(pages), "порция должна быть меньше всей выдачи API"
    # предсказание детектора не должно расходиться с реальностью
    created = ingest_payload(conn, batch["calls"])["tasks_created"]
    assert created == batch["planned"]


def test_pull_never_exceeds_max(conn):
    pages = [api_call(i, promises=4) for i in range(12)]

    batch = api_source.pull(conn, 10, 15, 20, fetcher=lambda attempts: pages)

    assert batch["planned"] <= 20


def test_pull_skips_calls_already_known_by_text(conn):
    known = api_call(0, call_id="already-here")
    ingest_payload(conn, [known])
    same_talk_new_id = {**known, "id": "same-text-new-id", "client_phone": "+79009999999"}

    batch = api_source.pull(
        conn, 10, 15, 20, fetcher=lambda attempts: [same_talk_new_id]
    )

    assert batch["calls"] == []
    assert batch["planned"] == 0


def test_pull_skips_known_ids(conn):
    known = api_call(0)
    ingest_payload(conn, [known])

    batch = api_source.pull(conn, 10, 15, 20, fetcher=lambda attempts: [known])

    assert batch["calls"] == []


def test_pull_rejects_broken_range(conn):
    with pytest.raises(ValueError):
        api_source.pull(conn, 20, 15, 10, fetcher=lambda attempts: [])


def test_pull_asks_api_again_when_first_batch_is_poor(conn):
    """Первый ответ API бедный — сервис добирает порцию вторым заходом."""
    calls = {"count": 0}

    def fetcher(attempts: int):
        calls["count"] += 1
        if calls["count"] == 1:
            return [api_call(0, promises=1)]
        return [api_call(i) for i in range(1, 12)]

    batch = api_source.pull(conn, 10, 15, 20, fetcher=fetcher)

    assert calls["count"] == 2
    assert 10 <= batch["planned"] <= 20


def test_fetch_and_ingest_returns_webhook_report(conn, monkeypatch):
    pages = [api_call(i) for i in range(12)]
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: pages)

    batch = api_source.fetch_and_ingest(conn, 10, 15, 20)
    assert batch["ingest"] is not None
    assert batch["ingest"]["tasks_created"] == batch["planned"]

    # API отдаёт только уже загруженные записи — второй заход ничего не пишет
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: pages[: batch["ingest"]["processed"]])
    second = api_source.fetch_and_ingest(conn, 10, 15, 20)
    assert second["ingest"] is None
    total = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
    assert total == batch["ingest"]["tasks_created"]


# ---------------------------------- HTTP-слой ----------------------------------


def test_fetch_api_requires_login(client):
    response = client.post("/api/v1/calls/fetch-api")
    assert response.status_code == 401


def test_fetch_api_without_token_is_disabled(client, monkeypatch):
    login_employee(client)
    monkeypatch.setattr(
        api_source,
        "settings",
        SimpleNamespace(api_base="https://example.invalid/api/v1", api_service_token=""),
    )

    response = client.post("/api/v1/calls/fetch-api")

    assert response.status_code == 503
    assert "URALMICRO_SERVICE_TOKEN" in response.json()["detail"]


def test_fetch_api_reports_unavailable_api(client, monkeypatch):
    login_employee(client)

    def broken(attempts: int):
        raise api_source.ApiSourceError("API недоступен: соединение отклонено")

    monkeypatch.setattr(api_source, "fetch_calls", broken)

    response = client.post("/api/v1/calls/fetch-api")

    assert response.status_code == 502
    assert "API недоступен" in response.json()["detail"]


def test_fetch_api_creates_10_to_20_tasks(client, monkeypatch):
    login_employee(client)
    pages = [api_call(i) for i in range(12)]
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: pages)

    response = client.post("/api/v1/calls/fetch-api")

    assert response.status_code == 200
    body = response.json()
    assert 10 <= body["tasks_created"] <= 20
    assert body["selected"] == body["processed"]
    assert body["duplicates"] == 0
    assert "задач" in body["message"]
    assert client.get("/api/v1/tasks").json()["total"] == body["tasks_created"]


def test_fetch_api_second_click_does_not_duplicate(client, monkeypatch):
    login_employee(client)
    pages = [api_call(i) for i in range(12)]
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: pages)

    first = client.post("/api/v1/calls/fetch-api").json()
    assert first["tasks_created"] >= 10

    # API повторно отдал те же записи, что уже загружены: новых задач быть не должно
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: pages[: first["selected"]])
    second = client.post("/api/v1/calls/fetch-api").json()

    assert second["tasks_created"] == 0
    assert second["selected"] == 0
    assert second["skipped"] == second["fetched"]
    assert "нет новых" in second["message"]
    assert client.get("/api/v1/tasks").json()["total"] == first["tasks_created"]


def test_fetch_api_next_click_takes_other_calls(client, monkeypatch):
    """Повторное нажатие добирает из API другие расшифровки, а не те же самые."""
    login_employee(client)
    pages = [api_call(i) for i in range(12)]
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: pages)

    first = client.post("/api/v1/calls/fetch-api").json()
    second = client.post("/api/v1/calls/fetch-api").json()

    total = client.get("/api/v1/tasks").json()["total"]
    assert second["tasks_created"] >= 10
    assert total == first["tasks_created"] + second["tasks_created"]
    calls = client.get("/api/v1/calls?limit=200").json()["items"]
    texts = [str(call["transcript"]) for call in calls]
    assert len(set(texts)) == len(texts), "один и тот же разговор не должен грузиться дважды"


def test_fetch_api_validates_range(client, monkeypatch):
    login_employee(client)
    monkeypatch.setattr(api_source, "fetch_calls", lambda attempts: [])

    response = client.post("/api/v1/calls/fetch-api?min_tasks=20&max_tasks=10")

    assert response.status_code == 400

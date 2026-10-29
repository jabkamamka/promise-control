"""Прогон на реальных 52 расшифровках из API УралМикро (данные синтетические)."""
from __future__ import annotations


def test_full_corpus_is_processed(client, sample_calls):
    assert len(sample_calls) == 52

    response = client.post("/webhook/calls", json=sample_calls)
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == 52
    assert body["failed"] == 0

    tasks = client.get("/api/v1/tasks?limit=200").json()
    assert tasks["total"] >= 120

    by_type = {}
    for task in tasks["items"]:
        by_type[task["promise_type"]] = by_type.get(task["promise_type"], 0) + 1

    # три обязательных типа из кейса должны встречаться в реальных данных
    assert by_type.get("callback", 0) > 0
    assert by_type.get("documents", 0) > 0
    assert by_type.get("clarification", 0) > 0

    per_call = {}
    for task in tasks["items"]:
        per_call[task["call_id"]] = per_call.get(task["call_id"], 0) + 1
    assert len(per_call) == 52
    assert min(per_call.values()) >= 1
    assert 2 <= sum(per_call.values()) / 52 <= 6

    # у каждой задачи есть цитата, срок и тип
    assert all(task["quote"] for task in tasks["items"])
    assert all(task["due_at"] for task in tasks["items"])
    assert all(task["promise_type"] for task in tasks["items"])


def test_second_pass_creates_no_duplicates(client, sample_calls):
    client.post("/webhook/calls", json=sample_calls)
    total_before = client.get("/api/v1/tasks?limit=1").json()["total"]

    repeat = client.post("/webhook/calls", json=sample_calls).json()
    assert repeat["duplicates"] == 52
    assert repeat["tasks_created"] == 0
    assert client.get("/api/v1/tasks?limit=1").json()["total"] == total_before


def test_stats_reflect_corpus(client, sample_calls):
    client.post("/webhook/calls", json=sample_calls)
    stats = client.get("/api/v1/stats").json()
    assert stats["calls_total"] == 52
    assert stats["tasks_total"] >= 120
    assert stats["avg_promises_per_call"] >= 2

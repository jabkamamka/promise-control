"""Дополнительная выборка из API: 48 звонков, собранных после основного набора.

Проверяем устойчивость на данных, которых не было при разработке детектора:
разметка типов и сроков не должна ломаться на новых комбинациях реплик.
"""
from __future__ import annotations

from collections import Counter


def test_extra_corpus_is_processed(client, extra_calls):
    assert len(extra_calls) >= 40

    response = client.post("/webhook/calls", json=extra_calls)
    assert response.status_code == 200
    body = response.json()
    assert body["processed"] == len(extra_calls)
    assert body["failed"] == 0
    assert body["duplicates"] == 0


def test_extra_corpus_produces_valid_tasks(client, extra_calls):
    client.post("/webhook/calls", json=extra_calls)
    tasks = client.get("/api/v1/tasks?limit=200").json()

    assert tasks["total"] >= len(extra_calls)
    per_call = Counter(task["call_id"] for task in tasks["items"])
    assert set(per_call) == {call["id"] for call in extra_calls}
    assert min(per_call.values()) >= 1

    types = Counter(task["promise_type"] for task in tasks["items"])
    assert types["callback"] > 0
    assert types["documents"] > 0
    assert types["clarification"] > 0

    assert all(task["quote"] for task in tasks["items"])
    assert all(task["due_at"] for task in tasks["items"])
    assert all(task["title"] and len(task["title"]) >= 3 for task in tasks["items"])


def test_extra_corpus_is_idempotent(client, extra_calls):
    client.post("/webhook/calls", json=extra_calls)
    total = client.get("/api/v1/tasks?limit=1").json()["total"]

    again = client.post("/webhook/calls", json=extra_calls).json()
    assert again["duplicates"] == len(extra_calls)
    assert again["tasks_created"] == 0
    assert client.get("/api/v1/tasks?limit=1").json()["total"] == total

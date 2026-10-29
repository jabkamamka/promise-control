"""Необязательный LLM-режим: не ломает основной сценарий и добавляет пропущенное."""
from __future__ import annotations

import app.services.llm as llm
from conftest import make_call


class FakeSettings:
    llm_enabled = True
    llm_api_key = "test-key"
    llm_base_url = "https://example.invalid/v1"
    llm_model = "test-model"
    llm_timeout = 1.0


def test_llm_disabled_by_default(client):
    from app.config import settings

    assert settings.llm_enabled is False
    response = client.post(
        "/webhook/calls",
        json=make_call("c-1", [{"speaker": "operator", "text": "Проконсультирую вас по тарифу завтра."}]),
    )
    assert response.json()["tasks_created"] == 0


def test_llm_adds_promise_rules_missed(client, monkeypatch):
    monkeypatch.setattr(llm, "settings", FakeSettings())
    monkeypatch.setattr(
        llm,
        "_call_model",
        lambda prompt: '[{"index": 0, "type": "callback", "quote": "Проконсультирую вас по тарифу завтра."}]',
    )

    response = client.post(
        "/webhook/calls",
        json=make_call("c-1", [{"speaker": "operator", "text": "Проконсультирую вас по тарифу завтра."}]),
    )
    assert response.json()["tasks_created"] == 1

    task = client.get("/api/v1/tasks").json()["items"][0]
    assert task["matched_by"] == "llm"
    assert task["promise_type"] == "callback"
    assert task["due_hint"] == "завтра"


def test_llm_confirms_rule_promise(client, monkeypatch):
    monkeypatch.setattr(llm, "settings", FakeSettings())
    monkeypatch.setattr(
        llm,
        "_call_model",
        lambda prompt: '[{"index": 0, "type": "callback", "quote": "Перезвоню вам завтра в десять утра."}]',
    )
    client.post(
        "/webhook/calls",
        json=make_call("c-1", [{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]),
    )
    tasks = client.get("/api/v1/tasks").json()
    assert tasks["total"] == 1
    assert tasks["items"][0]["matched_by"] == "rule+llm"


def test_llm_failure_does_not_break_ingest(client, monkeypatch):
    monkeypatch.setattr(llm, "settings", FakeSettings())

    def boom(prompt):
        raise RuntimeError("сервис недоступен")

    monkeypatch.setattr(llm, "_call_model", boom)
    response = client.post(
        "/webhook/calls",
        json=make_call("c-1", [{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]),
    )
    assert response.status_code == 200
    assert response.json()["tasks_created"] == 1


def test_llm_response_parser_is_strict():
    from app.services.llm import _parse_response

    raw = '```json\n[{"index": 0, "type": "callback", "quote": "q"}, {"index": 99, "type": "callback", "quote": "q"}, {"index": 1, "type": "unknown", "quote": "q"}]\n```'
    parsed = _parse_response(raw, {"callback", "documents"}, max_index=5)
    assert len(parsed) == 1
    assert parsed[0].index == 0

    assert _parse_response("не json", {"callback"}, 5) == []

"""Проверка детектора обещаний на типовых репликах."""
from __future__ import annotations

import datetime as dt

from app.services.detect import detect_promises
from app.services.taxonomy import BUILTIN_TYPES, PromiseType
from app.utils import to_iso

TYPES = [
    PromiseType(
        code=t["code"],
        title=t["title"],
        description=t["description"],
        keywords=t["keywords"],
        examples=t["examples"],
        is_builtin=True,
        priority=t["priority"],
    )
    for t in BUILTIN_TYPES
]

CALL_END = "2026-10-29T10:00:00Z"


def call(transcript, call_id="call-1"):
    return {
        "id": call_id,
        "operator_id": 1,
        "client_phone": "+70000000000",
        "started_at": "2026-10-29T09:56:00Z",
        "ended_at": CALL_END,
        "transcript": transcript,
    }


def test_finds_operator_callback():
    result = detect_promises(
        call([{"speaker": "operator", "text": "Перезвоню вам завтра в десять утра."}]), TYPES
    )
    assert len(result) == 1
    assert result[0].promise_type == "callback"
    assert to_iso(result[0].due.due_at) == "2026-10-30T05:00:00Z"
    assert result[0].due.source == "named_day"
    assert result[0].quote.startswith("Перезвоню")


def test_client_promise_is_ignored():
    result = detect_promises(
        call([{"speaker": "client", "text": "Я пришлю вам фото повреждений завтра."}]), TYPES
    )
    assert result == []


def test_question_is_not_a_promise():
    result = detect_promises(
        call([{"speaker": "operator", "text": "Перезвоню вам завтра?"}]), TYPES
    )
    assert result == []


def test_past_tense_is_not_a_promise():
    result = detect_promises(
        call([{"speaker": "operator", "text": "Я перезвонил вам вчера, но не дозвонился."}]), TYPES
    )
    assert result == []


def test_small_talk_is_not_a_promise():
    text = "В субботу мы работаем до шести вечера."
    result = detect_promises(call([{"speaker": "operator", "text": text}]), TYPES)
    assert result == []


def test_two_replicas_give_two_tasks():
    result = detect_promises(
        call(
            [
                {"speaker": "operator", "text": "Перезвоню вам в понедельник."},
                {"speaker": "operator", "text": "И отправлю счёт на почту сегодня."},
            ]
        ),
        TYPES,
    )
    assert len(result) == 2
    assert {p.promise_type for p in result} == {"callback", "documents"}


def test_one_replica_with_two_actions_is_one_task():
    result = detect_promises(
        call(
            [
                {
                    "speaker": "operator",
                    "text": "Подготовлю проект договора и направлю вам на согласование в течение трёх дней.",
                }
            ]
        ),
        TYPES,
    )
    assert len(result) == 1
    assert result[0].promise_type == "documents"
    assert len(result[0].actions) == 2
    assert all(a.startswith(("Подготовить", "Направить")) for a in result[0].actions)


def test_clarification_type():
    result = detect_promises(
        call([{"speaker": "operator", "text": "Не буду гадать, уточню у юристов и вернусь с ответом через день."}]),
        TYPES,
    )
    assert len(result) == 1
    assert result[0].promise_type == "clarification"
    assert result[0].due.source == "relative_days"


def test_documents_type():
    result = detect_promises(
        call([{"speaker": "operator", "text": "Скину вам исправленную накладную на почту завтра до двенадцати."}]),
        TYPES,
    )
    assert len(result) == 1
    assert result[0].promise_type == "documents"
    assert to_iso(result[0].due.due_at) == "2026-10-30T07:00:00Z"


def test_notification_type():
    result = detect_promises(
        call([{"speaker": "operator", "text": "Напомню вам об оплате смс за день до срока."}]), TYPES
    )
    assert result[0].promise_type == "notification"


def test_earliest_explicit_deadline_wins():
    result = detect_promises(
        call(
            [
                {
                    "speaker": "operator",
                    "text": "Подготовлю справку на бланке. Скан пришлю сегодня, оригинал вышлем почтой.",
                }
            ]
        ),
        TYPES,
    )
    assert len(result) == 1
    assert result[0].due.source == "named_day"
    assert to_iso(result[0].due.due_at) == "2026-10-29T13:00:00Z"


def test_deadline_can_come_from_next_operator_replica():
    result = detect_promises(
        call(
            [
                {"speaker": "operator", "text": "Перезвоню вам."},
                {"speaker": "operator", "text": "Завтра в десять утра, хорошо?"},
            ]
        ),
        TYPES,
    )
    assert len(result) == 1
    assert result[0].due.source == "named_day"
    assert to_iso(result[0].due.due_at) == "2026-10-30T05:00:00Z"


def test_custom_type_can_win():
    custom = PromiseType(
        code="visit_followup",
        title="Проконтролировать визит мастера",
        description="Оператор обещает вернуться к клиенту после визита мастера",
        keywords=["визит", "мастер"],
        examples=["Перезвоню после визита мастера"],
        is_builtin=False,
        priority=78,
    )
    result = detect_promises(
        call([{"speaker": "operator", "text": "Перезвоню вам завтра после визита мастера."}]),
        [*TYPES, custom],
    )
    assert len(result) == 1
    assert result[0].promise_type == "visit_followup"
    assert result[0].matched_by == "custom-rule"

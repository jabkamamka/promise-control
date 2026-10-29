"""Тесты поиска обещаний: роли, отрицания, несколько обещаний, срок по умолчанию."""

from datetime import datetime, timedelta, timezone

from app.detector import BUILTIN_TYPES, dedupe_key, detect_promises
from app.text import Segment, normalize_role, to_segments

TZ = timezone(timedelta(hours=5))
CALL_END = datetime(2026, 10, 29, 15, 0, tzinfo=TZ)


def detect(segments):
    return detect_promises(segments, BUILTIN_TYPES, CALL_END, default_due_hours=24)


def test_three_basic_types_and_roles():
    segments = [
        Segment("operator", "Добрый день, это Анна, компания УралМикро."),
        Segment("client", "Здравствуйте, а я вам сам перезвоню."),
        Segment("operator", "Хорошо, я перезвоню вам через час и отправлю договор на почту."),
        Segment("operator", "Уточню у коллег и вернусь с ответом."),
    ]
    promises = detect(segments)
    codes = sorted(p.type_code for p in promises)
    assert codes == ["callback", "clarify_and_reply", "send_documents"]
    # Обещание клиента не создаёт задачу оператору.
    assert all(p.quote != "Здравствуйте, а я вам сам перезвоню." for p in promises)
    callback = next(p for p in promises if p.type_code == "callback")
    assert callback.due_source == "explicit"
    assert callback.due_at == CALL_END + timedelta(hours=1)


def test_negative_is_not_a_promise():
    segments = [Segment("operator", "К сожалению, перезвонить не смогу, я не перезвоню.")]
    assert detect(segments) == []


def test_two_promises_of_same_type_stay_two_tasks():
    segments = [
        Segment("operator", "Я перезвоню вам через час."),
        Segment("operator", "И ещё раз перезвоню завтра в 10:00."),
    ]
    promises = detect(segments)
    assert len(promises) == 2
    assert len({p.dedupe_key for p in promises}) == 2


def test_default_deadline_is_24_hours():
    promises = detect([Segment("operator", "Уточню у коллег и вернусь с ответом.")])
    assert len(promises) == 1
    assert promises[0].due_source == "default"
    assert promises[0].due_at == CALL_END + timedelta(hours=24)


def test_deadline_from_following_operator_reply():
    segments = [
        Segment("operator", "Тогда я вам перезвоню."),
        Segment("operator", "Завтра в 11:00 вам удобно?"),
    ]
    promises = detect(segments)
    assert len(promises) == 1
    assert promises[0].due_source == "explicit"
    assert promises[0].due_at == datetime(2026, 10, 30, 11, 0, tzinfo=TZ)


def test_hedged_promise_has_lower_confidence():
    sure = detect([Segment("operator", "Я перезвоню вам через час.")])[0]
    hedged = detect([Segment("operator", "Постараюсь перезвонить вам через час.")])[0]
    assert hedged.confidence < sure.confidence


def test_string_transcript_with_prefixes():
    raw = (
        "Оператор: Здравствуйте, я перезвоню вам завтра.\n"
        "Клиент: Хорошо, спасибо.\n"
        "Оператор: И отправлю документы на почту."
    )
    segments = to_segments(raw)
    assert [s.role for s in segments] == ["operator", "client", "operator"]
    promises = detect(segments)
    assert {p.type_code for p in promises} == {"callback", "send_documents"}


def test_dedupe_key_is_stable():
    assert dedupe_key("callback", "Я перезвоню!") == dedupe_key("callback", "я перезвоню")

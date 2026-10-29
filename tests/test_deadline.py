"""Проверка разбора сроков: «завтра до обеда» → конкретная дата."""
from __future__ import annotations

import datetime as dt

import pytest

from app.services.deadline import get_tz, parse_deadline
from app.utils import to_iso

TZ = get_tz("Asia/Yekaterinburg")  # UTC+5, без перехода на летнее время
CALL_END = dt.datetime(2026, 10, 29, 10, 0, tzinfo=dt.timezone.utc)  # чт, 15:00 по Екатеринбургу


def local(day_offset: int, hour: int, minute: int = 0) -> str:
    base = dt.datetime(2026, 10, 29, hour, minute, tzinfo=TZ)
    return to_iso(base + dt.timedelta(days=day_offset))


@pytest.mark.parametrize(
    "text, expected, source",
    [
        ("Я вам перезвоню в понедельник и скажу точные сроки", local(4, 18), "weekday"),
        ("Наберу вас в среду утром", local(6, 10), "weekday"),
        ("Перезвоню вам завтра в десять утра", local(1, 10), "named_day"),
        ("Вернусь к вам с ответом завтра до обеда", local(1, 12), "named_day"),
        ("Отправлю каталог сегодня", local(0, 18), "named_day"),
        ("Сообщу вам сегодня до вечера", local(0, 18), "named_day"),
        ("Отправлю счёт сегодня после обеда", local(0, 15), "named_day"),
        ("Пришлю инструкцию в течение получаса", "2026-10-29T10:30:00Z", "relative_minutes"),
        ("Выгружу платёжное поручение и отправлю вам через час", "2026-10-29T11:00:00Z", "relative_hours"),
        ("Наберу вас через два часа", "2026-10-29T12:00:00Z", "relative_hours"),
        ("Уточню и вернусь в течение пятнадцати минут", "2026-10-29T10:15:00Z", "relative_minutes"),
        ("Подготовлю проект договора и направлю в течение трёх дней", local(3, 15), "relative_days"),
        ("Вернусь с ответом в течение трёх рабочих дней", local(5, 18), "working_days"),
        ("Свяжусь с вами ориентировочно через два-три дня", local(3, 15), "relative_days"),
        ("Наберу вас после обеда, часа в четыре", local(0, 16), "time_of_day"),
        ("Перезвоню около шести", local(0, 18), "time_of_day"),
        ("Исправлю адрес прямо сейчас", "2026-10-29T10:15:00Z", "immediate"),
        ("Отправлю на почту до конца недели", local(1, 18), "end_of_week"),
        ("Вернусь с ответом на следующей неделе", local(8, 18), "end_of_week"),
        ("Наберу вас до пятницы с результатом", local(1, 18), "weekday"),
    ],
)
def test_deadline_examples(text, expected, source):
    deadline = parse_deadline(text, CALL_END, TZ)
    assert to_iso(deadline.due_at) == expected
    assert deadline.source == source


def test_default_is_24_hours():
    deadline = parse_deadline("Сообщу результат", CALL_END, TZ)
    assert to_iso(deadline.due_at) == "2026-10-30T10:00:00Z"
    assert deadline.source == "default_24h"


def test_hint_keeps_the_phrase():
    deadline = parse_deadline("Перезвоню вам завтра в десять утра", CALL_END, TZ)
    assert "завтра" in deadline.hint
    assert "десять" in deadline.hint


def test_end_of_month():
    deadline = parse_deadline("Ответим до конца месяца", CALL_END, TZ)
    assert to_iso(deadline.due_at) == local(2, 18)


def test_past_deadline_is_clamped_forward():
    # «сегодня» в 23:00 при окончании звонка в 15:00 всё ещё в будущем,
    # а вот «сегодня в десять утра» — уже нет
    deadline = parse_deadline("Перезвоню сегодня в десять утра", CALL_END, TZ)
    assert deadline.due_at > CALL_END
    assert "clamped" in deadline.source


def test_unknown_phrase_falls_back():
    deadline = parse_deadline("Напомню вам об оплате смс за день до срока", CALL_END, TZ)
    assert deadline.source == "default_24h"

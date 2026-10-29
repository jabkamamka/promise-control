"""Тесты разбора сроков из русской речи."""

from datetime import datetime, timedelta, timezone

from app.datetime_ru import parse_deadline

TZ = timezone(timedelta(hours=5))
BASE = datetime(2026, 10, 29, 15, 0, tzinfo=TZ)  # четверг, 15:00


def at(text: str):
    result = parse_deadline(text, BASE)
    assert result is not None, text
    return result.at


def test_relative_minutes():
    assert at("Перезвоню через 30 минут") == BASE + timedelta(minutes=30)


def test_relative_hours():
    assert at("Я перезвоню через два часа") == BASE + timedelta(hours=2)


def test_tomorrow_with_time():
    assert at("Перезвоню завтра в 10:00") == datetime(2026, 10, 30, 10, 0, tzinfo=TZ)


def test_tomorrow_without_time_is_end_of_day():
    assert at("Наберу вас завтра") == datetime(2026, 10, 30, 18, 0, tzinfo=TZ)


def test_today_passed_time_moves_to_tomorrow():
    assert at("Перезвоню сегодня в 9 утра") == datetime(2026, 10, 30, 9, 0, tzinfo=TZ)


def test_business_days():
    # 29.10.2026 — четверг; два рабочих дня: пятница 30.10 и понедельник 02.11.
    assert at("Уточню в течение двух рабочих дней") == datetime(2026, 11, 2, 18, 0, tzinfo=TZ)


def test_end_of_week():
    assert at("Пришлю до конца недели") == datetime(2026, 10, 30, 18, 0, tzinfo=TZ)


def test_weekday():
    assert at("Перезвоню в понедельник в 11:00") == datetime(2026, 11, 2, 11, 0, tzinfo=TZ)


def test_end_of_day():
    assert at("Отправлю до конца дня") == datetime(2026, 10, 29, 18, 0, tzinfo=TZ)


def test_explicit_date():
    assert at("Пришлю 12.11.2026 в 14:30") == datetime(2026, 11, 12, 14, 30, tzinfo=TZ)


def test_bare_time_is_not_confused_with_day_count():
    assert at("Перезвоню в 16:30") == datetime(2026, 10, 29, 16, 30, tzinfo=TZ)


def test_no_deadline_returns_none():
    assert parse_deadline("Я вам перезвоню", BASE) is None

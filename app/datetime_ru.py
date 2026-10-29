"""Извлечение срока из реплики оператора.

Кейс требует: названный срок превращается в дату и время относительно окончания
звонка; если срок не назван — ставится +24 часа. Здесь только разбор текста,
решение о дефолте принимает вызывающий код.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from .text import normalize

MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6,
    "июл": 7, "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

WEEKDAYS = {
    "понедельник": 0, "вторник": 1, "сред": 2, "четверг": 3,
    "пятниц": 4, "суббот": 5, "воскресень": 6,
}

NUM_WORDS = {
    "один": 1, "одну": 1, "одна": 1, "одного": 1, "два": 2, "две": 2, "двух": 2,
    "три": 3, "трех": 3, "четыре": 4, "четырех": 4, "пять": 5, "пяти": 5,
    "шесть": 6, "шести": 6, "семь": 7, "семи": 7, "восемь": 8, "восьми": 8,
    "девять": 9, "девяти": 9, "десять": 10, "десяти": 10, "одиннадцать": 11,
    "двенадцать": 12, "тринадцать": 13, "четырнадцать": 14, "пятнадцать": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "тридцать": 30, "сорок": 40, "пятьдесят": 50, "шестьдесят": 60,
    "полтора": 1.5,
}

# Даты в числовом виде надо вырезать до разбора времени, иначе «12.11.2026»
# превратится в «12 часов 11 минут».
DATE_DOT_RE = re.compile(r"\b(\d{1,2})[.\-/](\d{1,2})(?:[.\-/](\d{2,4}))?\b")
DATE_WORD_RE = re.compile(r"\b(\d{1,2})\s+([а-я]+)")
TIME_RE = re.compile(
    r"(?<![\d.])\b([01]?\d|2[0-3])(?:[:.](\d{2}))\b"
    r"(?:\s*(?:час(?:а|ов)?|ч\.))?"
    r"(?:\s*(утра|дня|вечера|ночи))?"
)
TIME_WORD_RE = re.compile(r"\b(?:в|к|до)\s+([01]?\d|2[0-3])\s*(?:час(?:а|ов)?|ч\.)?(?:\s*(утра|дня|вечера|ночи))?\b")

INTERVAL_RE = re.compile(
    r"\b(через|в\s+течение|в\s+продолжение|за)\s+"
    r"((?:[а-я0-9]+\s+){0,3}?)"
    r"(минут\w*|мин\b|час\w*|дн\w*|день|сут\w*|недел\w*|месяц\w*)"
)
HALF_HOUR_RE = re.compile(r"\bполчаса\b|\bпол\s+часа\b")
WINDOW_RE = re.compile(r"\b(?:до\s+конца|к\s+концу)\s+(дня|недели|месяца|рабочего\s+дня)\b")
DAYWORD_RE = re.compile(r"\b(сегодня|завтра|послезавтра)\b")
WEEKDAY_RE = re.compile(
    r"\b(?:в|во|к|до|на)\s+(понедельник|вторник|среду|сред\w*|четверг|пятниц\w*|суббот\w*|воскресень\w*)\b"
)


@dataclass
class Deadline:
    at: datetime
    phrase: str


def _amount(phrase: str) -> float | None:
    for token in phrase.split():
        if token.isdigit():
            return float(token)
    for token in phrase.split():
        if token in NUM_WORDS:
            return float(NUM_WORDS[token])
    return None


def _strip_dates(text: str) -> str:
    text = DATE_DOT_RE.sub(" ", text)
    return DATE_WORD_RE.sub(lambda m: " " if _month_from_word(m.group(2)) else m.group(0), text)


def _parse_clock(text: str) -> tuple[int, int] | None:
    """Время суток: «в 15:30», «к 9 утра», «в 18 часов»."""
    cleaned = _strip_dates(text)

    m = TIME_RE.search(cleaned)
    if m:
        hour, minute = int(m.group(1)), int(m.group(2))
        return _apply_daypart(hour, m.group(3)), minute

    m = TIME_WORD_RE.search(cleaned)
    if m:
        hour = int(m.group(1))
        return _apply_daypart(hour, m.group(2)), 0

    return None


def _apply_daypart(hour: int, part: str | None) -> int:
    if part in {"дня", "вечера"} and hour < 12:
        return hour + 12
    if part == "ночи" and hour >= 12:
        return hour - 12
    return hour


def _month_from_word(word: str) -> int | None:
    for key, num in MONTHS.items():
        if word.startswith(key):
            return num
    return None


def _parse_explicit_date(text: str, base: datetime) -> date | None:
    m = DATE_DOT_RE.search(text)
    if m:
        day, month = int(m.group(1)), int(m.group(2))
        year = int(m.group(3)) if m.group(3) else base.year
        if year < 100:
            year += 2000
        try:
            return date(year, month, day)
        except ValueError:
            return None

    m = DATE_WORD_RE.search(text)
    if m:
        day = int(m.group(1))
        month = _month_from_word(m.group(2))
        if month:
            try:
                return date(base.year, month, day)
            except ValueError:
                return None
    return None


def _add_business_days(dt: datetime, days: int) -> datetime:
    step = 0
    while step < days:
        dt += timedelta(days=1)
        if dt.weekday() < 5:
            step += 1
    return dt


def _end_of_day(dt: datetime, hour: int = 18) -> datetime:
    return dt.replace(hour=hour, minute=0, second=0, microsecond=0)


def parse_deadline(text: str, base: datetime) -> Deadline | None:
    """Возвращает срок, если он явно назван в тексте. Иначе None."""
    if not text:
        return None
    src = normalize(text)
    clock = _parse_clock(src)
    tz = base.tzinfo

    # 0. «Полчаса» — отдельный случай, иначе «час» съест слово.
    if HALF_HOUR_RE.search(src):
        return Deadline(at=base + timedelta(minutes=30), phrase="полчаса")

    # 1. Интервалы: «через час», «через 30 минут», «в течение двух рабочих дней».
    m = INTERVAL_RE.search(src)
    if m:
        amount = _amount(m.group(2))
        unit = m.group(3)
        business = "рабоч" in m.group(0)
        if amount is None and not m.group(2).strip():
            amount = 1.0
        if amount is not None:
            dt = base
            if unit.startswith(("минут", "мин")):
                dt = base + timedelta(minutes=amount)
            elif unit.startswith("час"):
                dt = base + timedelta(hours=amount)
            elif unit.startswith("недел"):
                dt = base + timedelta(weeks=amount)
            elif unit.startswith("месяц"):
                dt = base + timedelta(days=30 * amount)
            else:
                if business:
                    dt = _add_business_days(_end_of_day(base), int(amount))
                else:
                    dt = base + timedelta(days=amount)
            return Deadline(at=dt, phrase=m.group(0).strip())

    # 2. «До конца дня / недели / месяца».
    m = WINDOW_RE.search(src)
    if m:
        target = m.group(1)
        if target.startswith("недел"):
            friday = base + timedelta(days=(4 - base.weekday()) % 7 or 7)
            return Deadline(at=_end_of_day(friday), phrase=m.group(0).strip())
        if target.startswith("месяц"):
            last = (date(base.year + 1, 1, 1) if base.month == 12 else date(base.year, base.month + 1, 1)) - timedelta(days=1)
            return Deadline(at=_end_of_day(datetime.combine(last, time(18, 0), tzinfo=tz)), phrase=m.group(0).strip())
        return Deadline(at=_end_of_day(base), phrase=m.group(0).strip())

    # 3. Явная дата (с временем или без).
    explicit = _parse_explicit_date(src, base)
    if explicit is not None:
        hour, minute = clock if clock else (18, 0)
        dt = datetime.combine(explicit, time(hour, minute), tzinfo=tz)
        if dt <= base:
            dt += timedelta(days=1)
        return Deadline(at=dt, phrase=_phrase(src, clock))

    # 4. «Сегодня / завтра / послезавтра».
    m = DAYWORD_RE.search(src)
    if m:
        word = m.group(1)
        shift = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[word]
        day = base + timedelta(days=shift)
        hour, minute = clock if clock else (18, 0)
        dt = datetime.combine(day.date(), time(hour, minute), tzinfo=tz)
        if dt <= base:
            dt += timedelta(days=1)
        return Deadline(at=dt, phrase=_phrase(src, clock))

    # 5. День недели.
    m = WEEKDAY_RE.search(src)
    if m:
        word = m.group(1)
        target = next((idx for key, idx in WEEKDAYS.items() if word.startswith(key[:4])), None)
        if target is not None:
            delta = (target - base.weekday()) % 7 or 7
            day = base + timedelta(days=delta)
            hour, minute = clock if clock else (18, 0)
            return Deadline(at=datetime.combine(day.date(), time(hour, minute), tzinfo=tz), phrase=_phrase(src, clock))

    # 6. Только время: «перезвоню в 15:30».
    if clock:
        hour, minute = clock
        dt = datetime.combine(base.date(), time(hour, minute), tzinfo=tz)
        if dt <= base:
            dt += timedelta(days=1)
        return Deadline(at=dt, phrase=_phrase(src, clock))

    return None


def _phrase(src: str, clock: tuple[int, int] | None) -> str:
    """Короткая цитата срока — для карточки задачи."""
    for pattern in (INTERVAL_RE, WINDOW_RE, DAYWORD_RE, WEEKDAY_RE, DATE_DOT_RE, DATE_WORD_RE):
        m = pattern.search(src)
        if m:
            return m.group(0).strip()
    if clock:
        return f"{clock[0]:02d}:{clock[1]:02d}"
    return src[:60]

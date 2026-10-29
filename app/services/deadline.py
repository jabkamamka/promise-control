"""Разбор срока обещания из русской реплики оператора.

Правила простые и объяснимые: ищем самый конкретный временной маркер в реплике
и переводим его в дату/время относительно окончания звонка.

Порядок приоритета:
  1. «до конца рабочего дня» / «в течение дня»
  2. «через ...» / «в течение ...» (минуты, часы, дни, рабочие дни, недели)
  3. «до конца недели», «на этой/следующей неделе», «до конца месяца»
  4. «сегодня / завтра / послезавтра» (+ время суток)
  5. день недели: «в четверг», «до пятницы», «в среду утром»
  6. абсолютная дата: «5 ноября», «05.11»
  7. только время суток: «до обеда», «вечером», «около шести»
  8. иначе — срок по умолчанию 24 часа

Если получившаяся дата уже в прошлом — срок сдвигается на час вперёд,
а источник помечается как clamped. Это лучше, чем задача «просрочена» сразу
после создания.
"""
from __future__ import annotations

import calendar
import datetime as dt
import re
from dataclasses import dataclass
from zoneinfo import ZoneInfo

from ..config import settings
from ..utils import normalize_text, UTC

# --------------------------------------------------------------------------- #
# Числа и единицы
# --------------------------------------------------------------------------- #

_NUM_WORDS = {
    "ноль": 0, "один": 1, "одну": 1, "одного": 1, "одна": 1,
    "два": 2, "две": 2, "двух": 2, "пару": 2, "пара": 2, "пары": 2,
    "три": 3, "трех": 3, "трех": 3, "четыре": 4, "четырех": 4,
    "пять": 5, "пяти": 5, "шесть": 6, "шести": 6, "семь": 7, "семи": 7,
    "восемь": 8, "восьми": 8, "девять": 9, "девяти": 9,
    "десять": 10, "десяти": 10, "одиннадцать": 11, "одиннадцати": 11,
    "двенадцать": 12, "двенадцати": 12, "тринадцать": 13, "тринадцати": 13,
    "четырнадцать": 14, "четырнадцати": 14, "пятнадцать": 15, "пятнадцати": 15,
    "шестнадцать": 16, "семнадцать": 17, "восемнадцать": 18, "девятнадцать": 19,
    "двадцать": 20, "двадцати": 20, "тридцать": 30, "тридцати": 30,
    "сорок": 40, "сорока": 40, "пятьдесят": 50, "пятидесяти": 50,
    "несколько": 3, "нескольких": 3, "полтора": 1.5,
}

_TENS = {"двадцать", "двадцати", "тридцать", "тридцати", "сорок", "сорока", "пятьдесят", "пятидесяти"}
_UNITS = {"один", "одну", "два", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"}

_WEEKDAYS = {
    "понедельник": 1, "вторник": 2, "сред": 3, "четверг": 4,
    "пятниц": 5, "суббот": 6, "воскресень": 7,
}

_REL_RE = re.compile(
    r"\b(через|в\s+течение|в\s+течении)\s+"
    r"(?P<num>[а-я0-9\s\-]{0,30}?)\s*"
    r"(?P<unit>минут\w*|мин\b|час\w*|ч\b|дн\w*|день\b|дня\b|дней\b|сут\w*|недел\w*|месяц\w*)"
)
_DAY_RE = re.compile(r"\b(?P<day>сегодня|завтра|послезавтра|после\s+завтра)\b(?P<rest>[^.!?;]{0,45})")
_WD_RE = re.compile(
    r"\b(?P<prep>в|во|до|к)\s+"
    r"(?P<wd>понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)"
    r"(?P<rest>[^.!?;]{0,45})"
)
_EOW_RE = re.compile(
    r"\b(до\s+конца\s+недели|к\s+концу\s+недели|на\s+этой\s+неделе|на\s+следующей\s+неделе|"
    r"до\s+конца\s+месяца|к\s+концу\s+месяца|в\s+конце\s+месяца|до\s+конца\s+рабочего\s+дня|"
    r"до\s+конца\s+дня|в\s+течение\s+дня|в\s+течение\s+рабочего\s+дня|на\s+днях)\b"
)
_ABS_DATE_RE = re.compile(
    r"\b(?:до|к|ко)?\s*(?P<day>\d{1,2})\s+(?P<month>январ\w*|феврал\w*|март\w*|апрел\w*|"
    r"ма[йя]\w*|июн\w*|июл\w*|август\w*|сентябр\w*|октябр\w*|ноябр\w*|декабр\w*)"
)
_ABS_NUM_RE = re.compile(r"\b(?:до|к|ко)\s+(?P<d>\d{1,2})[.\-/](?P<m>\d{1,2})(?:[.\-/](?P<y>\d{2,4}))?")

_MONTHS = {
    "январ": 1, "феврал": 2, "март": 3, "апрел": 4, "ма": 5, "июн": 6, "июл": 7,
    "август": 8, "сентябр": 9, "октябр": 10, "ноябр": 11, "декабр": 12,
}

_TOD_PATTERNS = (
    (re.compile(r"\bв\s+(\d{1,2})(?::(\d{2}))?\s*(утра|дня|вечера|ночи)\b"), "at"),
    (re.compile(r"\bдо\s+(\d{1,2})(?::(\d{2}))?\s*(утра|дня|вечера|ночи)?\b"), "at"),
    (re.compile(r"\bк\s+(\d{1,2})(?::(\d{2}))?\s*(утра|дня|вечера|ночи)?\b"), "at"),
    (re.compile(r"\bоколо\s+(\d{1,2})(?::(\d{2}))?\b"), "at"),
    (re.compile(r"\bчас[ау]?\s+в\s+(\d{1,2})\b"), "at"),
)

_SPECIAL_TOD = (
    (re.compile(r"\bдо\s+обеда\b"), (12, 0)),
    (re.compile(r"\bк\s+обеду\b"), (12, 0)),
    (re.compile(r"\bпосле\s+обеда\b"), (15, 0)),
    (re.compile(r"\bдо\s+вечера\b|\bк\s+вечеру\b|\bвечером\b"), (18, 0)),
    (re.compile(r"\bутром\b|\bс\s+утра\b"), (10, 0)),
    (re.compile(r"\bднем\b|\bв\s+обед\b"), (14, 0)),
    (re.compile(r"\bдо\s+конца\s+дня\b|\bдо\s+конца\s+рабочего\s+дня\b"), (18, 0)),
)


@dataclass
class Deadline:
    due_at: dt.datetime
    hint: str
    source: str
    matched: str = ""

    def hours_from(self, base: dt.datetime) -> float:
        return (self.due_at - base).total_seconds() / 3600.0


def get_tz(name: str | None = None) -> dt.tzinfo:
    try:
        return ZoneInfo(name or settings.timezone)
    except Exception:  # нет tzdata — работаем как в Екатеринбурге (UTC+5)
        return dt.timezone(dt.timedelta(hours=5))


def _parse_number(fragment: str, unit_minutes: bool = False) -> float | None:
    """Достаёт число из фрагмента: «два-три», «пятнадцати», «3», «пару»."""
    cleaned = normalize_text(fragment)
    if "получас" in cleaned:
        return 30.0
    if "полтора" in cleaned:
        return 1.5
    tokens = re.findall(r"[а-я]+|\d+", cleaned)
    values: list[float] = []
    for tok in tokens:
        if tok.isdigit():
            values.append(float(tok))
        elif tok in _NUM_WORDS:
            values.append(float(_NUM_WORDS[tok]))
    if not values:
        return None if unit_minutes else 1.0
    # «двадцать три» -> 23 (десяток + единица рядом)
    for i in range(len(values) - 1):
        if values[i] >= 20 and values[i] % 10 == 0 and 1 <= values[i + 1] <= 9:
            return values[i] + values[i + 1]
    # диапазон «два-три» -> берём максимум, чтобы срок не оказался слишком ранним
    return max(values)


def _unit_kind(unit: str) -> str:
    unit = unit.strip()
    if unit.startswith(("минут", "мин")):
        return "minutes"
    if unit.startswith(("час", "ч")):
        return "hours"
    if unit.startswith(("дн", "день", "дня", "дней", "сут")):
        return "days"
    if unit.startswith("недел"):
        return "weeks"
    if unit.startswith("месяц"):
        return "months"
    return "days"


def _next_weekday(base: dt.date, weekday: int) -> dt.date:
    return base + dt.timedelta(days=(weekday - base.isoweekday()) % 7)


def _add_working_days(start: dt.date, days: int) -> dt.date:
    cur = start
    left = max(0, days)
    while left > 0:
        cur += dt.timedelta(days=1)
        if cur.isoweekday() <= 5:
            left -= 1
    return cur


def _end_of_week(base: dt.date) -> dt.date:
    """Пятница текущей недели."""
    return base + dt.timedelta(days=(5 - base.isoweekday()) % 7)


def _last_day_of_month(base: dt.date) -> dt.date:
    return dt.date(base.year, base.month, calendar.monthrange(base.year, base.month)[1])


def _end_of_day_hour(local_now: dt.datetime, day: dt.date) -> tuple[int, int]:
    if day == local_now.date() and local_now.hour >= 18:
        return 23, 59
    return 18, 0


_WORD_HOUR_PATTERNS = (
    (re.compile(r"\bв\s+([а-я]+)\s*(утра|дня|вечера|ночи)\b"), True),
    (re.compile(r"\bдо\s+([а-я]+)\s*(утра|дня|вечера|ночи)\b"), True),
    (re.compile(r"\bк\s+([а-я]+)\s*(утра|дня|вечера|ночи)\b"), True),
    (re.compile(r"\bдо\s+([а-я]+)\b"), False),
    (re.compile(r"\bк\s+([а-я]+)\b"), False),
    (re.compile(r"\bв\s+([а-я]+)\b"), False),
    (re.compile(r"\bоколо\s+([а-я]+)\b"), False),
    (re.compile(r"\bчас[ау]?\s+в\s+([а-я]+)\b"), False),
)


def _apply_ampm(hour: int, ampm: str | None) -> int:
    if ampm in ("вечера", "дня"):
        return hour + 12 if hour < 12 else hour
    if ampm == "ночи":
        return 0 if hour == 12 else hour
    if ampm is None and hour <= 7:
        return hour + 12
    return hour


def _find_time_of_day(text: str) -> tuple[int, int, str] | None:
    """Ищет время суток. Возвращает (час, минута, найденный фрагмент)."""
    for pattern, _kind in _TOD_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        hour = int(m.group(1))
        minute = int(m.group(2) or 0)
        ampm = None
        if m.re.groups >= 3:
            try:
                ampm = m.group(3)
            except IndexError:
                ampm = None
        hour = _apply_ampm(hour, ampm)
        if 0 <= hour <= 23 and 0 <= minute <= 59:
            return hour, minute, m.group(0).strip()
    for pattern, has_ampm in _WORD_HOUR_PATTERNS:
        m = pattern.search(text)
        if not m:
            continue
        value = _NUM_WORDS.get(m.group(1))
        if value is None or not float(value).is_integer():
            continue
        hour = int(value)
        ampm = m.group(2) if has_ampm and m.re.groups >= 2 else None
        hour = _apply_ampm(hour, ampm)
        if 0 <= hour <= 23:
            return hour, 0, m.group(0).strip()
    for pattern, (hour, minute) in _SPECIAL_TOD:
        m = pattern.search(text)
        if m:
            return hour, minute, m.group(0).strip()
    return None


def _clamp(due: dt.datetime, local_now: dt.datetime) -> tuple[dt.datetime, str]:
    if due < local_now:
        return local_now + dt.timedelta(minutes=settings.immediate_minutes), "clamped"
    return due, ""


def parse_deadline(
    text: str,
    call_end: dt.datetime,
    tz: dt.tzinfo | None = None,
    default_hours: int | None = None,
) -> Deadline:
    """Главная функция: срок обещания по тексту реплики."""
    tz = tz or get_tz()
    if call_end.tzinfo is None:
        call_end = call_end.replace(tzinfo=UTC)
    local_now = call_end.astimezone(tz)
    default_hours = settings.default_due_hours if default_hours is None else default_hours
    norm = normalize_text(text)

    def finish(local_due: dt.datetime, source: str, matched: str) -> Deadline:
        due, reason = _clamp(local_due, local_now)
        if reason:
            source = f"{source}+clamped"
        return Deadline(due_at=due.astimezone(UTC), hint=matched.strip(), source=source, matched=matched)

    # 1. конец рабочего дня / в течение дня
    m = _EOW_RE.search(norm)
    if m:
        phrase = m.group(0)
        if "недел" in phrase:
            if "следующей" in phrase:
                friday = _end_of_week(local_now.date()) + dt.timedelta(days=7)
            else:
                friday = _end_of_week(local_now.date())
            local_due = dt.datetime.combine(friday, dt.time(18, 0), tzinfo=tz)
            return finish(local_due, "end_of_week", phrase)
        if "месяц" in phrase:
            last = _last_day_of_month(local_now.date())
            local_due = dt.datetime.combine(last, dt.time(18, 0), tzinfo=tz)
            return finish(local_due, "end_of_month", phrase)
        if "на днях" in phrase:
            local_due = dt.datetime.combine(local_now.date() + dt.timedelta(days=3), dt.time(18, 0), tzinfo=tz)
            return finish(local_due, "relative_days", phrase)
        # до конца дня / рабочего дня / в течение дня
        hour, minute = _end_of_day_hour(local_now, local_now.date())
        local_due = dt.datetime.combine(local_now.date(), dt.time(hour, minute), tzinfo=tz)
        return finish(local_due, "end_of_day", phrase)

    # 2. «в течение получаса» — отдельный случай: единица «часа» без числа
    if "получас" in norm:
        local_due = local_now + dt.timedelta(minutes=30)
        return finish(local_due, "relative_minutes", "полчаса")

    # 3. «через …» / «в течение …»
    m = _REL_RE.search(norm)
    if m:
        raw_num = m.group("num")
        unit = m.group("unit")
        kind = _unit_kind(unit)
        is_working = "рабоч" in raw_num
        number = _parse_number(raw_num, unit_minutes=(kind == "minutes"))
        phrase = re.sub(r"\s+", " ", m.group(0)).strip()
        if number is not None:
            if kind == "minutes":
                num = int(number if number > 0 else 10)
                num = 10 if number == 3 and "несколько" in raw_num else num
                local_due = local_now + dt.timedelta(minutes=num)
                return finish(local_due, "relative_minutes", phrase)
            if kind == "hours":
                local_due = local_now + dt.timedelta(hours=number)
                return finish(local_due, "relative_hours", phrase)
            days = number * 7 if kind == "weeks" else (number * 30 if kind == "months" else number)
            if is_working:
                target = _add_working_days(local_now.date(), int(days))
                local_due = dt.datetime.combine(target, dt.time(18, 0), tzinfo=tz)
                return finish(local_due, "working_days", phrase)
            local_due = local_now + dt.timedelta(days=days)
            return finish(local_due, "relative_days", phrase)

    # 4. «сегодня / завтра / послезавтра»
    m = _DAY_RE.search(norm)
    if m:
        word = m.group("day").replace(" ", "")
        offset = {"сегодня": 0, "завтра": 1, "послезавтра": 2}[word]
        day = local_now.date() + dt.timedelta(days=offset)
        rest = m.group("rest") or ""
        tod = _find_time_of_day(rest)
        if tod:
            hour, minute, tod_text = tod
            local_due = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
            return finish(local_due, "named_day", f"{word} {tod_text}")
        hour, minute = _end_of_day_hour(local_now, day)
        local_due = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
        return finish(local_due, "named_day", word)

    # 5. день недели
    m = _WD_RE.search(norm)
    if m:
        wd_word = m.group("wd")
        weekday = next(v for k, v in _WEEKDAYS.items() if wd_word.startswith(k))
        rest = m.group("rest") or ""
        tod = _find_time_of_day(rest)
        day = _next_weekday(local_now.date(), weekday)
        if tod:
            hour, minute, tod_text = tod
            local_due = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
            if local_due <= local_now:
                local_due += dt.timedelta(days=7)
            return finish(local_due, "weekday", f"{m.group('prep')} {wd_word} {tod_text}".strip())
        hour, minute = 18, 0
        local_due = dt.datetime.combine(day, dt.time(hour, minute), tzinfo=tz)
        if local_due <= local_now:
            local_due += dt.timedelta(days=7)
        return finish(local_due, "weekday", f"{m.group('prep')} {wd_word}")

    # 6. абсолютная дата
    m = _ABS_DATE_RE.search(norm)
    if m:
        day_num = int(m.group("day"))
        month_key = next((k for k in _MONTHS if m.group("month").startswith(k)), None)
        if month_key and 1 <= day_num <= 31:
            year = local_now.year
            try:
                candidate = dt.date(year, _MONTHS[month_key], day_num)
            except ValueError:
                candidate = None
            if candidate and candidate < local_now.date():
                try:
                    candidate = dt.date(year + 1, _MONTHS[month_key], day_num)
                except ValueError:
                    candidate = None
            if candidate:
                local_due = dt.datetime.combine(candidate, dt.time(18, 0), tzinfo=tz)
                return finish(local_due, "absolute_date", m.group(0).strip())

    m = _ABS_NUM_RE.search(norm)
    if m:
        day_num, month_num = int(m.group("d")), int(m.group("m"))
        if 1 <= day_num <= 31 and 1 <= month_num <= 12:
            year = int(m.group("y")) if m.group("y") else local_now.year
            if year < 100:
                year += 2000
            try:
                candidate = dt.date(year, month_num, day_num)
            except ValueError:
                candidate = None
            if candidate and candidate < local_now.date():
                try:
                    candidate = dt.date(year + 1, month_num, day_num)
                except ValueError:
                    candidate = None
            if candidate:
                local_due = dt.datetime.combine(candidate, dt.time(18, 0), tzinfo=tz)
                return finish(local_due, "absolute_date", m.group(0).strip())

    # 7. только время суток
    tod = _find_time_of_day(norm)
    if tod:
        hour, minute, tod_text = tod
        local_due = dt.datetime.combine(local_now.date(), dt.time(hour, minute), tzinfo=tz)
        if local_due <= local_now:
            local_due += dt.timedelta(days=1)
        return finish(local_due, "time_of_day", tod_text)

    # 8. «прямо сейчас» — срок наступил сразу
    m = re.search(r"\b(прямо\s+сейчас|сейчас|тут\s+же|незамедлительно)\b", norm)
    if m:
        local_due = local_now + dt.timedelta(minutes=settings.immediate_minutes)
        return finish(local_due, "immediate", m.group(0))

    # 9. срок по умолчанию
    local_due = local_now + dt.timedelta(hours=default_hours)
    return Deadline(
        due_at=local_due.astimezone(UTC),
        hint=f"{default_hours} ч по умолчанию",
        source="default_24h" if default_hours == 24 else "default",
        matched="",
    )

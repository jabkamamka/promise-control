"""Приведение входящего payload к внутреннему виду.

Отправщик кейса присылает массив звонков, но точные имена полей в задании не
зафиксированы, а формат может отличаться у разных версий API. Поэтому парсер
терпимый: принимает несколько синонимов полей и не падает на лишних ключах.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .text import Segment, to_segments


class CallFormatError(ValueError):
    """Звонок не удалось разобрать."""


@dataclass
class ParsedCall:
    external_id: str
    operator_id: str
    phone: str | None
    started_at: datetime
    ended_at: datetime
    segments: list[Segment]
    payload: dict[str, Any]


_ID_KEYS = ("id", "call_id", "callId", "uuid", "guid")
_OPERATOR_KEYS = ("operator_id", "operatorId", "operator", "operator_uuid")
_PHONE_KEYS = ("phone", "phone_number", "client_phone", "number", "phoneNumber")
_START_KEYS = ("started_at", "start_time", "startedAt", "start", "started")
_END_KEYS = ("ended_at", "end_time", "endedAt", "end", "ended", "finished_at")
_TRANSCRIPT_KEYS = ("transcript", "segments", "messages", "dialog", "turns", "text")


def extract_calls(payload: Any) -> list[dict[str, Any]]:
    """Достаёт список звонков из массива или обёртки {"calls": [...]}."""
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("calls", "data", "items", "results", "records"):
            value = payload.get(key)
            if isinstance(value, list):
                return [x for x in value if isinstance(x, dict)]
        if any(k in payload for k in _ID_KEYS):
            return [payload]
    raise CallFormatError("Ожидался массив звонков или объект с полем calls")


def _first(raw: dict[str, Any], keys: tuple[str, ...], default: Any = None) -> Any:
    for key in keys:
        if key in raw and raw[key] not in (None, ""):
            return raw[key]
    return default


def parse_dt(value: Any) -> datetime | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Unix-время в секундах или миллисекундах.
        ts = float(value)
        if ts > 1e12:
            ts /= 1000
        return datetime.fromtimestamp(ts, tz=timezone.utc)
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    text = str(value).strip()
    if text.isdigit():
        return parse_dt(int(text))
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d.%m.%Y %H:%M:%S", "%d.%m.%Y %H:%M"):
            try:
                dt = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_call(raw: dict[str, Any], now: datetime | None = None) -> ParsedCall:
    now = now or datetime.now(timezone.utc)

    external_id = _first(raw, _ID_KEYS)
    if external_id in (None, ""):
        raise CallFormatError("У звонка нет id")
    external_id = str(external_id)

    operator_id = str(_first(raw, _OPERATOR_KEYS, "unknown"))
    phone = _first(raw, _PHONE_KEYS)
    phone = str(phone) if phone not in (None, "") else None

    started = parse_dt(_first(raw, _START_KEYS))
    ended = parse_dt(_first(raw, _END_KEYS))
    if started is None and ended is None:
        started = ended = now
    elif started is None:
        started = ended - timedelta(minutes=1)  # type: ignore[operator]
    elif ended is None:
        ended = started + timedelta(minutes=1)

    transcript = _first(raw, _TRANSCRIPT_KEYS, [])
    segments = to_segments(transcript)

    return ParsedCall(
        external_id=external_id,
        operator_id=operator_id,
        phone=phone,
        started_at=started,  # type: ignore[arg-type]
        ended_at=ended,  # type: ignore[arg-type]
        segments=segments,
        payload=raw,
    )

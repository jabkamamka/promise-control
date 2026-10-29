"""Общие утилиты: время, строки, нормализация текста."""
from __future__ import annotations

import datetime as dt
import re
import unicodedata

UTC = dt.timezone.utc

_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
}


def utc_now() -> str:
    """Текущее время в ISO-8601 UTC (строка — так его удобно хранить в SQLite)."""
    return dt.datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def to_iso(value: dt.datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_iso(value: str | dt.datetime | None) -> dt.datetime | None:
    """Разбирает ISO-строку (в том числе с Z и без таймзоны — считаем UTC)."""
    if value is None:
        return None
    if isinstance(value, dt.datetime):
        return value if value.tzinfo else value.replace(tzinfo=UTC)
    raw = str(value).strip()
    if not raw:
        return None
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    # убираем лишние доли секунды (9 знаков бывает в API УралМикро)
    raw = re.sub(r"(\.\d{6})\d+", r"\1", raw)
    try:
        parsed = dt.datetime.fromisoformat(raw)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def normalize_text(text: str) -> str:
    """Нижний регистр, ё→е, единые кавычки/дефисы, схлопнутые пробелы."""
    text = unicodedata.normalize("NFKC", text or "")
    text = text.lower().replace("ё", "е")
    text = text.replace("«", '"').replace("»", '"').replace("—", "-").replace("–", "-")
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def slugify(text: str, fallback: str = "custom") -> str:
    """Латинский slug: для кода нового типа обещания."""
    out = []
    for ch in (text or "").lower():
        if ch in _TRANSLIT:
            out.append(_TRANSLIT[ch])
        elif ch.isalnum():
            out.append(ch)
        else:
            out.append("-")
    slug = re.sub(r"-+", "-", "".join(out)).strip("-")
    return slug or fallback


def split_sentences(text: str) -> list[str]:
    """Делит реплику на смысловые куски по знакам конца предложения."""
    parts = re.split(r"(?<=[.!?;…])\s+", (text or "").strip())
    return [p.strip() for p in parts if p and p.strip()]


def words(text: str) -> list[str]:
    return re.findall(r"[a-zа-я0-9]+", normalize_text(text))

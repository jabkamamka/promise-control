"""Нормализация русского текста и очень лёгкая морфология.

Полноценный лемматизатор (pymorphy и т.п.) не тянем специально: сервис должен
запускаться на школьной Windows-машине без тяжёлых зависимостей. Вместо этого
режем словоформы простым стеммером — для поиска «перезвоню / перезвонит /
перезвоним» этого достаточно.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_SENT_SPLIT = re.compile(r"(?<=[.!?…])\s+|\n+")
_WORD = re.compile(r"[а-яa-z0-9]+(?:-[а-яa-z0-9]+)?", re.IGNORECASE)
_SPACE = re.compile(r"\s+")
_QUOTES = str.maketrans({"«": '"', "»": '"', "“": '"', "”": '"', "—": "-", "–": "-", "ё": "е", "Ё": "Е"})

# Окончания, которые можно отрезать без потери смысла. Порядок важен:
# длинные суффиксы проверяются раньше коротких.
_SUFFIXES = (
    "иями", "ями", "ами", "ов", "ев", "ий", "ый", "ой", "ая", "яя", "ое", "ее",
    "ые", "ие", "ую", "юю", "ем", "им", "ым", "ых", "их", "ах", "ях", "ом", "ам",
    "ям", "ия", "ию", "ей", "ов", "у", "ю", "ы", "и", "а", "я", "о", "е", "ь",
)


def normalize(text: str) -> str:
    """Нижний регистр, единые кавычки/тире, без лишних пробелов."""
    return _SPACE.sub(" ", text.translate(_QUOTES).lower()).strip()


_KEY_STRIP = re.compile(r"[^а-яa-z0-9]+")


def key_text(text: str) -> str:
    """Нормализация для ключа дедупликации: без пунктуации и регистра."""
    return _KEY_STRIP.sub(" ", normalize(text)).strip()


def stem(word: str) -> str:
    """Очень грубый стеммер: отрезает частое окончание у достаточно длинного слова."""
    word = normalize(word)
    if len(word) <= 4:
        return word
    for suffix in _SUFFIXES:
        if len(word) - len(suffix) >= 4 and word.endswith(suffix):
            return word[: -len(suffix)]
    return word


def stems(text: str) -> set[str]:
    return {stem(w) for w in _WORD.findall(normalize(text))}


def split_sentences(text: str) -> list[str]:
    """Делит реплику на предложения, сохраняя порядок."""
    parts = [p.strip() for p in _SENT_SPLIT.split(text or "") if p and p.strip()]
    return parts


@dataclass(frozen=True)
class Segment:
    """Одна реплика в расшифровке."""

    role: str  # operator | client | unknown
    text: str
    start: float | None = None
    end: float | None = None

    @property
    def is_operator(self) -> bool:
        return self.role == "operator"


def normalize_role(raw: str | None) -> str:
    value = normalize(raw or "")
    if value in {"operator", "оператор", "agent", "менеджер", "manager", "specialist"}:
        return "operator"
    if value in {"client", "клиент", "customer", "user", "абонент", "гость"}:
        return "client"
    return "unknown"


def to_segments(raw: object) -> list[Segment]:
    """Приводит расшифровку к списку реплик.

    Поддерживаются оба распространённых варианта: массив объектов
    ({role, text}) и единая строка с префиксами «Оператор:» / «Клиент:».
    """
    result: list[Segment] = []

    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, str):
                result.append(Segment("unknown", item.strip()))
                continue
            if not isinstance(item, dict):
                continue
            role = item.get("role") or item.get("speaker") or item.get("author") or item.get("who")
            text = item.get("text") or item.get("utterance") or item.get("message") or item.get("content") or ""
            result.append(
                Segment(
                    role=normalize_role(role),
                    text=str(text).strip(),
                    start=_as_float(item.get("start") or item.get("from") or item.get("started")),
                    end=_as_float(item.get("end") or item.get("to") or item.get("finished")),
                )
            )
        return [s for s in result if s.text]

    if isinstance(raw, str):
        buffer_role = "unknown"
        buffer: list[str] = []
        for line in raw.splitlines():
            m = re.match(r"^\s*([А-Яа-яA-Za-z ]{3,20})\s*:\s*(.*)$", line)
            if m and normalize_role(m.group(1)) != "unknown":
                if buffer:
                    result.append(Segment(buffer_role, " ".join(buffer).strip()))
                buffer_role = normalize_role(m.group(1))
                buffer = [m.group(2)]
            elif line.strip():
                buffer.append(line.strip())
        if buffer:
            result.append(Segment(buffer_role, " ".join(buffer).strip()))
        return [s for s in result if s.text]

    return result


def _as_float(value: object) -> float | None:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None

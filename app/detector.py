"""Поиск обещаний в расшифровке звонка.

Подход гибридный и полностью объяснимый:

1. Смотрим только реплики оператора (обещание — это его обязательство).
2. Режем реплику на предложения и проверяем каждое по шаблонам типа обещания.
3. Отбрасываем отрицания («не перезвоню») и чужие реплики.
4. Срок ищем в самом предложении, а если его там нет — в следующих репликах
   оператора (люди часто говорят «перезвоню» и только потом «завтра в десять»).

Каждое найденное обещание — отдельная задача. Ключ дедупликации считается от
типа и нормализованной цитаты, поэтому повторная обработка того же звонка не
плодит копии, а два разных обещания одного типа в одном звонке остаются двумя
задачами.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from .datetime_ru import parse_deadline
from .db import iso
from .text import Segment, key_text, normalize, split_sentences, stem, stems

# Отрицания и отказы: если они рядом с глаголом обещания, это не обещание.
NEGATIVE_RE = re.compile(
    r"\b(не\s+перезвон\w*|не\s+позвон\w*|не\s+смогу|не\s+получится|вряд\s+ли|"
    r"не\s+вышлю|не\s+отправлю|не\s+пришлю|не\s+буду|невозможно)\b",
    re.IGNORECASE,
)
HEDGE_RE = re.compile(
    r"\b(постараюсь|попробую|если\s+получится|наверное|возможно|может\s+быть)\b",
    re.IGNORECASE,
)


@dataclass
class PromiseType:
    code: str
    name: str
    description: str
    action: str = ""
    patterns: list[str] = field(default_factory=list)
    keywords: list[str] = field(default_factory=list)
    examples: list[str] = field(default_factory=list)
    is_builtin: bool = False

    def compiled(self) -> list[re.Pattern[str]]:
        return [re.compile(p, re.IGNORECASE) for p in self.patterns]

    def matches(self, sentence: str, sentence_stems: set[str]) -> str | None:
        """Возвращает сработавший шаблон/ключевое слово или None."""
        for pattern in self.compiled():
            if pattern.search(sentence):
                return pattern.pattern
        for keyword in self.keywords:
            key = stem(keyword)
            if len(key) < 4:
                continue
            for word in sentence_stems:
                # Морфология грубая, поэтому сравниваем по началу основы:
                # «уточн» ↔ «уточнит», «перезвон» ↔ «перезвонит».
                if len(word) >= 4 and (word.startswith(key) or key.startswith(word)):
                    return keyword
        return None


@dataclass
class DetectedPromise:
    type_code: str
    type_name: str
    quote: str
    title: str
    comment: str
    confidence: float
    due_at: datetime
    due_source: str  # explicit | default
    due_phrase: str | None
    dedupe_key: str
    matched_by: str


BUILTIN_TYPES: list[PromiseType] = [
    PromiseType(
        code="callback",
        name="Перезвонить",
        description="Оператор обещает сам позвонить клиенту или организовать обратный звонок.",
        action="Перезвонить клиенту",
        is_builtin=True,
        keywords=["перезвон", "позвон", "набер", "свяж"],
        patterns=[
            r"\bперезвон\w*",
            r"\bпозвон\w*\s+(?:вам|ваш\w*|сегодня|завтра|позже|чуть\s+позже|в\s+\d)",
            r"\bнаберу\s+(?:вас|ваш\w*|номер)",
            r"\bсвяжусь\s+с\s+вами\b",
            r"\b(?:сделаю|организую|закажу)\s+(?:вам\s+)?(?:обратный\s+)?звонок\b",
            r"\bвернусь\s+с\s+звонком\b",
        ],
        examples=["Я вам перезвоню в течение часа.", "Наберу вас завтра после обеда."],
    ),
    PromiseType(
        code="send_documents",
        name="Выслать документы",
        description="Оператор обещает отправить клиенту документы, счёт, договор, письмо, ссылку или прайс.",
        action="Выслать документы клиенту",
        is_builtin=True,
        keywords=["вышл", "отправ", "пришл", "направ", "сброш"],
        patterns=[
            r"\b(?:вышлю|отправлю|пришлю|направлю|сброшу)\b[^.!?]{0,60}?"
            r"\b(?:документ\w*|счет\w*|счёт\w*|договор\w*|письм\w*|ссылк\w*|акт\w*|"
            r"прайс\w*|бланк\w*|справк\w*|предложени\w*|коммерческ\w*)",
            r"\b(?:документ\w*|счет\w*|счёт\w*|договор\w*|письм\w*|ссылк\w*|акт\w*|"
            r"прайс\w*|бланк\w*|справк\w*|предложени\w*)\b[^.!?]{0,40}?"
            r"\b(?:вышлю|отправлю|пришлю|направлю|сброшу|придет|придут|на\s+почту)",
            r"\b(?:отправлю|сброшу|пришлю)\s+(?:вам\s+)?(?:на\s+)?(?:почту|e-?mail|ватсап|whatsapp|телеграм|telegram)",
        ],
        examples=["Сейчас отправлю вам договор на почту.", "Пришлю счёт в течение дня."],
    ),
    PromiseType(
        code="clarify_and_reply",
        name="Уточнить и вернуться с ответом",
        description="Оператор обещает уточнить информацию у коллег или в системе и сообщить клиенту результат.",
        action="Уточнить информацию и вернуться с ответом",
        is_builtin=True,
        keywords=["уточн", "выясн", "провер", "согласу", "узна"],
        patterns=[
            r"\b(?:уточню|выясню|узнаю|проверю|согласую)\b",
            r"\b(?:уточнить|выяснить|узнать|проверить|согласовать)\b",
            r"\bвернусь\s+(?:с\s+ответом|к\s+вам|позже)\b",
            r"\bдам\s+(?:вам\s+)?ответ\b",
        ],
        examples=["Уточню у коллег и вернусь с ответом.", "Проверю по базе и сообщу вам."],
    ),
]


_CLAUSE_SPLIT = re.compile(r"[,;:]\s+|\s+(?:и|а|но|затем|потом)\s+", re.IGNORECASE)
_SUBORDINATE = re.compile(r"^(?:чтобы|что|если|когда|потому|так\s+как|котор\w*)\b", re.IGNORECASE)


def _clauses(sentence: str) -> list[str]:
    """Делит предложение на смысловые куски, чтобы не путать сроки разных обещаний."""
    parts = [p.strip(" ,;:\t") for p in _CLAUSE_SPLIT.split(sentence)]
    parts = [p for p in parts if p]
    return parts or [sentence]


def dedupe_key(type_code: str, quote: str) -> str:
    digest = hashlib.sha1(key_text(quote).encode("utf-8")).hexdigest()[:16]
    return f"{type_code}:{digest}"


def _confidence(sentence: str, matched_by: str, role_known: bool) -> float:
    score = 0.85 if (matched_by.startswith("\\b") or matched_by.startswith("(?:")) else 0.62
    if HEDGE_RE.search(sentence):
        score -= 0.2
    if not role_known:
        score -= 0.2
    return max(0.3, min(0.98, round(score, 2)))


def detect_promises(
    segments: list[Segment],
    types: list[PromiseType],
    call_end: datetime,
    default_due_hours: int = 24,
) -> list[DetectedPromise]:
    """Ищет обещания во всех репликах оператора."""
    found: list[DetectedPromise] = []
    seen: set[str] = set()

    for index, segment in enumerate(segments):
        if not segment.is_operator:
            continue
        for sentence in split_sentences(segment.text):
            if NEGATIVE_RE.search(sentence):
                continue
            clauses = _clauses(sentence)
            best: dict[str, tuple[str, str]] = {}
            sentence_deadline = parse_deadline(sentence, call_end)
            clauses_with_deadline = sum(
                1 for c in clauses
                if not _SUBORDINATE.match(c) and parse_deadline(c, call_end) is not None
            )

            for clause in clauses:
                if _SUBORDINATE.match(clause):
                    continue
                clause_norm = normalize(clause)
                clause_stems = stems(clause)

                for ptype in types:
                    matched_by = ptype.matches(clause_norm, clause_stems)
                    if not matched_by:
                        continue
                    previous = best.get(ptype.code)
                    # Одно предложение = одно обещание одного типа. Если тип
                    # сработал в двух кусках, берём тот, где назван срок.
                    if previous is None or (
                        parse_deadline(previous[0], call_end) is None
                        and parse_deadline(clause, call_end) is not None
                    ):
                        best[ptype.code] = (clause, matched_by)

            for ptype in types:
                if ptype.code not in best:
                    continue
                clause, matched_by = best[ptype.code]
                quote = clause if len(clauses) > 1 else sentence.strip()

                due = parse_deadline(clause, call_end)
                if due is None and sentence_deadline is not None and clauses_with_deadline <= 1:
                    # Срок назван один раз на всё предложение — относим его ко всем обещаниям.
                    due = sentence_deadline
                due_phrase = due.phrase if due else None
                due_source = "explicit"
                if due is None:
                    # Срок мог прозвучать следующей репликой оператора.
                    for nxt in segments[index + 1: index + 3]:
                        if not nxt.is_operator:
                            continue
                        follow = parse_deadline(nxt.text, call_end)
                        if follow:
                            due = follow
                            due_phrase = follow.phrase
                            due_source = "explicit"
                            break
                if due is None:
                    due_at = call_end + timedelta(hours=default_due_hours)
                    due_source = "default"
                    due_phrase = None
                else:
                    due_at = due.at

                key = dedupe_key(ptype.code, quote)
                if key in seen:
                    continue
                seen.add(key)

                found.append(
                    DetectedPromise(
                        type_code=ptype.code,
                        type_name=ptype.name,
                        quote=quote,
                        title=ptype.action or ptype.name,
                        comment=_comment(quote, due_phrase, due_source),
                        confidence=_confidence(clause, matched_by, segment.role != "unknown"),
                        due_at=due_at,
                        due_source=due_source,
                        due_phrase=due_phrase,
                        dedupe_key=key,
                        matched_by=matched_by if matched_by.startswith("\\b") else f"keyword:{matched_by}",
                    )
                )
    return found


def _comment(quote: str, due_phrase: str | None, due_source: str) -> str:
    parts = [f"Цитата оператора: «{quote.strip()}»"]
    if due_phrase:
        parts.append(f"Срок из разговора: «{due_phrase}».")
    elif due_source == "default":
        parts.append("Срок в разговоре не назван — поставлен +24 часа от окончания звонка.")
    return " ".join(parts)

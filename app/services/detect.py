"""Поиск обещаний оператора в расшифровке звонка.

Алгоритм (полностью объяснимый, без «чёрного ящика»):

1. Берём только реплики оператора — обещания клиента нам не нужны.
2. Делим реплику на смысловые куски по знакам конца предложения.
3. Ищем в куске глагол обещания в 1-м лице будущего времени
   («перезвоню», «отправлю», «уточню», «передам»). Вопросы, сослагательное
   наклонение и прошедшее время отсекаются.
4. Определяем тип обещания: по глаголу, объекту (документ/смс/выезд) и
   адресату (руководитель/склад/логистика). Спорные случаи решает приоритет
   типа: сначала то, что клиент увидит своими глазами.
5. Срок ищем отдельным парсером (services/deadline.py); если срок не назван —
   24 часа по умолчанию.
6. Несколько обещаний в одной реплике дают несколько задач; повторная
   обработка звонка не создаёт дублей (см. services/ingest.py).
"""
from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field

from ..config import settings
from ..utils import normalize_text, split_sentences, to_iso, words
from .deadline import Deadline, get_tz, parse_deadline
from .taxonomy import (
    CLARIFY_STEMS,
    DOC_OBJECTS,
    EXTRA_PHRASES,
    HEDGES,
    INTERNAL_TARGETS,
    RETURN_MARKERS,
    PromiseType,
    VERBS,
    Verb,
)

OPERATOR_SPEAKERS = {"operator", "оператор", "op", "manager", "agent", "специалист", "сотрудник"}

_QUESTION_START = re.compile(
    r"^\s*(что|чем|как|когда|где|почему|зачем|кто|какой|какая|какие|сколько|можно ли|есть ли|"
    r"будет ли|нужно ли|стоит ли|хотите|подсказать)\b"
)
_CONDITIONAL = re.compile(r"\b(если бы|могли бы|мог бы|стоило бы|хотелось бы|можно было бы|вряд ли)\b")
_NEGATION_BEFORE = re.compile(r"\bне\s+(?:\w+\s+){0,2}$")

#: Временные маркеры — обрезаем их из текста действия.
_TEMPORAL_CUT = re.compile(
    r"\b(?:сегодня|завтра|послезавтра|через|в\s+течение|в\s+течении|до\s+конца|на\s+следующей\s+неделе|"
    r"на\s+этой\s+неделе|на\s+днях)\b"
    r"|\b(?:в|во|до|к|ко)\s+(?:понедельник\w*|вторник\w*|сред\w*|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*)"
    r"|\b(?:утром|днем|вечером|после\s+обеда|до\s+обеда|около\s+\w+|прямо\s+сейчас|сейчас)\b"
)
_TRAILING_JUNK = re.compile(r"[\s,;:–-]*$")
_DANGLING_WORDS = {"и", "до", "в", "во", "к", "ко", "на", "через", "с", "со", "а", "но", "или"}


def _strip_tail(text: str) -> str:
    """Убирает висящие предлоги/союзы, не ломая слова («адрес» не должно стать «адре»)."""
    parts = text.strip(" ,;:-").split()
    while parts and parts[-1].lower() in _DANGLING_WORDS:
        parts.pop()
    return " ".join(parts)

_DOC_RE = re.compile(
    r"\b((?:[а-я]+\s+){0,2}(?:" + "|".join(o for o in DOC_OBJECTS) + r")[а-я]*)"
)
_TARGET_RE = re.compile(r"((?:на|в)\s+(?:склад|логистик\w*|производств\w*|сервисн\w*\s+служб\w*)|"
                        r"руководител\w*|бухгалтери\w*|юрист\w*|отдел\w*|бригад\w*|инженер\w*|коллег\w*)")


@dataclass
class PromiseCandidate:
    type_code: str
    priority: int
    verb: Verb
    clause: str
    matched_by: str = "rule"
    actions: list[str] = field(default_factory=list)


@dataclass
class DetectedPromise:
    promise_type: str
    title: str
    quote: str
    transcript_index: int
    actions: list[str]
    object: str
    due: Deadline
    confidence: float
    matched_by: str
    secondary_types: list[str] = field(default_factory=list)

    @property
    def due_at(self) -> str:
        return to_iso(self.due.due_at)


def _all_verb_forms() -> list[tuple[str, Verb]]:
    pairs: list[tuple[str, Verb]] = []
    for verb in VERBS:
        for form in verb.forms:
            pairs.append((form, verb))
    pairs.sort(key=lambda p: len(p[0]), reverse=True)
    return pairs


_VERB_FORMS = _all_verb_forms()
_VERB_RE = re.compile(
    r"\b(" + "|".join(re.escape(f) for f, _ in _VERB_FORMS) + r")\b",
    re.IGNORECASE,
)
_VERB_BY_FORM = {f: v for f, v in _VERB_FORMS}


def _is_operator(speaker: str) -> bool:
    return normalize_text(speaker) in OPERATOR_SPEAKERS


def _has_doc_object(text: str) -> bool:
    return bool(_DOC_RE.search(text))


def _extract_object(text: str, type_code: str = "") -> str:
    """Объект обещания: что именно отправят или кому передадут."""
    if type_code == "transfer":
        m = _TARGET_RE.search(text)
        return m.group(1).strip() if m else ""
    if type_code not in ("documents", "notification"):
        return ""

    m = _DOC_RE.search(text)
    if not m:
        return ""
    parts = m.group(1).split()
    stop = {"вам", "мне", "его", "ее", "её", "их", "этот", "эту", "это", "пожалуйста", "сразу"}
    while parts and (parts[0] in _VERB_BY_FORM or parts[0] in stop):
        parts.pop(0)
    return " ".join(parts).strip()


def _refine_type(
    verb: Verb, clause: str, types: dict[str, PromiseType], context: str | None = None
) -> tuple[str, int]:
    """Уточняет тип по объекту и адресату; возвращает (code, priority).

    `context` — вся реплика оператора: смысл обещания часто разнесён на два
    предложения («нужно уточнить… я перезвоню в понедельник»).
    """
    base = verb.hint
    ctx = context or clause
    has_doc = _has_doc_object(clause)
    has_sms = "смс" in clause or "уведомл" in clause
    has_visit = "выезд" in clause or "визит" in clause
    has_internal = any(t in clause for t in INTERNAL_TARGETS)
    has_clarify = any(stem in ctx for stem in CLARIFY_STEMS)
    has_return = any(marker in ctx for marker in RETURN_MARKERS)

    if base == "documents" and has_sms and not has_doc:
        base = "notification"
    if base == "transfer" and has_doc and ("направ" in clause or "отправ" in clause or "пришл" in clause):
        base = "documents"
    if base == "fix" and has_visit:
        base = "visit"

    priority = types[base].priority if base in types else 50

    # Уточнение + «вернуться с ответом» — третий тип из кейса, он важнее звонка.
    if base == "clarification" and has_clarify and has_return:
        priority = max(priority, 88)
    elif base == "callback" and has_clarify and has_return:
        # «Мне нужно уточнить у производства, я перезвоню в понедельник» —
        # это «уточнить и вернуться с ответом», а не просто звонок
        base = "clarification"
        priority = max(types[base].priority if base in types else 0, 88)
    elif base == "clarification" and not has_clarify:
        # «Проверю статус и наберу вас» — обещание вернуться, но не уточнение по сути
        priority = min(priority, 55)
    if base == "transfer" and has_internal:
        priority = max(priority, 45)
    return base, priority


def _action_phrase(infinitive: str, clause: str, verb_form: str) -> str:
    idx = clause.lower().find(verb_form.lower())
    if idx < 0:
        return infinitive
    tail = clause[idx + len(verb_form):]
    tail = re.split(r"[,;.!?]", tail)[0]
    # обрезаем на следующем глаголе обещания: «выпишу акт и вышлю…» → два действия
    next_verb = _VERB_RE.search(tail)
    if next_verb:
        tail = tail[: next_verb.start()]
    cut = _TEMPORAL_CUT.search(tail)
    if cut:
        tail = tail[: cut.start()]
    tail = _strip_tail(tail)
    tail = re.sub(r"\s+", " ", tail).strip()
    if len(tail.split()) > 8:
        tail = " ".join(tail.split()[:8])
    phrase = (infinitive + " " + tail).strip()
    return phrase[0].upper() + phrase[1:] if phrase else infinitive


def _custom_candidates(clause: str, custom_types: list[PromiseType]) -> list[PromiseCandidate]:
    """Пользовательские типы: ключевые слова + пересечение с описанием и примерами."""
    clause_norm = normalize_text(clause)
    clause_tokens = set(words(clause))
    found: list[PromiseCandidate] = []
    for ptype in custom_types:
        kw_hits = sum(1 for kw in ptype.normalized_keywords if kw and kw in clause_norm)
        example_tokens = ptype.example_tokens()
        shared = clause_tokens & example_tokens
        overlap = len(shared) / max(1, len(clause_tokens))
        if kw_hits == 0 and (len(shared) < 3 or overlap < 0.2):
            continue
        # для пользовательского типа «глагол» не обязателен, но нужен глагол обещания
        verb_match = _VERB_RE.search(clause)
        if not verb_match:
            continue
        verb = _VERB_BY_FORM[verb_match.group(1).lower()]
        # Пользовательский тип важнее встроенных: его добавили осознанно,
        # чтобы он ловил именно эту формулировку.
        priority = 92 + min(kw_hits, 3) * 2 + (2 if overlap >= 0.34 else 0)
        found.append(
            PromiseCandidate(
                type_code=ptype.code,
                priority=priority,
                verb=verb,
                clause=clause,
                matched_by="custom-rule",
            )
        )
    return found


def _deadline_for(
    clauses: list[str],
    full_text: str,
    call_end: dt.datetime,
    tz: dt.tzinfo,
    next_texts: tuple[str, ...] = (),
) -> Deadline:
    """Выбирает самый ранний явно названный срок; иначе срок по умолчанию.

    Если в самой реплике срока нет, смотрим следующие короткие реплики оператора:
    люди часто говорят «перезвоню» и только потом — «завтра в десять».
    """
    explicit: list[Deadline] = []
    for clause in clauses:
        d = parse_deadline(clause, call_end, tz)
        if d.source not in ("default_24h", "default"):
            explicit.append(d)
    if explicit:
        return min(explicit, key=lambda d: d.due_at)

    whole = parse_deadline(full_text, call_end, tz)
    if whole.source not in ("default_24h", "default"):
        return whole

    for text in next_texts:
        follow = parse_deadline(text, call_end, tz)
        if follow.source not in ("default_24h", "default"):
            return follow

    return whole


def detect_promises(
    call: dict,
    types: list[PromiseType],
    tz: dt.tzinfo | None = None,
) -> list[DetectedPromise]:
    """Возвращает список обещаний оператора в звонке."""
    tz = tz or get_tz()
    transcript = call.get("transcript") or []
    call_end = call_end_for(call, tz)

    type_map = {t.code: t for t in types}
    custom_types = [t for t in types if not t.is_builtin and t.code in type_map]
    builtin_types = {t.code: t for t in types if t.is_builtin} or type_map

    results: list[DetectedPromise] = []

    for index, replica in enumerate(transcript):
        if not isinstance(replica, dict) or not _is_operator(replica.get("speaker", "")):
            continue
        text = (replica.get("text") or "").strip()
        if not text:
            continue

        clauses = split_sentences(text)
        candidates: list[PromiseCandidate] = []

        for clause in clauses:
            clause_norm = normalize_text(clause)
            if not clause_norm:
                continue
            if clause_norm.endswith("?") or _QUESTION_START.match(clause_norm):
                continue
            if _CONDITIONAL.search(clause_norm):
                continue

            verbs: list[Verb] = []
            for m in _VERB_RE.finditer(clause):
                if _NEGATION_BEFORE.search(clause_norm[: m.start()]):
                    continue
                verbs.append(_VERB_BY_FORM[m.group(1).lower()])
            if not verbs:
                continue

            for verb in verbs:
                code, priority = _refine_type(verb, clause_norm, builtin_types, normalize_text(text))
                candidates.append(
                    PromiseCandidate(type_code=code, priority=priority, verb=verb, clause=clause)
                )

            for ptype in custom_types:
                for cand in _custom_candidates(clause, [ptype]):
                    candidates.append(cand)

        if not candidates:
            continue

        # Одна реплика оператора = одно обещание. Несколько вопросов в звонке
        # дают несколько реплик — и, соответственно, несколько задач.
        by_type: dict[str, list[PromiseCandidate]] = {}
        for cand in candidates:
            by_type.setdefault(cand.type_code, []).append(cand)

        ordered_types = sorted(by_type, key=lambda c: -max(x.priority for x in by_type[c]))
        primary_code = ordered_types[0]

        all_clauses = [c.clause for c in candidates]
        next_texts: list[str] = []
        for j in range(index + 1, min(index + 3, len(transcript))):
            follow = transcript[j]
            if not isinstance(follow, dict) or not _is_operator(follow.get("speaker", "")):
                continue
            follow_text = (follow.get("text") or "").strip()
            if follow_text and len(follow_text.split()) <= 12:
                next_texts.append(follow_text)
        deadline = _deadline_for(all_clauses, text, call_end, tz, tuple(next_texts))

        actions: list[str] = []
        for code in ordered_types:
            for cand in by_type[code]:
                for form in cand.verb.forms:
                    if form in normalize_text(cand.clause):
                        phrase = _action_phrase(cand.verb.infinitive, cand.clause, form)
                        if phrase.lower() not in [a.lower() for a in actions]:
                            actions.append(phrase)
                        break
        if not actions:
            actions = [type_map[primary_code].title if primary_code in type_map else primary_code]

        confidence = 0.9
        if deadline.source in ("default_24h", "default"):
            confidence -= 0.15
        if any(h in normalize_text(text) for h in HEDGES):
            confidence -= 0.1
        confidence = round(max(0.3, min(0.99, confidence)), 2)

        results.append(
            DetectedPromise(
                promise_type=primary_code,
                title=_task_title(actions, type_map.get(primary_code)),
                quote=text,
                transcript_index=index,
                actions=actions,
                object=_extract_object(" ".join(all_clauses), primary_code),
                due=deadline,
                confidence=confidence,
                matched_by=by_type[primary_code][0].matched_by,
                secondary_types=[c for c in ordered_types if c != primary_code],
            )
        )

    return results


def _task_title(actions: list[str], ptype: PromiseType | None) -> str:
    """Название задачи: первое действие оператора, иначе — типобещания."""
    if actions:
        candidate = actions[0].strip()
        if 3 <= len(candidate) <= 80:
            return candidate
    return ptype.title if ptype else "Обещание оператора"


def call_end_for(call: dict, tz: dt.tzinfo) -> dt.datetime:
    """Момент окончания звонка в нужном часовом поясе (или «сейчас», если даты нет)."""
    from ..utils import parse_iso

    ended = parse_iso(call.get("ended_at"))
    started = parse_iso(call.get("started_at"))
    base = ended or started or dt.datetime.now(dt.timezone.utc)
    return base.astimezone(tz)


_call_end = call_end_for

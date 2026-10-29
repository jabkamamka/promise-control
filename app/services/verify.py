"""Проверка исполнения обещания по следующим звонкам клиента.

Идея: обещание оператора проверяется не человеком, а клиентом. Когда с того же
номера приходит более поздний звонок, ищем в репликах клиента подтверждение
(«да, перезвонили», «счёт пришёл») или опровержение («никто не позвонил»,
«счёт так и не пришёл»). Подтверждение закрывает задачу, опровержение
переводит её в вычисляемый статус «Не выполнено».

Правила намеренно консервативные:

* смотрим только реплики клиента и только в более поздних звонках;
* для каждого типа проверяем последнюю открытую задачу клиента;
* вопрос, сослагательное наклонение и побуждение («давайте проверим…»)
  доказательством не считаются;
* если в звонке есть и подтверждение, и опровержение, побеждает опровержение;
* неясная реплика ничего не меняет — задача остаётся открытой.

Сервис не коммитит транзакцию: это делает вызывающий код (приём звонка).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
from dataclasses import dataclass
from typing import Any

from ..utils import normalize_text, parse_iso, split_sentences, utc_now

CLIENT_SPEAKERS = {"client", "клиент", "customer", "абонент", "заказчик"}

#: Реплики-вопросы, предположения и побуждения доказательством не являются.
_SKIP = re.compile(
    r"\b(?:если|бы|ли|давай(?:те)?|проверим|проверьте|уточните|скажите|сообщите|"
    r"перезвоните|позвоните|пришлите|вышлите|напишите)\b"
)

_DOC_OBJECT = (
    r"\b(?:документ[а-я]*|счет[а-я]*|акт[а-я]*|договор[а-я]*|накладн[а-я]*|письм[а-я]*|"
    r"файл[а-я]*|справк[а-я]*|выписк[а-я]*|чек|смет[а-я]*|предложени[а-я]*|"
    r"каталог[а-я]*|прайс[а-я]*|скан[а-я]*|оригинал[а-я]*|копи[а-я]*|расчет[а-я]*)"
)
_DOC_DONE = (
    r"\b(?:пришел[а-я]*|пришл[а-я]*|прислал[а-я]*|отправил[а-я]*|выслал[а-я]*|"
    r"направил[а-я]*|скинул[а-я]*|получил[а-я]*|принял[а-я]*)"
)
_VISITOR = r"\b(?:мастер[а-я]*|инженер[а-я]*|бригад[а-я]*|специалист[а-я]*)"
_VISIT_DONE = r"\b(?:приезжал[а-я]*|приехал[а-я]*|пришел[а-я]*|приходил[а-я]*|был[а-я]*)"
_NOTIFY_OBJECT = r"\b(?:смс|уведомлен[а-я]*|напоминани[а-я]*|подтверждени[а-я]*)"

#: Шаблоны по каждому встроенному типу: сначала опровержение, потом подтверждение.
_EVIDENCE: dict[str, dict[str, tuple[str, ...]]] = {
    "callback": {
        "refuted": (
            r"\bне\s+перезвонил[а-я]?",
            r"\bне\s+позвонил[а-я]?",
            r"\bне\s+набрал[а-я]?",
            r"\bне\s+созвонил[а-я]*",
            r"\bне\s+связал[а-я]*",
            r"\bне\s+дозвон[а-я]*",
            r"\bникто не (?:позвонил|перезвонил|звонил)[а-я]*",
            r"\bне\s+звонил[а-я]*",
            r"\bтишин[а-я]*\b",
            r"\bне\s+дождал[а-я]*\b",
        ),
        "confirmed": (
            r"\bперезвонил[а-я]?",
            r"\bпозвонил[а-я]?",
            r"\bнабрал[а-я]?",
            r"\bсозвонил[а-я]*",
            r"\bсвязал[а-я]*",
            r"\bдозвонил[а-я]*",
            r"\bзвонок был\b",
        ),
    },
    "documents": {
        "refuted": (
            rf"{_DOC_OBJECT}[^.!?]{{0,40}}\bне\s+{_DOC_DONE}",
            rf"\bне\s+{_DOC_DONE}[^.!?]{{0,40}}{_DOC_OBJECT}",
            rf"{_DOC_OBJECT}[^.!?]{{0,20}}\b(?:нет|отсутствует)\b",
            r"\bничего не (?:пришл[а-я]*|получил[а-я]*|прислал[а-я]*)\b",
        ),
        "confirmed": (
            rf"{_DOC_OBJECT}[^.!?]{{0,40}}{_DOC_DONE}",
            rf"{_DOC_DONE}[^.!?]{{0,40}}{_DOC_OBJECT}",
        ),
    },
    "clarification": {
        "refuted": (
            r"\bне\s+(?:уточнил[а-я]*|выяснил[а-я]*|сообщил[а-я]*|сказал[а-я]*|"
            r"ответил[а-я]*|перезвонил[а-я]*|узнал[а-я]*)",
            r"\bничего не (?:сказал[а-я]*|сообщил[а-я]*|ответил[а-я]*|уточнил[а-я]*)",
            r"\bникто не (?:сказал|сообщил|ответил)[а-я]*",
            r"\b(?:ответа|информации|уточнения)\s+(?:так и\s+)?нет\b",
            r"\bбез ответа\b",
        ),
        "confirmed": (
            r"\bуточнил[а-я]?",
            r"\bвыяснил[а-я]?",
            r"\bсообщил[а-я]?",
            r"\bответил[а-я]?",
            r"\bузнал[а-я]?",
            r"\bуведомил[а-я]*",
            r"\bрассказал[а-я]*",
            r"\bобъяснил[а-я]*",
            r"\b(?:дал|дали) знать\b",
            r"\bвернул[а-я]* с ответом\b",
        ),
    },
    "visit": {
        "refuted": (
            rf"{_VISITOR}[^.!?]{{0,30}}\bне\s+{_VISIT_DONE}",
            rf"\bне\s+{_VISIT_DONE}[^.!?]{{0,30}}{_VISITOR}",
            r"\bникто не приезжал[а-я]*",
            r"\bмастера не было\b",
            r"\bникого не было\b",
        ),
        "confirmed": (
            rf"{_VISITOR}[^.!?]{{0,30}}{_VISIT_DONE}",
            rf"{_VISIT_DONE}[^.!?]{{0,30}}{_VISITOR}",
        ),
    },
    "fix": {
        "refuted": (
            r"\bне\s+(?:исправил[а-я]*|пересчитал[а-я]*|починил[а-я]*)",
            r"\bденьги не (?:вернул[а-я]*|пришл[а-я]*|пришел[а-я]*)\b",
            rf"\bвозврат[а-я]*[^.!?]{{0,20}}\bне (?:пришел[а-я]*|пришл[а-я]*|"
            r"оформ[а-я]*|сделал[а-я]*)\b",
        ),
        "confirmed": (
            r"\bисправил[а-я]*",
            r"\bпересчитал[а-я]*",
            r"\bпочинил[а-я]*",
            r"\bвозврат[а-я]*[^.!?]{0,20}(?:пришел[а-я]*|пришл[а-я]*|получил[а-я]*|"
            r"оформил[а-я]*|сделал[а-я]*|вернул[а-я]*)",
            r"\b(?:оформил[а-я]*|сделал[а-я]*|получил[а-я]*)"
            r"[^.!?]{0,20}\bвозврат[а-я]*",
            r"\bденьги (?:вернул[а-я]*|пришл[а-я]*|пришел[а-я]*)\b",
        ),
    },
    "transfer": {
        "refuted": (
            r"\bне\s+передал[а-я]*",
            r"\bне\s+принял[а-я]*",
            r"\bникто не (?:передал|принял)[а-я]*",
            r"\bзаявк[а-я]*[^.!?]{0,20}\bне (?:передал[а-я]*|принял[а-я]*)\b",
        ),
        "confirmed": (
            r"\bпередал[а-я]*",
            r"\bпринял[а-я]*",
            r"\bзарегистрировал[а-я]*",
            r"\bв курсе\b",
        ),
    },
    "notification": {
        "refuted": (
            rf"{_NOTIFY_OBJECT}[^.!?]{{0,30}}\bне (?:пришел[а-я]*|пришл[а-я]*|получил[а-я]*)\b",
            rf"\bне (?:пришел[а-я]*|пришл[а-я]*|получил[а-я]*)[^.!?]{{0,30}}{_NOTIFY_OBJECT}",
            rf"{_NOTIFY_OBJECT}[^.!?]{{0,20}}\bне было\b",
            r"\b(?:смс|уведомлени[а-я]*|напоминани[а-я]*)\s+(?:так и\s+)?нет\b",
        ),
        "confirmed": (
            rf"{_NOTIFY_OBJECT}[^.!?]{{0,30}}(?:пришел[а-я]*|пришл[а-я]*|получил[а-я]*|приход[а-я]*)",
            rf"(?:пришел[а-я]*|пришл[а-я]*|получил[а-я]*)[^.!?]{{0,30}}{_NOTIFY_OBJECT}",
        ),
    },
}

_COMPILED: dict[str, dict[str, tuple[re.Pattern[str], ...]]] = {
    code: {
        kind: tuple(re.compile(pattern) for pattern in patterns)
        for kind, patterns in rules.items()
    }
    for code, rules in _EVIDENCE.items()
}


@dataclass
class Evidence:
    status: str  # confirmed | refuted
    quote: str


def find_evidence(transcript: list[dict[str, Any]], type_code: str) -> Evidence | None:
    """Ищет в репликах клиента подтверждение или опровержение обещания."""
    rules = _COMPILED.get(type_code)
    if not rules:
        return None

    sentences: list[tuple[str, str]] = []
    for replica in transcript or []:
        if not isinstance(replica, dict):
            continue
        if normalize_text(str(replica.get("speaker") or "")) not in CLIENT_SPEAKERS:
            continue
        for sentence in split_sentences(str(replica.get("text") or "")):
            normalized = normalize_text(sentence)
            if not normalized or "?" in normalized or _SKIP.search(normalized):
                continue
            sentences.append((sentence.strip(), normalized))

    for status in ("refuted", "confirmed"):
        for original, normalized in sentences:
            if any(pattern.search(normalized) for pattern in rules[status]):
                return Evidence(status=status, quote=original)
    return None


def _apply(
    conn: sqlite3.Connection,
    task: dict[str, Any],
    evidence: Evidence,
    call_id: str,
    now: str,
) -> None:
    if evidence.status == "confirmed":
        conn.execute(
            """UPDATE tasks
               SET status = 'done', closed_at = ?, updated_at = ?,
                   verification_status = 'confirmed', verified_at = ?,
                   verified_call_id = ?, verification_quote = ?
               WHERE id = ?""",
            (now, now, now, call_id, evidence.quote, task["id"]),
        )
        to_status = "done"
        comment = f"Клиент подтвердил исполнение в звонке {call_id}: «{evidence.quote}»"
    else:
        conn.execute(
            """UPDATE tasks
               SET updated_at = ?, verification_status = 'refuted', verified_at = ?,
                   verified_call_id = ?, verification_quote = ?
               WHERE id = ?""",
            (now, now, call_id, evidence.quote, task["id"]),
        )
        to_status = None
        comment = (
            f"Клиент сообщил, что обещание не исполнено, в звонке {call_id}: "
            f"«{evidence.quote}»"
        )

    conn.execute(
        "INSERT INTO task_events (task_id, event, from_status, to_status, comment, at) "
        "VALUES (?,?,?,?,?,?)",
        (task["id"], "verified", task["status"], to_status, comment, now),
    )


def _load_calls(conn: sqlite3.Connection, phone: str) -> list[tuple[dt.datetime, str, list[dict]]]:
    rows = conn.execute(
        "SELECT id, started_at, ended_at, transcript FROM calls WHERE client_phone = ?",
        (phone,),
    ).fetchall()
    calls: list[tuple[dt.datetime, str, list[dict]]] = []
    for row in rows:
        start = parse_iso(row["started_at"]) or parse_iso(row["ended_at"])
        if not start:
            continue
        try:
            transcript = json.loads(row["transcript"] or "[]")
        except json.JSONDecodeError:
            continue
        calls.append((start, row["id"], transcript))
    calls.sort(key=lambda item: (item[0], item[1]))
    return calls


def _load_open_tasks(conn: sqlite3.Connection, phone: str) -> dict[str, list[dict[str, Any]]]:
    rows = conn.execute(
        """SELECT t.rowid AS task_rowid, t.id, t.promise_type, t.status,
                  t.call_id, c.started_at AS call_started_at, c.ended_at AS call_ended_at
           FROM tasks t
           JOIN calls c ON c.id = t.call_id
           WHERE c.client_phone = ? AND t.status != 'done'
             AND t.verification_status IS NULL""",
        (phone,),
    ).fetchall()

    by_call: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        start = parse_iso(row["call_started_at"]) or parse_iso(row["call_ended_at"])
        if not start:
            continue
        by_call.setdefault(row["call_id"], []).append(
            {
                "id": row["id"],
                "type": row["promise_type"],
                "status": row["status"],
                "start": start,
                "rowid": int(row["task_rowid"]),
            }
        )
    return by_call


def verify_phone(conn: sqlite3.Connection, phone: str) -> int:
    """Пересчитывает проверки по всем звонкам телефона. Возвращает число событий.

    История обрабатывается в хронологическом порядке, поэтому результат не
    зависит от того, в каком порядке пришли вебхуки. Для каждого звонка
    проверяется последняя открытая задача каждого типа из более ранних
    звонков; собственные обещания звонка его же репликами не подтверждаются.
    """
    phone = str(phone or "").strip()
    if not phone:
        return 0

    calls = _load_calls(conn, phone)
    if len(calls) < 2:
        return 0
    open_by_call = _load_open_tasks(conn, phone)
    # один звонок может проверить не больше одной задачи каждого типа,
    # повторный пересчёт не должен «доедать» старые задачи тем же доказательством
    used = {
        (row["verified_call_id"], row["promise_type"])
        for row in conn.execute(
            "SELECT DISTINCT verified_call_id, promise_type FROM tasks "
            "WHERE verified_call_id IS NOT NULL"
        )
    }

    open_tasks: list[dict[str, Any]] = []
    now = utc_now()
    verified = 0
    for start, call_id, transcript in calls:
        latest: dict[str, dict[str, Any]] = {}
        for task in open_tasks:
            if task["start"] >= start:
                continue
            current = latest.get(task["type"])
            if current is None or (task["start"], task["rowid"]) > (
                current["start"],
                current["rowid"],
            ):
                latest[task["type"]] = task

        for type_code, task in latest.items():
            if (call_id, type_code) in used:
                continue
            evidence = find_evidence(transcript, type_code)
            if not evidence:
                continue
            _apply(conn, task, evidence, call_id, now)
            open_tasks.remove(task)
            used.add((call_id, type_code))
            verified += 1

        open_tasks.extend(open_by_call.get(call_id, []))

    return verified

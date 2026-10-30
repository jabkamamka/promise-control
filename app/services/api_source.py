"""Загрузка новых звонков из API партнёра — необязательный путь для демонстрации.

Основной сценарий (вебхук от программы-отправителя) от этого модуля не зависит:
без сети и без сервисного токена сервис работает как обычно, а кнопка
«Загрузить ещё из API» честно отвечает ошибкой.

Почему так сложно: у API нет страниц. Параметр ``count`` он игнорирует и отдаёт
фиксированную небольшую порцию, каждый раз новую. Поэтому «ещё 10–20 задач»
набирается не одним запросом, а несколькими порциями, причём повторы нужно
отсеивать по тексту расшифровки — у одного и того же разговора может быть новый id.
"""

from __future__ import annotations

import json
import re
import sqlite3
import threading
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any, Callable

from pydantic import ValidationError

from ..config import settings
from ..schemas import CallIn
from .detect import detect_promises
from .ingest import ingest_payload
from .tasks import load_types

#: Один заход в API за раз: два одновременных нажатия иначе могут выбрать одни и те же
#: звонки и создать задачи-двойники.
_PULL_LOCK = threading.Lock()

#: API отдаёт порцию фиксированного размера и не слушает count — проверено руками.
REQUEST_TIMEOUT = 30

#: Сколько порций запрашивать за одно нажатие кнопки.
DEFAULT_ATTEMPTS = 8


class ApiSourceError(RuntimeError):
    """API недоступен или не настроен. Текст показывается сотруднику в панели."""


@dataclass(frozen=True)
class Candidate:
    """Звонок из API, которого ещё нет в базе, и предсказанное число задач."""

    call: dict[str, Any]
    promises: int
    types: list[str] = field(default_factory=list)


def is_configured() -> bool:
    """Настроен ли поход в API: нужны адрес и сервисный токен."""
    return bool((settings.api_base or "").strip() and (settings.api_service_token or "").strip())


def transcript_key(rows: list[dict[str, Any]] | None) -> str:
    """Отпечаток расшифровки: ловит тот же разговор, пришедший с другим id."""
    parts = []
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        text = re.sub(r"\s+", " ", str(row.get("text") or "")).strip().lower()
        parts.append(f"{row.get('speaker')}:{text}")
    return "|".join(parts)


def _request(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={"X-Service-Token": token, "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=REQUEST_TIMEOUT) as response:
            return json.loads(response.read().decode())
    except urllib.error.HTTPError as error:
        if error.code in (401, 403):
            raise ApiSourceError(
                "API отклонил сервисный токен — проверьте URALMICRO_SERVICE_TOKEN"
            ) from error
        raise ApiSourceError(f"API ответил ошибкой {error.code}") from error
    except urllib.error.URLError as error:
        raise ApiSourceError(f"API недоступен: {error.reason}") from error
    except (TimeoutError, OSError) as error:
        raise ApiSourceError(f"API не ответил за {REQUEST_TIMEOUT} с: {error}") from error
    except json.JSONDecodeError as error:
        raise ApiSourceError("API вернул не JSON — похоже, адрес указан неверно") from error


def fetch_calls(attempts: int = DEFAULT_ATTEMPTS) -> list[dict[str, Any]]:
    """Собирает звонки из нескольких порций API, отбрасывая повторы по id."""
    if not is_configured():
        raise ApiSourceError("Не заданы URALMICRO_API_BASE и URALMICRO_SERVICE_TOKEN")

    base = settings.api_base.rstrip("/")
    token = settings.api_service_token
    collected: dict[str, dict[str, Any]] = {}
    for _ in range(max(1, attempts)):
        payload = _request(f"{base}/calls?count=50", token)
        items = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(items, list):
            raise ApiSourceError("API вернул неожиданный формат списка звонков")
        fresh = [
            item
            for item in items
            if isinstance(item, dict) and item.get("id") and item["id"] not in collected
        ]
        for item in fresh:
            collected[item["id"]] = item
        if not fresh:  # API начал повторяться — дальше просить бессмысленно
            break
    return list(collected.values())


def candidates(conn: sqlite3.Connection, calls: list[dict[str, Any]]) -> list[Candidate]:
    """Оставляет звонки, которых нет в базе ни по id, ни по тексту расшифровки."""
    known_ids = {row["id"] for row in conn.execute("SELECT id FROM calls")}
    known_texts = {
        transcript_key(json.loads(row["transcript"] or "[]"))
        for row in conn.execute("SELECT transcript FROM calls")
    }
    types = load_types(conn)
    seen_ids: set[str] = set()
    seen_texts: set[str] = set(known_texts)
    result: list[Candidate] = []

    for raw in calls:
        call_id = raw.get("id")
        if not call_id or call_id in known_ids or call_id in seen_ids:
            continue
        key = transcript_key(raw.get("transcript") or [])
        if not key or key in seen_texts:
            continue
        try:
            parsed = CallIn.model_validate(raw)
        except ValidationError:
            continue
        seen_ids.add(call_id)
        seen_texts.add(key)
        call = parsed.model_dump(mode="json")
        promises = detect_promises(call, types)
        result.append(
            Candidate(
                call=call,
                promises=len(promises),
                types=[promise.promise_type for promise in promises],
            )
        )
    return result


def pick(items: list[Candidate], low: int, target: int, high: int) -> list[Candidate]:
    """Набирает порцию так, чтобы сумма задач попала в диапазон ``low``…``high``.

    Идём от коротких звонков к длинным: в порцию попадает больше разных клиентов,
    а не два «тяжёлых» разговора на всю квоту.
    """
    chosen: list[Candidate] = []
    total = 0
    for item in sorted(items, key=lambda candidate: candidate.promises):
        if item.promises <= 0 or total + item.promises > high:
            continue
        if total >= target:
            break
        chosen.append(item)
        total += item.promises
    if total < low:  # добор, если коротких звонков оказалось мало
        for item in items:
            if item in chosen or item.promises <= 0 or total + item.promises > high:
                continue
            chosen.append(item)
            total += item.promises
            if total >= low:
                break
    if not chosen:
        # Все звонки в порции оказались длиннее max: лучше один такой, чем «новых нет».
        positive = [item for item in items if item.promises > 0]
        if positive:
            chosen = [min(positive, key=lambda candidate: candidate.promises)]
    return chosen


def pull(
    conn: sqlite3.Connection,
    min_tasks: int = 10,
    target_tasks: int = 15,
    max_tasks: int = 20,
    attempts: int = DEFAULT_ATTEMPTS,
    fetcher: Callable[..., list[dict[str, Any]]] | None = None,
) -> dict[str, Any]:
    """Готовит порцию звонков под нужное число новых задач.

    Возвращает словарь: сама порция (``calls``), план (``planned``) и счётчики,
    которые удобно показать в панели. Ничего не пишет в базу — это делает вызывающий.
    """
    if not 1 <= min_tasks <= target_tasks <= max_tasks:
        raise ValueError("Ожидается 1 ≤ min_tasks ≤ target_tasks ≤ max_tasks")

    load = fetcher or fetch_calls
    fetched = load(attempts=attempts)
    items = candidates(conn, fetched)
    chosen = pick(items, min_tasks, target_tasks, max_tasks)

    # Первая порция бывает бедной: API отдаёт случайные звонки, часть уже загружена.
    # Тогда просим ещё, прежде чем честно сказать «новых почти нет».
    if sum(item.promises for item in chosen) < min_tasks:
        known = {call["id"] for call in fetched}
        extra = [
            call
            for call in load(attempts=max(attempts * 2, attempts + 8))
            if call.get("id") not in known
        ]
        if extra:
            fetched = fetched + extra
            items = candidates(conn, fetched)
            chosen = pick(items, min_tasks, target_tasks, max_tasks)

    planned = sum(item.promises for item in chosen)
    return {
        "fetched": len(fetched),
        "skipped": len(fetched) - len(items),
        "planned": planned,
        "calls": [item.call for item in chosen],
        "types": [item.types for item in chosen],
    }


def fetch_and_ingest(
    conn: sqlite3.Connection,
    min_tasks: int = 10,
    target_tasks: int = 15,
    max_tasks: int = 20,
) -> dict[str, Any]:
    """Забирает порцию из API и сразу создаёт задачи — целиком под блокировкой.

    Возвращает результат ``pull`` плюс поле ``ingest`` с отчётом вебхука (``None``,
    если новых расшифровок не нашлось).
    """
    with _PULL_LOCK:
        batch = pull(conn, min_tasks, target_tasks, max_tasks)
        batch["ingest"] = ingest_payload(conn, batch["calls"]) if batch["calls"] else None
        return batch

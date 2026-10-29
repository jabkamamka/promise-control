"""Необязательный LLM-адаптер (OpenAI-совместимый API).

Зачем: правила работают офлайн и объяснимо, но не понимают незнакомые формулировки.
LLM-режим — второй проход, который ищет обещания «по смыслу». Он **выключен по умолчанию**:
`LLM_ENABLED=0`. Если ключа нет или сервис недоступен, приём звонков продолжает работать
на правилах — ошибка LLM не влияет на основной сценарий.

Контракт с моделью: на входе — реплики оператора с индексами и справочник типов,
на выходе — строго JSON-массив `{"index": int, "type": "код типа", "quote": "реплика"}`.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

from ..config import settings
from .taxonomy import PromiseType

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "Ты помогаешь контакт-центру контролировать обещания операторов. "
    "Тебе дают реплики оператора из расшифровки звонка и справочник типов обещаний. "
    "Найди только те реплики, где оператор сам обязуется что-то сделать для клиента "
    "(позвонить, отправить документы, уточнить и вернуться с ответом и т.п.). "
    "Не считай обещанием вопросы, констатацию факта, прошедшее время и слова клиента. "
    "Ответь строго JSON-массивом без пояснений: "
    '[{"index": <номер реплики>, "type": "<код типа>", "quote": "<текст реплики>"}]. '
    "Если обещаний нет — верни []."
)


@dataclass
class LLMPromise:
    index: int
    type_code: str
    quote: str


def _build_user_prompt(replicas: list[tuple[int, str]], types: list[PromiseType]) -> str:
    types_block = "\n".join(f"- {t.code}: {t.title}. {t.description}" for t in types)
    replicas_block = "\n".join(f"[{i}] {text}" for i, text in replicas)
    return (
        f"Типы обещаний:\n{types_block}\n\n"
        f"Реплики оператора:\n{replicas_block}\n\n"
        "Верни JSON-массив найденных обещаний."
    )


def _strip_code_fences(raw: str) -> str:
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    return text.strip()


def _parse_response(raw: str, valid_codes: set[str], max_index: int) -> list[LLMPromise]:
    try:
        data = json.loads(_strip_code_fences(raw))
    except json.JSONDecodeError:
        logger.warning("LLM вернул не-JSON, игнорирую ответ")
        return []
    if isinstance(data, dict):
        data = data.get("promises", [])
    if not isinstance(data, list):
        return []

    result: list[LLMPromise] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        try:
            index = int(item.get("index"))
        except (TypeError, ValueError):
            continue
        type_code = str(item.get("type") or "").strip()
        quote = str(item.get("quote") or "").strip()
        if 0 <= index <= max_index and type_code in valid_codes and quote:
            result.append(LLMPromise(index=index, type_code=type_code, quote=quote))
    return result


def _call_model(prompt: str) -> str:  # pragma: no cover - сетевой вызов
    import httpx

    response = httpx.post(
        f"{settings.llm_base_url.rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {settings.llm_api_key}"},
        json={
            "model": settings.llm_model,
            "temperature": 0,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
        },
        timeout=settings.llm_timeout,
    )
    response.raise_for_status()
    payload = response.json()
    return payload["choices"][0]["message"]["content"]


def detect_with_llm(call: dict, types: list[PromiseType]) -> list[LLMPromise]:
    """Возвращает обещания по версии LLM. При любой ошибке — пустой список."""
    if not settings.llm_enabled or not settings.llm_api_key:
        return []

    replicas: list[tuple[int, str]] = []
    for index, replica in enumerate(call.get("transcript") or []):
        if not isinstance(replica, dict):
            continue
        if str(replica.get("speaker", "")).lower() not in {"operator", "оператор", "op", "manager", "agent"}:
            continue
        text = (replica.get("text") or "").strip()
        if text:
            replicas.append((index, text))
    if not replicas:
        return []

    prompt = _build_user_prompt(replicas, types)
    try:
        raw = _call_model(prompt)
    except Exception as exc:  # сеть, таймаут, 4xx/5xx — не ломаем приём звонков
        logger.warning("LLM недоступен: %s", exc)
        return []

    return _parse_response(raw, {t.code for t in types}, max(i for i, _ in replicas))

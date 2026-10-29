"""Делает телефоны в датасетах уникальными и добавляет пары звонков для проверки исполнения.

Маска «+7*******50» склеивала разных клиентов: проверка исполнения принимала чужие
реплики за подтверждение/опровержение. Здесь каждому звонку даётся свой синтетический
номер (префикс 900), а для демонстрации проверки добавляются две пары звонков.
"""
from __future__ import annotations

import hashlib
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data")
VERIFY_FILE = os.path.join(DATA, "sample_verification.json")


def phone_for(call_id: str) -> str:
    digest = hashlib.sha1(call_id.encode("utf-8")).hexdigest()
    digits = "".join(str(int(ch, 16) % 10) for ch in digest[:7])
    return "+7900" + digits


def rewrite(name: str) -> None:
    path = os.path.join(DATA, name)
    calls = json.load(open(path, encoding="utf-8"))
    seen: dict[str, str] = {}
    for call in calls:
        phone = phone_for(call["id"])
        while phone in seen:  # на всякий случай
            phone = phone[:-1] + str((int(phone[-1]) + 1) % 10)
        seen[phone] = call["id"]
        call["client_phone"] = phone
    json.dump(calls, open(path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print(f"{name}: телефонов {len(seen)} на {len(calls)} звонков")


def build_verification_demo() -> None:
    phone_ok = "+79001110001"
    phone_bad = "+79001110002"

    calls = [
        {
            "id": "demo-verify-callback-1",
            "operator_id": 3,
            "client_phone": phone_ok,
            "started_at": "2026-10-27T09:00:00Z",
            "ended_at": "2026-10-27T09:04:00Z",
            "transcript": [
                {"speaker": "operator", "text": "Добрый день, компания «Сфера», оператор Сергей."},
                {"speaker": "client", "text": "Когда будет готов мой заказ?"},
                {"speaker": "operator", "text": "Перезвоню вам завтра в десять утра и скажу точные сроки."},
                {"speaker": "client", "text": "Хорошо, жду."},
            ],
        },
        {
            "id": "demo-verify-callback-2",
            "operator_id": 3,
            "client_phone": phone_ok,
            "started_at": "2026-10-28T12:00:00Z",
            "ended_at": "2026-10-28T12:03:00Z",
            "transcript": [
                {"speaker": "operator", "text": "Добрый день, компания «Сфера», оператор Сергей."},
                {"speaker": "client", "text": "Да, мне вчера перезвонили, всё рассказали. Спасибо."},
                {"speaker": "operator", "text": "Рад помочь, хорошего дня."},
            ],
        },
        {
            "id": "demo-verify-docs-1",
            "operator_id": 5,
            "client_phone": phone_bad,
            "started_at": "2026-10-27T14:00:00Z",
            "ended_at": "2026-10-27T14:05:00Z",
            "transcript": [
                {"speaker": "operator", "text": "Добрый день, компания «Вектор», оператор Мария."},
                {"speaker": "client", "text": "Для бухгалтерии нужен акт выполненных работ."},
                {"speaker": "operator", "text": "Выпишу акт и вышлю на электронную почту до пятницы."},
                {"speaker": "client", "text": "Спасибо."},
            ],
        },
        {
            "id": "demo-verify-docs-2",
            "operator_id": 5,
            "client_phone": phone_bad,
            "started_at": "2026-10-31T10:00:00Z",
            "ended_at": "2026-10-31T10:04:00Z",
            "transcript": [
                {"speaker": "operator", "text": "Добрый день, компания «Вектор», оператор Мария."},
                {"speaker": "client", "text": "Акт так и не пришёл, мы уже отправили жалобу."},
                {"speaker": "operator", "text": "Приношу извинения, отправлю сегодня повторно."},
            ],
        },
    ]
    json.dump(calls, open(VERIFY_FILE, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("файл демонстрации проверки:", VERIFY_FILE, len(calls), "звонка")


if __name__ == "__main__":
    rewrite("sample_calls.json")
    rewrite("sample_calls_extra.json")
    build_verification_demo()

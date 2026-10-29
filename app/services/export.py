"""Выгрузка задач в CSV: руководитель смены открывает файл в Excel.

Отдельный модуль, существующие функции не меняет — использует публичный
`list_tasks` из services/tasks.py и те же фильтры, что и API.
"""
from __future__ import annotations

import csv
import io
import sqlite3
from typing import Any

from .tasks import list_tasks

COLUMNS = [
    ("id", "ID задачи"),
    ("created_at", "Создана"),
    ("due_at", "Срок"),
    ("due_hint", "Фраза срока"),
    ("status", "Статус"),
    ("effective_status", "Фактический статус"),
    ("promise_type", "Тип"),
    ("promise_type_title", "Тип (название)"),
    ("title", "Задача"),
    ("object", "Объект"),
    ("quote", "Цитата оператора"),
    ("operator_id", "Оператор"),
    ("call_id", "Звонок"),
    ("verification_status", "Проверка"),
    ("verification_quote", "Цитата клиента"),
    ("confidence", "Уверенность"),
    ("matched_by", "Найдено"),
]


def _row_value(task: dict[str, Any], key: str) -> str:
    value = task.get(key)
    if value is None:
        return ""
    if key == "confidence":
        return f"{round(float(value) * 100)}%"
    return str(value).replace("\n", " ").strip()


def tasks_csv(conn: sqlite3.Connection, max_rows: int = 20000, **filters: Any) -> str:
    items, _total = list_tasks(conn, limit=max_rows, offset=0, **filters)

    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow([title for _, title in COLUMNS])
    for task in items:
        writer.writerow([_row_value(task, key) for key, _ in COLUMNS])
    # BOM нужен Excel, иначе кириллица открывается кракозябрами
    return "\ufeff" + buffer.getvalue()


def filename(prefix: str = "tasks") -> str:
    from ..utils import utc_now

    return f"{prefix}_{utc_now()[:10]}.csv"

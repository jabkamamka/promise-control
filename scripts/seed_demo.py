"""Загружает демонстрационные звонки из data/sample_calls.json в базу.

Запуск:  python scripts/seed_demo.py
Повторный запуск безопасен: звонки с теми же id не создадут дублей.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connect, init_db  # noqa: E402
from app.services.ingest import ingest_payload  # noqa: E402


def main() -> None:
    path = ROOT / "data" / "sample_calls.json"
    if not path.exists():
        raise SystemExit(f"Нет файла {path}")
    calls = json.loads(path.read_text(encoding="utf-8"))
    init_db()
    with connect() as conn:
        result = ingest_payload(conn, calls)
    print(
        f"Принято звонков: {result['received']}, обработано: {result['processed']}, "
        f"дублей: {result['duplicates']}, ошибок: {result['failed']}, "
        f"создано задач: {result['tasks_created']}"
    )


if __name__ == "__main__":
    main()

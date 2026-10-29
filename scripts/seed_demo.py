"""Загружает в базу звонки из data/sample_calls.json — это выборка, полученная из API.

Запуск:  python scripts/seed_demo.py [--file sample_calls.json]

Данные не меняются: время, операторы, телефоны и расшифровки берутся как есть.
Повторный запуск безопасен — звонки с теми же id не создадут дублей.

Живой приём звонков проверяется программой-отправителем из кейса:
    .\\sender_windows_amd64.exe -t <service_token> -w http://localhost:8080/webhook/calls
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connect, init_db  # noqa: E402
from app.services.ingest import ingest_payload  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="sample_calls.json", help="файл с звонками в data/")
    args = parser.parse_args()

    path = ROOT / "data" / args.file
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

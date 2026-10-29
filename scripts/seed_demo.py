"""Загружает демонстрационные звонки из data/sample_calls.json в базу.

Запуск:
    python scripts/seed_demo.py                # как есть, с исходными временами
    python scripts/seed_demo.py --shift-now    # сдвинуть времена к текущему моменту

Повторный запуск безопасен: звонки с теми же id не создадут дублей.
Флаг --shift-now полезен для демонстрации: свежие звонки дают задачи в будущем,
а не пачку просроченных из прошлого.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.db import connect, init_db  # noqa: E402
from app.services.demo import apply_progress  # noqa: E402
from app.services.ingest import ingest_payload  # noqa: E402
from app.utils import parse_iso, to_iso  # noqa: E402


def shift_to_now(calls: list[dict]) -> list[dict]:
    """Сдвигает все звонки так, чтобы самый поздний заканчивался сейчас."""
    return _shifted(calls, anchor=dt.datetime.now(dt.timezone.utc))


def spread_over(calls: list[dict], days: int) -> list[dict]:
    """Раскладывает звонки по последним `days` дням — так графики выглядят как живые."""
    ordered = sorted(calls, key=lambda c: c.get("ended_at") or "")
    if not ordered:
        return calls
    now = dt.datetime.now(dt.timezone.utc)
    span = dt.timedelta(days=max(1, days))
    step = span / max(1, len(ordered))
    shifted = []
    for index, call in enumerate(ordered):
        end = now - span + step * (index + 1)
        shifted.append(_shifted([call], anchor=end)[0])
    return shifted


def _shifted(calls: list[dict], anchor: dt.datetime) -> list[dict]:
    ends = [parse_iso(c.get("ended_at")) for c in calls if c.get("ended_at")]
    ends = [e for e in ends if e]
    if not ends:
        return calls
    delta = anchor - max(ends)
    shifted = []
    for call in calls:
        item = dict(call)
        for key in ("started_at", "ended_at"):
            moment = parse_iso(item.get(key))
            if moment:
                item[key] = to_iso(moment + delta)
        shifted.append(item)
    return shifted


def _place_verification_pairs(pairs: list[dict]) -> list[dict]:
    """Ставит пары проверки в последние дни: обещание → более поздний звонок клиента."""
    now = dt.datetime.now(dt.timezone.utc)
    offsets = {0: 4, 1: 3, 2: 6, 3: 2}  # дни назад для каждого из четырёх звонков
    placed = []
    for index, call in enumerate(pairs):
        item = dict(call)
        target = now - dt.timedelta(days=offsets.get(index, 3))
        shifted = _shifted([item], anchor=target)[0]
        placed.append(shifted)
    return sorted(placed, key=lambda c: c.get("started_at") or "")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shift-now", action="store_true", help="сдвинуть времена звонков к текущему моменту")
    parser.add_argument("--file", default="sample_calls.json", help="файл с звонками в data/")
    parser.add_argument("--progress", action="store_true", help="демо: закрыть часть задач и взять часть в работу")
    parser.add_argument("--spread", type=int, default=0, help="демо: разложить звонки по последним N дням")
    parser.add_argument("--verification", action="store_true", help="демо: добавить пары звонков для проверки исполнения")
    args = parser.parse_args()

    path = ROOT / "data" / args.file
    if not path.exists():
        raise SystemExit(f"Нет файла {path}")
    calls = json.loads(path.read_text(encoding="utf-8"))
    if args.spread:
        calls = spread_over(calls, args.spread)
    elif args.shift_now:
        calls = shift_to_now(calls)

    init_db()
    extra: list[dict] = []
    if args.verification:
        pairs = json.loads((ROOT / "data" / "sample_verification.json").read_text(encoding="utf-8"))
        extra = _place_verification_pairs(pairs)

    with connect() as conn:
        result = ingest_payload(conn, calls)
        if extra:
            verification_result = ingest_payload(conn, extra)
            result["tasks_created"] += verification_result["tasks_created"]
            result["received"] += verification_result["received"]
            result["processed"] += verification_result["processed"]
        progress = apply_progress(conn) if args.progress else None
    print(
        f"Принято звонков: {result['received']}, обработано: {result['processed']}, "
        f"дублей: {result['duplicates']}, ошибок: {result['failed']}, "
        f"создано задач: {result['tasks_created']}"
    )
    if progress:
        print(f"Демо-прогресс: выполнено {progress['done']}, в работе {progress['in_progress']}")


if __name__ == "__main__":
    main()

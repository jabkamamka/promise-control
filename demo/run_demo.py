"""Сквозной демонстрационный сценарий.

Запуск (в отдельном окне):
    uvicorn app.main:app --port 8000
    python demo/run_demo.py

Скрипт ничего не знает о внутренностях сервиса: он ходит в API так же, как это
делал бы вебхук отправителя или фронтенд оператора.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8000"
ROOT = Path(__file__).resolve().parent.parent
CALLS = ROOT / "demo" / "calls_demo.json"

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")


def api(method: str, path: str, payload: dict | list | None = None):
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(
        BASE + path, data=data, method=method,
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", "replace")
        raise SystemExit(f"{method} {path} -> {exc.code}: {body}") from exc
    except urllib.error.URLError as exc:
        raise SystemExit(
            f"Не удалось подключиться к {BASE}. Запустите сервер:\n"
            f"  uvicorn app.main:app --port 8000\n({exc.reason})"
        ) from exc


def line(char: str = "=", width: int = 90) -> None:
    print(char * width)


def show_tasks(tasks: list[dict], title: str) -> None:
    print(f"\n{title}")
    if not tasks:
        print("  (пусто)")
        return
    print(f"  {'id':>4}  {'тип':<22} {'статус':<12} {'срок':<20} {'оператор':<10} цитата")
    for task in tasks:
        quote = (task["quote"] or "").replace("\n", " ")
        if len(quote) > 40:
            quote = quote[:37] + "..."
        due = task["due_at"].replace("T", " ")[:16]
        print(f"  {task['id']:>4}  {task['type_code']:<22} {task['status_label']:<12} {due:<20} "
              f"{task['operator_id']:<10} {quote}")


def make_fresh(calls: list[dict]) -> list[dict]:
    """Сдвигает время звонков к «сейчас», чтобы демо не устаревало.

    Самый поздний звонок заканчивается 10 минут назад, старые звонки сохраняют
    свой возраст — поэтому задача из просроченного звонка остаётся просроченной.
    """
    ends = [datetime.fromisoformat(c["ended_at"]) for c in calls]
    latest = max(ends)
    delta = (datetime.now(latest.tzinfo) - timedelta(minutes=10)) - latest
    for call in calls:
        for key in ("started_at", "ended_at"):
            moment = datetime.fromisoformat(call[key]) + delta
            call[key] = moment.isoformat(timespec="seconds")
    return calls


def main() -> None:
    calls = make_fresh(json.loads(CALLS.read_text(encoding="utf-8")))
    line()
    print(f"Сервис контроля обещаний — демонстрация ({BASE})")
    line()

    print(f"\n1. Отправляем {len(calls)} звонков на вебхук POST /webhook/calls (как это делает sender)")
    report = api("POST", "/webhook/calls", calls)
    print(f"   принято: {report['accepted']}, дублей: {report['duplicates']}, "
          f"создано задач: {report['tasks_created']}")
    for item in report["calls"]:
        if item.get("status") == "accepted":
            print(f"   {item['id']}: обещаний {item.get('promises', 0)}, задач {item['tasks_created']}")

    print("\n2. Повторно отправляем те же звонки — проверяем защиту от дублей")
    again = api("POST", "/webhook/calls", calls)
    print(f"   принято: {again['accepted']}, дублей: {again['duplicates']}, "
          f"создано задач: {again['tasks_created']} (ожидаем 0)")

    all_tasks = api("GET", "/tasks?limit=100")["items"]
    show_tasks(all_tasks, "3. Все задачи, которые создал сервис")

    first = next((t for t in all_tasks if t["status"] == "created"), None)
    if first:
        print(f"\n4. Оператор берёт задачу #{first['id']} в работу и закрывает её")
        api("PATCH", f"/tasks/{first['id']}/status", {"status": "in_progress", "note": "Беру в работу"})
        closed = api("PATCH", f"/tasks/{first['id']}/status", {"status": "done", "note": "Перезвонил клиенту"})
        print(f"   итоговый статус: {closed['status_label']}")

    overdue = api("GET", "/tasks?status=overdue")["items"]
    show_tasks(overdue, "5. Просроченные задачи (выставлены автоматически по сроку)")

    by_operator = api("GET", "/tasks?operator_id=op-anna")["items"]
    print(f"\n6. Фильтр по оператору op-anna: {len(by_operator)} задач")

    print("\n7. Добавляем новый тип обещания через API")
    payload = {
        "name": "Переключить на отдел",
        "description": "Оператор обещает переключить клиента на профильный отдел.",
        "keywords": ["переключу", "соединю"],
        "action": "Соединить клиента с профильным отделом",
    }
    try:
        new_type = api("POST", "/promise-types", payload)
        print(f"   тип создан: {new_type['code']} — {new_type['name']}")
    except SystemExit as exc:
        # Повторный запуск демо: тип уже есть, 409 — это нормально.
        if "409" not in str(exc):
            raise
        existing = api("GET", "/promise-types")["items"]
        new_type = next(t for t in existing if t["name"] == payload["name"])
        print(f"   тип уже был создан ранее: {new_type['code']} — {new_type['name']}")

    extra = {
        "id": "demo-new-type",
        "operator_id": "op-anna",
        "phone": "+7 900 123-45-67",
        "started_at": "2026-10-29T15:00:00+05:00",
        "ended_at": "2026-10-29T15:02:00+05:00",
        "transcript": [
            {"role": "operator", "text": "Сейчас переключу вас на отдел продаж."},
        ],
    }
    api("POST", "/webhook/calls", [extra])
    fresh = api("GET", f"/tasks?type_code={new_type['code']}")["items"]
    show_tasks(fresh, "   Задача по новому типу найдена:")

    stats = api("GET", "/stats")
    line()
    print("8. Сводка GET /stats")
    print(f"   звонков: {stats['calls_total']}, задач: {stats['tasks_total']}, "
          f"в среднем обещаний на звонок: {stats['avg_promises_per_call']}")
    for status, count in stats["by_status"].items():
        print(f"   {status}: {count}")
    line()


if __name__ == "__main__":
    main()

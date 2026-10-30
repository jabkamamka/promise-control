"""Приводит имена сотрудников к нормальным и чистит историю задач.

Скрипт идемпотентный: можно запускать повторно, лишних изменений не будет.
Соответствие задаётся по email, поэтому переименование не зависит от текущего имени.
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import connect, init_db  # noqa: E402

NAMES = {
    "bn.4a@yandex.ru": "Александр Волков",
    "bn.4a+direct@yandex.ru": "Дмитрий Орлов",
    "bn.4anegor@gmail.com": "Егор Николаев",
    "danila.mer@bk.ru": "Данила Меркулов",
    "p23084829@gmail.com": "Павел Егоров",
    "kfkf@gmail.com": "Кирилл Фомин",
    "anna@example.com": "Анна Смирнова",
    "maria@example.com": "Мария Кузнецова",
    "ui-test@example.com": "Игорь Тестов",
    "petr@example.com": "Пётр Смирнов",
    "olga@example.com": "Ольга Лебедева",
    "confirm-test@example.com": "Сергей Волков",
    "rostislav.zimnev91@gmail.com": "Ростислав Зимнев",
}


def main() -> None:
    init_db()
    renamed = 0
    touched_tasks = 0
    touched_events = 0
    with connect() as conn:
        for email, new_name in NAMES.items():
            row = conn.execute(
                "SELECT id, full_name FROM employees WHERE lower(email) = ?", (email.lower(),)
            ).fetchone()
            if not row:
                continue
            old_name = row["full_name"]
            if old_name == new_name:
                continue

            conn.execute("UPDATE employees SET full_name = ? WHERE id = ?", (new_name, row["id"]))
            tasks = conn.execute(
                "UPDATE tasks SET assignee_name = ? WHERE assignee_id = ?", (new_name, row["id"])
            ).rowcount
            events = 0
            if old_name:
                events = conn.execute(
                    "UPDATE task_events SET comment = replace(comment, ?, ?) WHERE comment LIKE ?",
                    (old_name, new_name, f"%{old_name}%"),
                ).rowcount
            named = conn.execute(
                "UPDATE task_events SET comment = replace(comment, ?, ?) WHERE comment LIKE ?",
                (email, new_name, f"%{email}%"),
            ).rowcount
            events += named
            renamed += 1
            touched_tasks += tasks
            touched_events += events
        conn.commit()

        print(f"переименовано сотрудников: {renamed}")
        print(f"обновлено задач: {touched_tasks}")
        print(f"поправлено записей истории: {touched_events}")
        print("\nтекущий список:")
        for row in conn.execute(
            "SELECT email, full_name, role FROM employees ORDER BY id"
        ):
            print(f"  {row['email']:30} {row['full_name']:26} {row['role']}")


if __name__ == "__main__":
    main()

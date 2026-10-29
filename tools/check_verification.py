import json
import os
import sqlite3
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "verify.db")
sys.path.insert(0, ROOT)

from app.db import connect, init_db  # noqa: E402
from app.services.ingest import ingest_payload  # noqa: E402

calls = json.load(open(os.path.join(ROOT, "data", "sample_calls.json"), encoding="utf-8"))
init_db()
with connect() as conn:
    result = ingest_payload(conn, calls)
    rows = conn.execute(
        "SELECT verification_status, COUNT(*) c FROM tasks WHERE verification_status IS NOT NULL GROUP BY 1"
    ).fetchall()
    print("ingest:", result["tasks_created"], "задач, verified:", result["tasks_verified"])
    print("по статусам проверки:", {r["verification_status"]: r["c"] for r in rows})

    events = conn.execute("SELECT COUNT(*) c FROM task_events WHERE event='verified'").fetchone()["c"]
    print("событий verified:", events)
    if events:
        for e in conn.execute("SELECT task_id, comment FROM task_events WHERE event='verified' LIMIT 5"):
            print("  ", e["comment"][:160])

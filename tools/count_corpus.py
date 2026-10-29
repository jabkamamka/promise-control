import collections
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "count.db")
sys.path.insert(0, ROOT)

from app.db import connect, init_db  # noqa: E402
from app.services.ingest import ingest_payload  # noqa: E402

calls = json.load(open(os.path.join(ROOT, "data", "sample_calls.json"), encoding="utf-8"))
init_db()
with connect() as conn:
    result = ingest_payload(conn, calls)
    types = collections.Counter(
        r["promise_type"] for r in conn.execute("SELECT promise_type FROM tasks")
    )
    total = conn.execute("SELECT COUNT(*) AS c FROM tasks").fetchone()["c"]
print("tasks", total, "avg", round(total / len(calls), 2), "by type", dict(types))
print("created", result["tasks_created"])

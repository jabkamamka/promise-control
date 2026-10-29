import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "demo.db")
sys.path.insert(0, ROOT)

from app.db import connect, init_db  # noqa: E402
from app.services.ingest import ingest_payload  # noqa: E402

calls = json.load(open(os.path.join(ROOT, "data", "sample_verification.json"), encoding="utf-8"))
init_db()
with connect() as conn:
    result = ingest_payload(conn, calls)
    print("verified:", result["tasks_verified"])
    rows = conn.execute(
        "SELECT promise_type, status, verification_status, verification_quote FROM tasks ORDER BY created_at"
    ).fetchall()
    for row in rows:
        print(f"  {row['promise_type']:14s} {row['status']:10s} {str(row['verification_status']):10s} {(row['verification_quote'] or '')[:60]}")

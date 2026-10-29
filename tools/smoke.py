"""Быстрая проверка сквозного сценария без запуска сервера."""
import json
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "smoke.db")

from fastapi.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402

calls = json.load(open(os.path.join(ROOT, "data", "sample_calls.json"), encoding="utf-8"))

with TestClient(app) as client:
    print("health", client.get("/health").json())
    r = client.post("/webhook/calls", json=calls[:10])
    print("webhook", r.status_code, json.dumps(r.json(), ensure_ascii=False)[:400])
    r2 = client.post("/webhook/calls", json=calls[:10])
    print("repeat", r2.status_code, json.dumps(r2.json(), ensure_ascii=False)[:250])
    tasks = client.get("/api/v1/tasks?limit=3").json()
    print("tasks total", tasks["total"])
    print(json.dumps(tasks["items"][0], ensure_ascii=False, indent=1)[:900])
    print("stats", client.get("/api/v1/stats").json())

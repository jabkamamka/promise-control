"""Локальная заглушка API УралМикро — чтобы проверить настоящий sender.

Отдаёт звонки в точной схеме отправщика:
    {id, operator_id, client_phone, started_at, ended_at,
     transcript: [{speaker, text}]}

Запуск: python tools/mock_api.py 8099
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DEMO = Path(__file__).resolve().parent.parent / "promise-service" / "demo" / "calls_demo.json"


def build_calls() -> list[dict]:
    raw = json.loads(DEMO.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).replace(microsecond=0)
    operators = {"op-anna": 101, "op-boris": 102}
    calls = []
    for index, call in enumerate(raw):
        end = now - timedelta(minutes=12 + index)
        start = end - timedelta(minutes=6)
        calls.append({
            "id": "sender-" + call["id"],
            "operator_id": operators.get(call["operator_id"], 100),
            "client_phone": call["phone"],
            "started_at": start.isoformat(),
            "ended_at": end.isoformat(),
            "transcript": [
                {"speaker": "оператор" if s["role"] == "operator" else "клиент", "text": s["text"]}
                for s in call["transcript"]
            ],
        })
    return calls


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/api/v1/calls":
            self.send_error(404)
            return
        if not self.headers.get("X-Service-Token"):
            body = json.dumps({"message": "missing service token"}).encode()
            self.send_response(401)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return

        count = int(parse_qs(parsed.query).get("count", ["10"])[0])
        body = json.dumps(build_calls()[:count], ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:  # тише в консоли
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8099
    print(f"Mock API УралМикро на http://127.0.0.1:{port}/api/v1/calls", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()

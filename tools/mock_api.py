"""Локальная заглушка API УралМикро для проверки настоящего отправщика.

Отдаёт корпус `data/sample_calls.json` в схеме отправщика:
`GET /api/v1/calls?count=N` с заголовком `X-Service-Token`.

Запуск:
    python tools/mock_api.py 8099
    .\\sender_windows_amd64.exe -t test-token -w http://localhost:8080/webhook/calls -a http://127.0.0.1:8099
"""

from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

CORPUS = Path(__file__).resolve().parent.parent / "data" / "sample_calls.json"


def load_calls() -> list[dict]:
    return json.loads(CORPUS.read_text(encoding="utf-8"))


class Handler(BaseHTTPRequestHandler):
    def _json(self, payload: object, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - имя задано базовым классом
        parsed = urlparse(self.path)
        if parsed.path.rstrip("/") != "/api/v1/calls":
            self.send_error(404)
            return
        if not self.headers.get("X-Service-Token"):
            self._json({"message": "missing service token"}, status=401)
            return

        count = int(parse_qs(parsed.query).get("count", ["10"])[0])
        self._json(load_calls()[: max(1, min(count, 50))])

    def log_message(self, fmt: str, *args) -> None:
        if "--verbose" in sys.argv:
            super().log_message(fmt, *args)


if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 and sys.argv[1].isdigit() else 8099
    print(f"Mock API УралМикро: http://127.0.0.1:{port}/api/v1/calls", flush=True)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()

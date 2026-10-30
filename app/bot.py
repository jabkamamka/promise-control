"""Telegram-бот для входа: присылает код, сайт меняет его на сессию.

Запуск отдельным процессом (нужен токен от @BotFather):

    set TELEGRAM_BOT_TOKEN=123456:ABC...
    python -m app.bot

Бот работает через getUpdates (long polling), вебхук не требуется — удобно для
бесплатного хостинга. Если токена нет, процесс завершается с понятным сообщением.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

from .db import connect, init_db
from .services import users

API = "https://api.telegram.org/bot{token}/{method}"
LONG_POLL = 25


def call(token: str, method: str, **params) -> dict:
    url = API.format(token=token, method=method)
    data = urllib.parse.urlencode(params).encode("utf-8")
    request = urllib.request.Request(url, data=data, method="POST")
    with urllib.request.urlopen(request, timeout=LONG_POLL + 10) as response:
        return json.loads(response.read().decode("utf-8"))


def send(token: str, chat_id: int, text: str) -> None:
    call(token, "sendMessage", chat_id=chat_id, text=text)


def handle(token: str, update: dict) -> None:
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    chat_id = chat.get("id")
    text = (message.get("text") or "").strip()
    if not chat_id:
        return

    if text.startswith("/start"):
        with connect() as conn:
            users.ensure_schema(conn)
            code = users.issue_telegram_code(conn, int(chat_id))
            conn.commit()
        send(
            token,
            chat_id,
            "Код для входа: " + code + "\n"
            "Введите его на странице /account. Код действует 10 минут.",
        )
    elif text.startswith("/code"):
        with connect() as conn:
            users.ensure_schema(conn)
            code = users.issue_telegram_code(conn, int(chat_id))
            conn.commit()
        send(token, chat_id, "Новый код: " + code + " (10 минут)")
    else:
        send(token, chat_id, "Отправьте /start, чтобы получить код для входа.")


def main() -> None:
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        print("TELEGRAM_BOT_TOKEN не задан. Получите токен у @BotFather и повторите.", file=sys.stderr)
        raise SystemExit(1)

    init_db()
    offset = 0
    print("Бот запущен, жду сообщения…", flush=True)
    while True:
        try:
            payload = call(token, "getUpdates", timeout=LONG_POLL, offset=offset)
        except urllib.error.URLError as exc:
            print(f"Сеть недоступна: {exc}. Повтор через 5 секунд.", file=sys.stderr, flush=True)
            time.sleep(5)
            continue
        except Exception as exc:  # noqa: BLE001 - бот не должен падать от одного апдейта
            print(f"Ошибка getUpdates: {exc}", file=sys.stderr, flush=True)
            time.sleep(3)
            continue

        for update in payload.get("result", []):
            offset = max(offset, int(update.get("update_id", 0)) + 1)
            try:
                handle(token, update)
            except Exception as exc:  # noqa: BLE001
                print(f"Ошибка обработки апдейта: {exc}", file=sys.stderr, flush=True)


if __name__ == "__main__":
    main()

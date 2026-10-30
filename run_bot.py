"""Запуск Telegram-бота: python run_bot.py

Обёртка нужна потому, что в этом окружении `python -m app.bot` не видит пакет
`app` (cwd не попадает в sys.path). Здесь путь добавляется явно.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from app.bot import main  # noqa: E402

if __name__ == "__main__":
    main()

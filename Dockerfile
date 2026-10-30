# syntax=docker/dockerfile:1
# Образ сервиса контроля обещаний: FastAPI + uvicorn + SQLite.
# Сборка: docker build -t promise-service .
# Запуск:  docker run --rm -p 8080:8080 promise-service

FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Зависимости копируются отдельно: слой пересобирается только при изменении
# requirements.txt, а не на каждой правке кода.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Непривилегированный пользователь. UID/GID 1000 выбран намеренно: на Hugging Face
# Spaces контейнер запускается от UID 1000, и при другом UID не сможет писать в /app/data.
RUN groupadd --gid 1000 app \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/sh app

COPY --chown=app:app . .

# Каталог под файл SQLite. app/db.py создаёт его сам (Path.mkdir(parents=True)),
# но владельцем должен быть пользователь процесса, иначе запись запрещена.
RUN mkdir -p /app/data && chown -R app:app /app/data

ENV DATABASE_PATH=/app/data/promises.db

USER app

EXPOSE 8080

# PORT задаёт хостинг (Render присылает свой, обычно 10000); без PORT слушаем 8080.
# Подстановку ${PORT:-8080} делает sh, поэтому CMD запускается через sh -c.
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}"]

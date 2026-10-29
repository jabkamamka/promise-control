# API сервиса контроля обещаний

Базовый адрес: `http://localhost:8080`. Интерактивная документация: `/docs` (Swagger UI), `/redoc`.

Формат данных — JSON UTF-8. Время — ISO-8601 UTC (`2026-10-29T10:00:00Z`).

Ошибки:

```json
{ "detail": "Текст ошибки" }
```

| Код | Когда |
|---|---|
| 400 | Некорректный JSON или не найдено ни одного звонка в теле |
| 401 | Задан `WEBHOOK_TOKEN`, но заголовок не совпал |
| 404 | Объект не найден |
| 409 | Нарушено бизнес-правило: запрещённый переход статуса, дубль типа, удаление используемого типа |
| 422 | Ошибка валидации схемы (Pydantic) |

---

## POST /webhook/calls

Приём звонков от программы-отправителя. Принимает три формата тела:

- массив звонков (основной, по 10 штук),
- один звонок,
- `{"calls": [...]}`.

Заголовок `X-Webhook-Token` обязателен, только если в `.env` задан `WEBHOOK_TOKEN`.

**Тело (элемент массива):**

```json
{
  "id": "CDWCAMRH3NQD5HGBL4HJ36XJ2A",
  "operator_id": 3,
  "client_phone": "+79800908260",
  "started_at": "2026-10-29T10:35:37.772935923Z",
  "ended_at": "2026-10-29T10:39:37.772935923Z",
  "transcript": [
    { "speaker": "operator", "text": "Добрый день, служба поддержки «Сфера»." },
    { "speaker": "client", "text": "Действует ли акция на ноутбуки?" }
  ]
}
```

**Ответ 200:**

```json
{
  "received": 10,
  "processed": 10,
  "duplicates": 0,
  "failed": 0,
  "tasks_created": 34,
  "calls": [
    { "call_id": "CDWCAMRH3NQD5HGBL4HJ36XJ2A", "status": "processed", "tasks_created": 5, "promises_found": 5, "error": null }
  ]
}
```

`status` элемента: `processed` — обработан, `duplicate` — звонок с таким `id` уже был (задачи не создаются),
`error` — звонок битый, батч при этом не падает.

Один битый звонок не мешает обработать остальные: в ответе он попадёт со `status: "error"`.

Совместимость: тот же обработчик доступен по адресу `POST /calls` — если отправитель настроен на него.

---

## GET /api/v1/tasks

Список задач с фильтрами и пагинацией.

| Параметр | Тип | Описание |
|---|---|---|
| `status` | строка | `created`, `in_progress`, `done`, `overdue`; можно несколько через запятую |
| `type` | строка | Код типа обещания (`callback`, `documents`, …) |
| `operator_id` | int | Задачи конкретного оператора |
| `call_id` | строка | Задачи конкретного звонка |
| `due_before` | ISO | Срок не позже указанного времени |
| `due_after` | ISO | Срок не раньше указанного времени |
| `q` | строка | Поиск по названию, цитате, объекту и действиям (регистр и ё/е не важны) |
| `sort` | строка | `due_at` (по умолчанию), `-due_at`, `created_at`, `-updated_at`, `status`, `confidence` |
| `limit` | int | 1–200, по умолчанию 50 |
| `offset` | int | Смещение, по умолчанию 0 |

Фильтр `status=created` и `status=in_progress` **не включает просроченные** задачи — они отдаются
только по `status=overdue`. Это сделано, чтобы «Создана» не показывала давно просроченные задачи.

**Ответ:**

```json
{
  "items": [
    {
      "id": "tsk_8bf7d74e3a64",
      "call_id": "PLKWT67VBE5KSTFEGEH27K5KK5",
      "operator_id": 9,
      "client_phone": "+7*******50",
      "promise_type": "fix",
      "promise_type_title": "Исправить данные или оформить возврат",
      "title": "Исправить адрес",
      "object": "",
      "quote": "Исправлю адрес прямо сейчас. Подтверждение придёт вам смс.",
      "transcript_index": 28,
      "actions": ["Исправить адрес"],
      "secondary_types": [],
      "due_at": "2026-10-29T10:55:07Z",
      "due_hint": "прямо сейчас",
      "deadline_source": "immediate",
      "status": "created",
      "effective_status": "overdue",
      "is_overdue": true,
      "confidence": 0.9,
      "matched_by": "rule",
      "created_at": "2026-10-29T10:57:32Z",
      "updated_at": "2026-10-29T10:57:32Z",
      "closed_at": null,
      "call_started_at": "2026-10-29T10:35:51Z",
      "call_ended_at": "2026-10-29T10:40:07Z"
    }
  ],
  "total": 189,
  "limit": 50,
  "offset": 0
}
```

Поля, на которые смотреть в первую очередь:

- `effective_status` — реальное состояние с учётом срока (`overdue`, если срок прошёл и задача не закрыта);
- `deadline_source` — откуда взялся срок: `named_day`, `weekday`, `relative_hours`, `working_days`,
  `end_of_week`, `immediate`, `default_24h`, `clamped`;
- `due_hint` — фраза из разговора, по которой посчитан срок;
- `confidence` — уверенность детектора (0–1);
- `matched_by` — чем найдено: `rule` (правила), `custom-rule` (свой тип), `llm` (если включён LLM).

---

## GET /api/v1/tasks/{id}

Одна задача в том же формате. `404`, если не найдена.

## PATCH /api/v1/tasks/{id}

Смена статуса.

```json
{ "status": "in_progress", "comment": "Беру в работу" }
```

Разрешённые переходы:

| Из | В |
|---|---|
| `created` | `in_progress` |
| `in_progress` | `done`, `created` |
| `done` | `in_progress` |

Запрещённый переход → `409`:

```json
{ "detail": "Переход «Создана» → «Выполнена» запрещён. Доступно: in_progress" }
```

При переходе в `done` заполняется `closed_at`. Каждое изменение пишется в историю.

Совместимость: тот же обработчик доступен как `PATCH /api/v1/tasks/{id}/status`.

## GET /api/v1/tasks/{id}/events

История задачи:

```json
[
  { "id": 1, "task_id": "tsk_...", "event": "created", "from_status": null, "to_status": "created", "comment": "Задача создана по звонку", "at": "2026-10-29T10:57:32Z" },
  { "id": 2, "task_id": "tsk_...", "event": "status_changed", "from_status": "created", "to_status": "in_progress", "comment": "Беру в работу", "at": "2026-10-29T11:02:10Z" },
  { "id": 3, "task_id": "tsk_...", "event": "overdue", "from_status": null, "to_status": "overdue", "comment": "Срок истёк, задача не закрыта", "at": "2026-10-29T12:00:01Z" }
]
```

---

## GET /api/v1/promise-types

Справочник типов обещаний с количеством задач.

```json
[
  {
    "code": "documents",
    "title": "Отправить документы клиенту",
    "description": "Оператор обещает отправить или предоставить клиенту документы и файлы…",
    "keywords": ["отправ", "пришл", "вышл", "направ", "скин", "выгруж", "предоставл", "продикт", "документ", "почт", "письм"],
    "examples": ["Скину вам исправленную накладную на почту завтра до двенадцати"],
    "is_builtin": true,
    "priority": 90,
    "created_at": "2026-10-29T10:57:15Z",
    "updated_at": "2026-10-29T10:57:15Z",
    "tasks_count": 85
  }
]
```

## POST /api/v1/promise-types

Добавить свой тип. Код можно не указывать — сгенерируется из названия (транслит).

```json
{
  "title": "Согласовать скидку",
  "description": "Оператор обещает согласовать скидку с руководителем и вернуться с ответом",
  "keywords": ["скидк", "согласую"],
  "examples": ["Согласую скидку и перезвоню завтра"],
  "priority": 80
}
```

Ответ `201` — объект типа. `409`, если код уже занят.

Как тип начинает работать:

1. ключевые слова ищутся в реплике оператора как подстроки (стемы: `скидк` найдёт «скидку»);
2. дополнительно считается пересечение слов реплики с описанием и примерами;
3. если тип сработал и его приоритет выше встроенного — задача получит этот тип;
4. новые типы применяются к новым звонкам; для старых есть `POST /api/v1/calls/{id}/reanalyze`.

## DELETE /api/v1/promise-types/{code}

Удаляет пользовательский тип. `409`, если тип встроенный или по нему уже есть задачи.

---

## GET /api/v1/calls

Список принятых звонков: `operator_id`, `limit` (1–200), `offset`.

## GET /api/v1/calls/{id}

Звонок целиком: расшифровка, `promise_count`, список задач.

## POST /api/v1/calls/{id}/reanalyze

Повторный поиск обещаний по сохранённой расшифровке. Существующие задачи не дублируются
(`tasks_created` = только новые). Удобно после добавления своего типа.

```json
{ "call_id": "c-1", "promises_found": 5, "tasks_created": 0 }
```

---

## GET /api/v1/stats

```json
{
  "calls_total": 52,
  "tasks_total": 189,
  "by_status": { "created": 189, "in_progress": 0, "done": 0 },
  "by_type": { "documents": 85, "clarification": 76, "callback": 57 },
  "overdue": 17,
  "due_today": 61,
  "avg_promises_per_call": 3.63
}
```

## GET /health

```json
{ "status": "ok", "version": "1.0.0", "time": "2026-10-29T11:00:28Z", "database": "sqlite", "timezone": "Asia/Yekaterinburg", "types": 7, "tasks": 189 }
```

---

## Переменные окружения

| Переменная | По умолчанию | Назначение |
|---|---|---|
| `APP_TIMEZONE` | `Asia/Yekaterinburg` | Пояс, в котором произносятся сроки |
| `DATABASE_PATH` | `data/promises.db` | Файл SQLite |
| `DEFAULT_DUE_HOURS` | `24` | Срок, если дата не названа |
| `IMMEDIATE_MINUTES` | `15` | Срок для «прямо сейчас» |
| `WEBHOOK_TOKEN` | пусто | Если задан — требуется заголовок `X-Webhook-Token` |
| `LLM_ENABLED` | `0` | Включает необязательный LLM-адаптер |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | — | Настройки OpenAI-совместимого API |

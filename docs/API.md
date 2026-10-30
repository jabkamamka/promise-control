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
| 502 | API партнёра недоступен или отклонил токен (только `POST /api/v1/calls/fetch-api`) |
| 503 | Загрузка из API не настроена: нет `URALMICRO_SERVICE_TOKEN` |

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

## POST /api/v1/calls/fetch-api

Кнопка «Загрузить ещё из API» в панели: сервис сам идёт в API партнёра, берёт свежие
расшифровки и создаёт по ним задачи — от 10 до 20 за одно нажатие.

Требует входа сотрудника (cookie `sid`). Если в `.env` нет `URALMICRO_SERVICE_TOKEN`,
метод отвечает 503, а остальной сервис работает как обычно.

| Параметр | Тип | По умолчанию | Описание |
|---|---|---|---|
| `min_tasks` | int | 10 | Минимум новых задач (1–100) |
| `target_tasks` | int | 15 | Сколько задач хочется получить |
| `max_tasks` | int | 20 | Потолок: больше не создаст |

Нужно `1 ≤ min_tasks ≤ target_tasks ≤ max_tasks`, иначе 400.

Почему запросов к API несколько: параметр `count` партнёрский API игнорирует и отдаёт
небольшую порцию случайных звонков, а у одного и того же разговора может оказаться новый `id`.
Поэтому повторы отсеиваются по `id` **и** по тексту расшифровки. Если свежих записей не
хватает на `min_tasks`, сервис делает дополнительный заход и честно пишет об этом в `message`.

**Ответ 200:**

```json
{
  "fetched": 32,
  "skipped": 25,
  "selected": 7,
  "planned": 16,
  "received": 7,
  "processed": 7,
  "duplicates": 0,
  "failed": 0,
  "tasks_created": 16,
  "tasks_verified": 0,
  "min_tasks": 10,
  "max_tasks": 20,
  "message": "Из API: 7 звонков → 16 задач",
  "calls": [
    { "call_id": "CCOKFF6MG6BPPA37HN2SCFQEH5", "status": "processed", "tasks_created": 2, "promises_found": 2, "tasks_verified": 0, "error": null }
  ]
}
```

`fetched` — сколько звонков пришло из API, `skipped` — сколько отброшено как повторы,
`selected` — сколько попало в порцию, `planned` — сколько задач предсказал детектор.

| Код | Когда |
|---|---|
| 400 | Нарушен порядок `min_tasks ≤ target_tasks ≤ max_tasks` |
| 401 | Нет входа сотрудника |
| 502 | API недоступен, отклонил токен или вернул не JSON |
| 503 | Не задан `URALMICRO_SERVICE_TOKEN` |

Если в API не осталось незнакомых расшифровок: 200, `selected = 0`, `tasks_created = 0`,
`message` — «В API нет новых расшифровок…». Повторное нажатие кнопки дублей не создаёт.

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
| `verification` | строка | `confirmed`, `refuted`, `pending` — результат проверки исполнения по следующим звонкам |
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
      "verification_status": null,
      "verified_at": null,
      "verified_call_id": null,
      "verification_quote": null,
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
3. **свой тип важнее встроенных**: если он сработал, задача получит его код
   (`matched_by = custom-rule`), потому что тип добавили осознанно;
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

## GET /api/v1/analytics

Сводка для руководителя смены. Параметр `days` (1–90, по умолчанию 14) задаёт окно графика:
оно центрируется вокруг сегодняшнего дня, чтобы были видны и прошедшие, и предстоящие сроки.

```json
{
  "generated_at": "2026-10-29T13:18:41Z",
  "timezone": "Asia/Yekaterinburg",
  "period_days": 14,
  "totals": { "calls": 56, "tasks": 192, "closed": 123, "overdue": 56, "open": 69,
              "not_fulfilled": 1, "due_today": 6, "overdue_share": 29.2, "closed_share": 64.1 },
  "by_status": { "created": 12, "in_progress": 57, "done": 123 },
  "by_verification": { "pending": 190, "confirmed": 1, "refuted": 1 },
  "by_type": [{ "code": "clarification", "title": "Уточнить информацию и вернуться с ответом", "count": 66 }],
  "series": [{ "date": "2026-10-29", "weekday": 4, "created": 0, "closed": 2, "due": 6 }],
  "operators": [{ "operator_id": 13, "open": 15, "overdue": 13, "done": 20 }],
  "close_time": { "closed_count": 123, "avg_hours": 5.3, "median_hours": 4.7 }
}
```

`series[].due` — открытые задачи, у которых срок попадает на этот день; `closed` — закрытые в этот день.

## GET /api/v1/tasks-export

Выгрузка задач в CSV для Excel. Принимает те же фильтры, что `GET /api/v1/tasks`
(`status`, `type`, `operator_id`, `call_id`, `due_before`, `due_after`, `q`, `verification`, `sort`).

Ответ: `text/csv; charset=utf-8`, разделитель `;`, BOM в начале, заголовок
`Content-Disposition: attachment`. Колонки: ID, даты, статусы, тип, задача, объект, цитата оператора,
оператор, звонок, результат проверки, цитата клиента, уверенность, источник.

```powershell
Invoke-WebRequest "http://localhost:8080/api/v1/tasks-export?status=overdue" -OutFile overdue.csv
```

## GET /api/v1/stats

```json
{
  "calls_total": 52,
  "tasks_total": 189,
  "by_status": { "created": 189, "in_progress": 0, "done": 0 },
  "by_type": { "clarification": 66, "documents": 58, "callback": 37, "fix": 19 },
  "overdue": 17,
  "due_today": 61,
  "avg_promises_per_call": 3.63,
  "by_verification": { "confirmed": 0, "refuted": 0, "pending": 189 },
  "not_fulfilled": 0
}
```

## Вход и сотрудники

Сессия — HttpOnly-cookie `sid` на 30 дней. Все методы ниже, кроме `register` и `login`,
требуют входа; без сессии — `401`.

| Метод | Тело | Ответ |
|---|---|---|
| `POST /auth/register` | `{"full_name": "...", "email": "...", "password": "..."}` | `{"employee": {...}}`, ставит cookie |
| `POST /auth/email/start` | `{"email": "...", "full_name": "..."}` | `{"ok": true, "email_status": "file", "dev_link"?: "..."}` |
| `GET /auth/email/verify?token=...` | — | `303` в панель и cookie `sid` |
| `POST /auth/email/verify` | `{"email": "...", "code": "123456"}` | `{"employee": {...}}` |
| `POST /auth/login` | `{"email": "...", "password": "..."}` | `{"employee": {...}}`, ставит cookie |
| `POST /auth/logout` | — | `{"ok": true}` |
| `GET /auth/me` | — | `{"employee": {...}}` или `{"employee": null}` |
| `PATCH /auth/me` | `{"full_name": "...", "email": "..."}` | `{"employee": {...}}`; при смене почты — письмо-подтверждение |
| `POST /auth/password` | `{"current_password": "...", "new_password": "..."}` | `{"ok": true}`, прочие сессии закрываются |

```json
{
  "employee": {
    "id": 1,
    "email": "anna@company.ru",
    "full_name": "Анна Смирнова",
    "role": "operator",
    "email_confirmed": true,
    "created_at": "2026-10-29T09:12:00Z",
    "last_login_at": "2026-10-29T11:03:11Z"
  }
}
```

### PATCH /auth/me

Меняет имя и почту вошедшего сотрудника. Можно передать только одно поле.

| Поле | Описание |
|---|---|
| `full_name` | имя и фамилия, 2–120 символов, лишние пробелы схлопываются |
| `email` | новая рабочая почта; адрес должен быть свободен, иначе `409` |

Смена почты не рвёт сессию и не меняет роль, но адрес становится **неподтверждённым**:
на него уходит письмо со ссылкой, а `employee.email_confirmed` становится `false`.
Пока адрес не подтверждён, вход по паролю отвечает `403` — так опечатка в адресе не
превращается в новую точку входа. Вход по ссылке из письма подтверждает адрес сам.

```json
PATCH /auth/me
{ "full_name": "Анна Смирнова", "email": "a.smirnova@company.ru" }
```

```json
{
  "employee": {
    "id": 1,
    "email": "a.smirnova@company.ru",
    "full_name": "Анна Смирнова",
    "role": "operator",
    "email_confirmed": false
  },
  "email_changed": true,
  "needs_confirmation": true,
  "email_status": "sent",
  "message": "Почта изменена на a.smirnova@company.ru. Подтвердите адрес по ссылке из письма."
}
```

Ошибки: `400` — не передано ни одного поля, `401` — нет входа, `409` — адрес занят,
`422` — адрес не похож на почту или имя короче двух символов.

## Вход по ссылке на почту

```json
POST /auth/email/start
{ "email": "ivan@company.ru", "full_name": "Иван Петров" }
```

```json
{
  "ok": true,
  "email": "ivan@company.ru",
  "expires_in_minutes": 15,
  "email_status": "file",
  "created": true,
  "employee": { "id": 5, "email": "ivan@company.ru", "full_name": "Иван Петров", "role": "operator" },
  "dev_link": "http://127.0.0.1:8080/auth/email/verify?token=...",
  "dev_code": "778073"
}
```

Поля `dev_link` и `dev_code` возвращаются только при `EMAIL_TRANSPORT=file`
(демо без SMTP). Со SMTP их нет — ссылка уходит только в письме.

## GET /api/v1/notifications

Уведомления текущего сотрудника: напоминания о сроках в интерфейсе и копии писем.

```
?unread=1&limit=20
```

```json
{
  "items": [
    {
      "id": 12,
      "task_id": "tsk_3de972650967",
      "kind": "deadline_soon",
      "title": "Срок через 28 мин: «Перезвонить вам»",
      "body": "Срок: 30 октября, 12:46\nИз разговора: «Перезвоню вам через тридцать минут.»",
      "link": "/?task=tsk_3de972650967",
      "read_at": null,
      "email_status": "file",
      "created_at": "2026-10-30T07:17:10Z"
    }
  ],
  "unread": 1,
  "email": { "enabled": true, "transport": "file", "from": "Контроль обещаний <no-reply@promise-control.local>", "smtp_host": null }
}
```

`kind`: `deadline_soon` (за `REMINDER_MINUTES_BEFORE` до срока) или `overdue` (срок прошёл).
`email_status`: `sent` (ушло по SMTP), `file` (сохранено в `data/outbox`), `failed`, `disabled`.

## POST /api/v1/notifications/read

```json
{ "ids": [12] }
```

Без `ids` отмечает все. Ответ: `{"marked": 1, "unread": 0}`.

## POST /api/v1/notifications/scan

Проверяет сроки прямо сейчас и рассылает уведомления — тот же проход, что делает
планировщик раз в минуту. Нужен для демонстрации без ожидания.

```json
{ "checked_at": "2026-10-30T07:17:10Z", "created": 1, "already": 0, "emails": 1, "items": [ ... ] }
```

## POST /api/v1/notifications/test

Проверочное письмо себе — кнопка «Проверить почту» в панели уведомлений.
Требует входа. Возвращает, куда письмо ушло **на самом деле**.

```json
{
  "status": "sent",
  "detail": "SMTP smtp.yandex.ru:465 (ssl)",
  "to": "wekimu@vgmale.com",
  "sent_to": "wekimu@vgmale.com",
  "redirected": false,
  "email": { "transport": "smtp", "from": "...", "redirect_to": "bn.4a@yandex.ru" }
}
```

| Поле | Смысл |
|---|---|
| `to` | адрес сотрудника из профиля |
| `sent_to` | фактический получатель после демо-переадресации |
| `redirected` | `true`, если сработала `EMAIL_REDIRECT_TO` |
| `status` | `sent`, `file` (письмо в `data/outbox`), `failed`, `disabled` |

Панель показывает `sent_to`; при `redirected: true` пишет, что это демо-переадресация
письма для адреса `to`. Наличие `email.redirect_to` само по себе ничего не значит:
переадресация применяется только к доменам из `EMAIL_REDIRECT_DOMAINS`.

## GET /health

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
| `EMAIL_ENABLED` | `1` | Включить письма сотрудникам |
| `EMAIL_TRANSPORT` | `auto` | `auto` / `smtp` / `file` (файлы в `data/outbox`) |
| `EMAIL_FROM` | `Контроль обещаний <no-reply@...>` | Отправитель |
| `SMTP_HOST`, `SMTP_PORT`, `SMTP_USER`, `SMTP_PASSWORD` | пусто / `587` | SMTP-сервер |
| `SMTP_SECURITY` | `starttls` | `starttls` / `ssl` / `none` |
| `PUBLIC_BASE_URL` | `http://127.0.0.1:8080` | База ссылок в письмах |
| `REMINDER_MINUTES_BEFORE` | `60` | За сколько минут напоминать |
| `NOTIFY_ENABLED` | `1` | Фоновая рассылка уведомлений |
| `NOTIFY_INTERVAL_SECONDS` | `60` | Период проверки сроков |
| `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MODEL` | — | Настройки OpenAI-совместимого API |

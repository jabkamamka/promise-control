# Демонстрационный сценарий (7 минут)

Слайды для защиты: docs/Презентация_7_минут.pptx (9 слайдов, в заметках — что говорить).

Полный путь, который показывается жюри: **звонки пришли → обещания найдены → задачи созданы →
оператор получил список → изменил статус**. Все команды проверены на Windows PowerShell 5.1.

## 0. Подготовка (за 2 минуты до защиты)

```powershell
cd promise-control
.\.venv\Scripts\Activate.ps1
python scripts\seed_demo.py
python -m uvicorn app.main:app --host 127.0.0.1 --port 8080
```

`seed_demo.py` загружает 52 расшифровки (189 задач). Если нужен «чистый» прогон — удалите
`data\promises.db` перед запуском и отправьте звонки через вебхук (шаг 1).

Открыть в браузере: **http://localhost:8080/**

## 1. Звонки пришли (1 минута)

Показать, что сервис принимает ровно тот формат, который присылает программа-отправитель.

```powershell
$calls = Get-Content data\sample_calls.json -Raw -Encoding UTF8 | ConvertFrom-Json
$batch = $calls[0..9] | ConvertTo-Json -Depth 8
Invoke-RestMethod -Method Post -Uri http://localhost:8080/webhook/calls `
  -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($batch))
```

Ожидаемый ответ (числа могут отличаться на 1–2):

```
received      : 10
processed     : 10
duplicates    : 0
failed        : 0
tasks_created : 34
```

**Что сказать:** «Отправитель присылает по 10 звонков каждые 30 секунд. Сервис отвечает сводкой:
сколько принял, сколько задач создал, сколько было дублей».

Повторить ту же команду — показать идемпотентность:

```
received : 10   processed : 0   duplicates : 10   tasks_created : 0
```

## 2. Обещания найдены (1 минута)

```powershell
$tasks = Invoke-RestMethod http://localhost:8080/api/v1/tasks?limit=3
$tasks.items | Select-Object title, promise_type, due_at, due_hint, status | Format-Table -AutoSize
```

Ожидаемо: 3 задачи с разными типами, у каждой — цитата оператора и срок.

**Что сказать:** «Сервис смотрит реплики оператора и находит три обязательных типа: перезвонить,
выслать документы, уточнить и вернуться с ответом. Срок берётся из фразы: “завтра до обеда”,
“в четверг”, “через два часа”, “в течение трёх рабочих дней”. Если срок не назван — 24 часа».

Показать одну задачу целиком:

```powershell
$tasks.items[0] | ConvertTo-Json -Depth 5
```

Обратить внимание на `quote` (цитата), `due_hint` (фраза-источник срока) и `confidence`.

## 3. Задачи оператора (1 минута)

В браузере **http://localhost:8080/**:

1. Счётчики сверху: задач / просрочено / звонков / выполнено.
2. Фильтр «Просрочена» — сервис сам поставил просрочку по истёкшему сроку (17 задач на демо-данных).
3. Кнопка «звонок» в карточке — открывается расшифровка, реплики-обещания подсвечены
   пометкой «обещание», обещания клиента не подсвечиваются.
4. Фильтр по типу обещания и поиск по тексту.

## 4. Оператор изменил статус (1 минута)

Через интерфейс: «В работу» → «Выполнена». Через API то же самое:

```powershell
$id = (Invoke-RestMethod "http://localhost:8080/api/v1/tasks?status=created&limit=1").items[0].id

Invoke-RestMethod -Method Patch -Uri "http://localhost:8080/api/v1/tasks/$id" `
  -ContentType 'application/json' -Body '{"status":"in_progress","comment":"Беру в работу"}'

Invoke-RestMethod -Method Patch -Uri "http://localhost:8080/api/v1/tasks/$id" `
  -ContentType 'application/json' -Body '{"status":"done","comment":"Перезвонил клиенту"}'

Invoke-RestMethod "http://localhost:8080/api/v1/tasks/$id/events" | Format-Table event, from_status, to_status, comment
```

Показать запрещённый переход (защита от «перепрыгивания»):

```powershell
Invoke-RestMethod -Method Patch -Uri "http://localhost:8080/api/v1/tasks/$id" `
  -ContentType 'application/json' -Body '{"status":"created"}'   # 409
```

## 5. Новый тип обещания (1 минута)

```powershell
$body = @{
  title = "Согласовать скидку"
  description = "Оператор обещает согласовать скидку с руководителем и вернуться с ответом"
  keywords = @("скидк", "согласую")
  examples = @("Согласую скидку и перезвоню завтра")
} | ConvertTo-Json

Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/v1/promise-types `
  -ContentType 'application/json' -Body ([System.Text.Encoding]::UTF8.GetBytes($body))
```

**Что сказать:** «Новый тип добавляется через API, без перезапуска: описание, ключевые слова,
примеры. Дальше он участвует в поиске наравне со встроенными».

Для старых звонков — перепрогнать без дублей:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8080/api/v1/calls/<id_звонка>/reanalyze
```

## 6. Сводка (30 секунд)

```powershell
Invoke-RestMethod http://localhost:8080/api/v1/stats | ConvertTo-Json -Depth 4
```

**Что сказать:** «52 звонка → 189 задач, 3,6 обещания на звонок. Всё видно в `/api/v1/stats`».

## 7. Ограничения (30 секунд, обязательный пункт)

Сказать честно:

- поиск на правилах и лексике, а не на большой модели — незнакомые формулировки могут не найтись;
- проверка исполнения по следующим звонкам не сделана (кейс разрешает);
- SQLite и один процесс, для нагрузки нужен PostgreSQL;
- праздники при расчёте рабочих дней не учитываются;
- LLM-режим выключен по умолчанию.

## Если что-то пошло не так

| Симптом | Что сделать |
|---|---|
| Порт занят | `python -m uvicorn app.main:app --port 8090` |
| `Activate.ps1` запрещён | `Set-ExecutionPolicy -Scope Process -ExecutionPolicy Bypass` |
| Пустая база после перезапуска | `python scripts\seed_demo.py` |
| Кракозябры в PowerShell | `chcp 65001` перед выводом |

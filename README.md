# Team Bot

Team Bot — модульный командный чат-бот. Он накапливает идеи и задачи команды,
изолирует данные рабочих групп и на этапе M1 принимает slash-команды в Telegram.
Источник архитектурных решений: [ARCHITECTURE.md](ARCHITECTURE.md).

## Реализовано

### M0. Каркас

- Python 3.12, src-layout, типизированная конфигурация из окружения;
- FastAPI с `GET /healthz` и `GET /readyz`;
- SQLAlchemy 2 async и Alembic для SQLite и PostgreSQL;
- UUID создаются приложением, время хранится как aware UTC;
- репозитории командных данных обязательно фильтруют по `TeamContext`;
- APScheduler in-memory и ежедневный backup SQLite.

### M1. Ядро и Telegram

- реестр slash-команд, оркестратор, RBAC и русские тексты ответов;
- рабочие группы, роли, привязка аккаунта и чата одноразовыми кодами;
- задачи с устойчивым номером внутри команды, идеи и поиск по `*_norm`;
- идемпотентность входящих событий по `(platform, chat_id, message_id)`;
- адаптер Telegram на long polling (aiogram 3), меню команд и экспорт файлами;
- первая команда и owner создаются из `TELEGRAM_BOOTSTRAP_OWNER_ID`.

## Команды бота

Реализованы только команды ниже; имена и смысл `/start`, `/add`, `/list`,
`/list_csv`, `/list_html`, `/summary` сохранены. Неверные аргументы известной
команды возвращают её синтаксис и пример.

| Команда | Описание | Мин. роль | Синтаксис | Пример |
|---|---|---|---|---|
| `/start` | Начать | любая | `/start [код]` | `/start Ab3xY9kLm2` |
| `/add` | Добавить задачу | member | `/add <текст>` | `/add Подготовить отчёт к пятнице` |
| `/list` | Список задач | viewer | `/list [open\|done\|all]` | `/list open` |
| `/list_csv` | Список в csv | viewer | `/list_csv` | `/list_csv` |
| `/list_html` | Список в html | viewer | `/list_html` | `/list_html` |
| `/summary` | Итоги задач | viewer | `/summary` | `/summary` |
| `/help` | Справка | любая | `/help` | `/help` |
| `/my` | Мои задачи | member | `/my` | `/my` |
| `/done` | Завершить задачу | member | `/done <номер>` | `/done 1` |
| `/edit` | Изменить задачу | member | `/edit <номер> <новый текст>` | `/edit 1 Подготовить отчёт к понедельнику` |
| `/idea` | Добавить идею | member | `/idea <текст>` | `/idea Сделать дашборд для отчётов #продукт #аналитика` |
| `/ideas` | Список идей | viewer | `/ideas [текст]` | `/ideas #продукт` |
| `/link` | Привязать аккаунт | любая | `/link [код]` | `/link Ab3xY9kLm2` |
| `/bind` | Привязать чат к команде | admin | `/bind [код]` | `/bind Ab3xY9kLm2` |
| `/team` | Моя команда | member | `/team` | `/team` |
| `/invite` | Пригласить в команду | admin | `/invite [роль]` | `/invite member` |
| `/role` | Назначить роль | admin | `/role <uuid> <роль>` | `/role 11111111-1111-1111-1111-111111111111 viewer` |
| `/kick` | Исключить из команды | admin | `/kick <uuid>` | `/kick 11111111-1111-1111-1111-111111111111` |
| `/unbind` | Отвязать чат от команды | admin | `/unbind` | `/unbind` |
| `/leave` | Выйти из команды | member | `/leave` | `/leave` |
| `/chats` | Чаты команды | owner | `/chats` | `/chats` |

## Роли и права

Один механизм ролей для бота: `owner`, `admin`, `member`, `viewer`. Права
проверяет ядро, а не адаптер канала.

- `viewer` — просмотр задач и идей;
- `member` — создание задач и идей, выход из команды (`/leave`);
- `admin` — приглашения, роли (кроме owner и admin), `/bind`, `/unbind`, `/kick` (member и viewer);
- `owner` — всё перечисленное, включая приглашение admin и `/chats`; выйти и быть исключённым нельзя.

Первый владелец задаётся
`TELEGRAM_BOOTSTRAP_OWNER_ID`; случайный пользователь owner не становится.

## Как это работает

Сообщение из Telegram приводится к `InboundEvent`. Оркестратор атомарно
регистрирует ключ события, разрешает пользователя и команду, проверяет реестр
команд и вызывает сервис. Ответ уходит как `OutboundMessage` с учётом лимита
длины. Свободный текст без `/команды` на M1 игнорируется.

Первый чат владельца привязывается при `/start`, если у него ровно одна
команда с ролью owner. Остальные чаты привязываются кодом `/bind`.
Владелец смотрит привязки командой `/chats`: Telegram не отдаёт полный
список групп бота, поэтому в ответе только сохранённые чаты и проверка,
состоит ли бот в них ещё.

## Конфигурация

Скопируйте `.env.example` в `.env`. Секреты не должны попадать в репозиторий.

- `APP_ENV` — `development`, `test` или `production`;
- `APP_HOST`, `APP_PORT` — адрес и порт HTTP-сервера;
- `LOG_LEVEL` — минимальный уровень структурных логов;
- `DATABASE_URL` — единственный выбор БД;
- `SQLITE_BUSY_TIMEOUT_MS`, `SQLITE_BACKUP_DIR`, `SQLITE_BACKUP_CRON`;
- `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_PORT`;
- `RETENTION_AUDIO_DAYS` — будущий срок хранения аудио;
- `INITIAL_TEAM_NAME` — имя первой рабочей группы;
- `ACCESS_CODE_TTL_MINUTES` — срок одноразовых кодов;
- `TELEGRAM_BOT_TOKEN` — токен BotFather; пустое значение оставляет HTTP-каркас
  без канала;
- `TELEGRAM_BOOTSTRAP_OWNER_ID` — Telegram id владельца первой команды;
- `TELEGRAM_WEBHOOK_SECRET` — не используется при long polling;
- `VK_GROUP_TOKEN` — placeholder этапа M6, код канала не читает эту переменную;
- `PROXYAPI_BASE_URL`, `PROXYAPI_KEY`, `ZAI_API_KEY`, `GIGACHAT_API_KEY`,
  `LOCAL_LLM_URL`, `HF_TOKEN` — зарезервированы для M2/M3.

Токены канала читаются адаптером Telegram, а не ядром. Пустые необязательные
значения становятся `None`.

## Локальный запуск

```bash
uv venv --python 3.12
uv sync
```

PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
```

Заполните `.env`: `TELEGRAM_BOT_TOKEN` и `TELEGRAM_BOOTSTRAP_OWNER_ID`.
Числовой id можно узнать у `@userinfobot`. Затем:

```bash
uv run python main.py
```

Откройте `http://127.0.0.1:8000/healthz` и `http://127.0.0.1:8000/readyz`.
Напишите боту `/start` от аккаунта владельца.

Без токена приложение всё равно поднимает healthcheck и пишет в лог, что канал
отключён. Если команда `uv` не в `PATH`, используйте `python -m uv`.

Docker:

```bash
docker compose up --build
```

PostgreSQL для проверки переносимости:

```bash
docker compose --profile postgres up -d postgres
```

## Миграции

```bash
uv run alembic upgrade head
uv run alembic check
```

## Тесты и качество

```bash
uv run ruff check .
uv run mypy
uv run pytest
```

## Структура

- `main.py` — точка запуска;
- `src/teambot/core` — события, порты, реестр команд, оркестратор, сервисы;
- `src/teambot/adapters/channels` — Telegram;
- `src/teambot/adapters/storage` — SQLAlchemy, репозитории, backup;
- `src/teambot/adapters/scheduler` — APScheduler;
- `src/teambot/infra` — конфигурация ядра, БД, миграции, логирование;
- `src/teambot/web` — служебный FastAPI;
- `alembic` — версии схемы;
- `tests` — юнит-тесты сервисов и контрактные тесты адаптеров.

## Ограничения

- нет VK, MAX, LLM, напоминаний, свободного разбора текста, встреч и RLS;
- `/add` не разбирает исполнителя и срок — это этап M2;
- номера задач постоянны внутри команды и не совпадают с порядком фильтра
  `/list open`;
- одноразовые коды хранятся только как хеш и живут `ACCESS_CODE_TTL_MINUTES`;
- прототипа для переноса данных не было: совместимы имена и смысл команд, а не
  байтовый формат старого SQLite.

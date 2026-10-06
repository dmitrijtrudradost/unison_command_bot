"""Точка композиции приложения и адаптеров.

Только этот модуль связывает инфраструктуру с ядром (ARCHITECTURE.md, раздел 5).
На этапе M1 здесь собираются хранилище, оркестратор, планировщик и адаптер Telegram.
"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

import structlog
from fastapi import FastAPI
from sqlalchemy.engine import make_url

from teambot.adapters.channels.telegram import (
    TelegramAdapter,
    TelegramSettings,
    load_telegram_settings,
)
from teambot.adapters.scheduler.apscheduler import APSchedulerAdapter
from teambot.adapters.storage.backup import SqliteBackup
from teambot.adapters.storage.stores import (
    NormalizedIdeaIndex,
    SqlAccessCodeStore,
    SqlEventDeduplicator,
    SqlIdeaStore,
    SqlIdentityStore,
    SqlTaskStore,
    SqlTeamStore,
)
from teambot.core.commands import COMMANDS
from teambot.core.events import JsonValue
from teambot.core.models import ExternalIdentity
from teambot.core.orchestrator import Orchestrator
from teambot.core.services.ideas import IdeaService
from teambot.core.services.identity import IdentityService
from teambot.core.services.tasks import TaskService
from teambot.infra.config import Settings, get_settings
from teambot.infra.db import Database
from teambot.infra.logging import configure_logging
from teambot.web.app import ReadinessProbe, create_app

logger = structlog.get_logger(__name__)


@dataclass(frozen=True, slots=True)
class Application:
    """Хранит собранные компоненты процесса M1."""

    web: FastAPI
    settings: Settings
    database: Database
    scheduler: APSchedulerAdapter
    backup: SqliteBackup | None
    telegram: TelegramAdapter | None
    background_tasks: list[asyncio.Task[None]] = field(default_factory=list)


def build_application(
    settings: Settings | None = None,
    readiness_probe: ReadinessProbe | None = None,
    telegram_settings: TelegramSettings | None = None,
) -> Application:
    """Собирает приложение без запуска сервера.

    Аргументы:
        settings: Готовые настройки; при отсутствии загружаются из окружения.
        readiness_probe: Проверка внешних зависимостей.
        telegram_settings: Настройки канала; ``None`` означает чтение из env.

    Возвращает:
        Контейнер собранных компонентов приложения.
    """
    resolved_settings = settings or get_settings()
    configure_logging(resolved_settings.log_level)
    database = Database.create(
        resolved_settings.database_url,
        resolved_settings.sqlite_busy_timeout_ms,
    )
    backup: SqliteBackup | None = None
    if make_url(resolved_settings.database_url).get_backend_name() == "sqlite":
        backup = SqliteBackup(resolved_settings.database_url)

    identity_store = SqlIdentityStore(database.sessions)
    team_store = SqlTeamStore(database.sessions)
    access_codes = SqlAccessCodeStore(database.sessions)
    task_store = SqlTaskStore(database.sessions)
    idea_store = SqlIdeaStore(database.sessions)
    identity_service = IdentityService(
        identity_store,
        team_store,
        access_codes,
        code_lifetime=timedelta(minutes=resolved_settings.access_code_ttl_minutes),
    )
    resolved_telegram = (
        telegram_settings if telegram_settings is not None else load_telegram_settings()
    )
    telegram: TelegramAdapter | None = None
    if resolved_telegram.telegram_bot_token is not None:
        telegram = TelegramAdapter(resolved_telegram)
    else:
        logger.info("telegram_channel_disabled")
    orchestrator = Orchestrator(
        SqlEventDeduplicator(database.sessions),
        identity_service,
        TaskService(task_store),
        IdeaService(idea_store, NormalizedIdeaIndex(idea_store)),
        presence=telegram,
    )

    async def handle_scheduled(name: str, _payload: dict[str, JsonValue]) -> None:
        """Исполняет только инфраструктурные задания этапа M0."""
        if name == "sqlite_backup" and backup is not None:
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            destination = Path(resolved_settings.sqlite_backup_dir) / f"teambot-{timestamp}.db"
            await backup.create(destination)

    scheduler = APSchedulerAdapter(handler=handle_scheduled)
    background_tasks: list[asyncio.Task[None]] = []

    async def startup() -> None:
        """Запускает планировщик, bootstrap владельца и polling Telegram."""
        await scheduler.start()
        if backup is not None:
            await scheduler.schedule_cron(
                "sqlite_backup",
                resolved_settings.sqlite_backup_cron,
                {},
            )
        if telegram is None:
            return
        owner_id = resolved_telegram.telegram_bootstrap_owner_id
        if owner_id:
            await identity_service.bootstrap_owner(
                ExternalIdentity(telegram.platform, owner_id),
                resolved_settings.initial_team_name,
            )
        await telegram.publish_commands(list(COMMANDS))
        background_tasks.append(
            asyncio.create_task(telegram.start(orchestrator.handle), name="telegram-polling")
        )

    async def shutdown() -> None:
        """Останавливает канал, планировщик и пул БД."""
        if telegram is not None:
            await telegram.stop()
        for task in background_tasks:
            try:
                await task
            except asyncio.CancelledError:
                pass
        background_tasks.clear()
        await scheduler.shutdown()
        await database.close()

    probe = readiness_probe or database.ready
    web = create_app(probe, startup=startup, shutdown=shutdown)
    return Application(
        web=web,
        settings=resolved_settings,
        database=database,
        scheduler=scheduler,
        backup=backup,
        telegram=telegram,
        background_tasks=background_tasks,
    )

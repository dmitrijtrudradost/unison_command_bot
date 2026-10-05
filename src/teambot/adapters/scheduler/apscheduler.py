"""In-memory адаптер APScheduler с восстановлением из основной БД.

APScheduler служит только будильником (DB-12): при старте активные записи
перечитываются через ``JobRecoverySource``, а идемпотентность действия
обеспечивает ``JobExecutor`` условным изменением источника истины.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from uuid import uuid4

from apscheduler.jobstores.memory import MemoryJobStore
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

from teambot.core.events import JsonValue
from teambot.core.models import RecoverableJob, TeamContext
from teambot.core.ports import JobExecutor, JobRecoverySource

type JobHandler = Callable[[str, dict[str, JsonValue]], Awaitable[None]]


async def _noop_handler(_name: str, _payload: dict[str, JsonValue]) -> None:
    """Обеспечивает безопасное выполнение тестовых заданий M0."""


class APSchedulerAdapter:
    """Реализует Scheduler поверх непостоянного MemoryJobStore."""

    def __init__(
        self,
        recovery_source: JobRecoverySource | None = None,
        executor: JobExecutor | None = None,
        handler: JobHandler = _noop_handler,
    ) -> None:
        """Создаёт остановленный планировщик и проверяет пары зависимостей."""
        if (recovery_source is None) != (executor is None):
            raise ValueError("Источник восстановления и исполнитель задаются вместе")
        self._recovery_source = recovery_source
        self._executor = executor
        self._handler = handler
        self._scheduler = AsyncIOScheduler(
            jobstores={"default": MemoryJobStore()},
            timezone=UTC,
        )

    @property
    def running(self) -> bool:
        """Сообщает, запущен ли внутренний планировщик."""
        return bool(self._scheduler.running)

    async def start(self) -> None:
        """Запускает планировщик и восстанавливает активные задания."""
        self._scheduler.start()
        if self._recovery_source is None:
            return
        for ctx in await self._recovery_source.list_team_contexts():
            for job in await self._recovery_source.list_active(ctx):
                self._schedule_recovered(ctx, job)

    async def shutdown(self) -> None:
        """Останавливает планировщик без ожидания исполняющихся задач."""
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    async def schedule_once(
        self,
        name: str,
        run_at: datetime,
        payload: dict[str, JsonValue],
    ) -> str:
        """Ставит одноразовый будильник в UTC."""
        run_at_utc = _ensure_aware_utc(run_at)
        job_id = str(uuid4())
        self._scheduler.add_job(
            self._handler,
            trigger=DateTrigger(run_date=run_at_utc),
            id=job_id,
            args=[name, payload],
        )
        return job_id

    async def schedule_cron(
        self,
        name: str,
        cron: str,
        payload: dict[str, JsonValue],
    ) -> str:
        """Ставит будильник по стандартному пятичастному crontab."""
        job_id = str(uuid4())
        self._scheduler.add_job(
            self._handler,
            trigger=CronTrigger.from_crontab(cron, timezone=UTC),
            id=job_id,
            args=[name, payload],
        )
        return job_id

    async def cancel(self, job_id: str) -> None:
        """Удаляет задание; повторная отмена безопасна."""
        job = self._scheduler.get_job(job_id)
        if job is not None:
            self._scheduler.remove_job(job_id)

    def _schedule_recovered(self, ctx: TeamContext, job: RecoverableJob) -> None:
        run_at = _ensure_aware_utc(job.run_at)
        # Просроченный будильник запускается немедленно: источник истины решит,
        # нужно ли ещё выполнять действие.
        if run_at < datetime.now(UTC):
            run_at = datetime.now(UTC)
        self._scheduler.add_job(
            self._execute_recovered,
            trigger=DateTrigger(run_date=run_at),
            id=f"recovered:{job.id}",
            args=[ctx, job],
            replace_existing=True,
            misfire_grace_time=None,
        )

    async def _execute_recovered(self, ctx: TeamContext, job: RecoverableJob) -> None:
        if self._executor is None:  # pragma: no cover — проверено конструктором.
            raise RuntimeError("Исполнитель восстановленных заданий не настроен")
        await self._executor.execute(ctx, job)


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Время задания должно быть aware datetime")
    return value.astimezone(UTC)

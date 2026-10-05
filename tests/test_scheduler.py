"""Контракт восстановления и идемпотентного выполнения DB-12."""

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from teambot.adapters.scheduler.apscheduler import APSchedulerAdapter
from teambot.core.models import RecoverableJob, Role, TeamContext


class FakeRecoverySource:
    def __init__(self, ctx: TeamContext, job: RecoverableJob) -> None:
        self.ctx = ctx
        self.job = job

    async def list_team_contexts(self) -> list[TeamContext]:
        return [self.ctx]

    async def list_active(self, ctx: TeamContext) -> list[RecoverableJob]:
        assert ctx == self.ctx
        return [self.job]


class IdempotentFakeExecutor:
    def __init__(self) -> None:
        self.processed: set[UUID] = set()
        self.actions = 0
        self.calls = 0

    async def execute(self, ctx: TeamContext, job: RecoverableJob) -> bool:
        assert str(ctx.team_id) == job.payload["team_id"]
        self.calls += 1
        if job.id in self.processed:
            return False
        self.processed.add(job.id)
        self.actions += 1
        return True


async def test_restore_twice_does_not_duplicate_action() -> None:
    ctx = TeamContext(uuid4(), uuid4(), Role.OWNER)
    job = RecoverableJob(
        id=uuid4(),
        name="test",
        run_at=datetime.now(UTC) - timedelta(seconds=1),
        payload={"team_id": str(ctx.team_id)},
    )
    source = FakeRecoverySource(ctx, job)
    executor = IdempotentFakeExecutor()
    first = APSchedulerAdapter(source, executor)
    second = APSchedulerAdapter(source, executor)

    await first.start()
    await second.start()
    for _ in range(20):
        if executor.calls == 2:
            break
        await asyncio.sleep(0.01)
    await first.shutdown()
    await second.shutdown()

    assert executor.calls == 2
    assert executor.actions == 1


async def test_schedule_and_cancel_one_time_job() -> None:
    scheduler = APSchedulerAdapter()
    await scheduler.start()
    job_id = await scheduler.schedule_once(
        "test",
        datetime.now(UTC) + timedelta(hours=1),
        {},
    )
    await scheduler.cancel(job_id)
    await scheduler.cancel(job_id)
    await scheduler.shutdown()

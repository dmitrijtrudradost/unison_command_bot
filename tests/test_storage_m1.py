"""Контрактные тесты хранилища M1: нумерация, дедупликация и одноразовые коды."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import uuid4

from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from teambot.adapters.storage.dialect import create_engine
from teambot.adapters.storage.hashing import hash_access_code
from teambot.adapters.storage.models import AccessCodeRecord, Base
from teambot.adapters.storage.stores import (
    SqlAccessCodeStore,
    SqlEventDeduplicator,
    SqlIdeaStore,
    SqlIdentityStore,
    SqlTaskStore,
    SqlTeamStore,
)
from teambot.core.models import (
    AccessCodePurpose,
    EventKey,
    ExternalIdentity,
    IdeaFilter,
    NewAccessCode,
    NewIdea,
    Role,
    TaskStatus,
)
from teambot.core.services.tasks import TaskService


async def _engine(tmp_path: Path) -> AsyncEngine:
    configured_url = os.environ.get("DATABASE_URL", "")
    database_url = (
        configured_url
        if configured_url and make_url(configured_url).get_backend_name() == "postgresql"
        else f"sqlite+aiosqlite:///{tmp_path / 'm1-store.db'}"
    )
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    return engine


async def test_task_numbers_are_stable_and_isolated(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identities = SqlIdentityStore(sessions)
    teams = SqlTeamStore(sessions)
    tasks = TaskService(SqlTaskStore(sessions))
    owner_a = await identities.create_user(ExternalIdentity("src", "a"), "A")
    owner_b = await identities.create_user(ExternalIdentity("src", "b"), "B")
    ctx_a = await teams.ensure_owned_team(owner_a, "A")
    ctx_b = await teams.ensure_owned_team(owner_b, "B")

    first = await tasks.add(ctx_a, "Первая")
    second = await tasks.add(ctx_a, "Вторая")
    other = await tasks.add(ctx_b, "Чужая")
    await tasks.complete(ctx_a, first.number)

    remaining = await tasks.list(ctx_a, status=None)
    assert [task.number for task in remaining] == [1, 2]
    assert remaining[0].status is TaskStatus.DONE
    assert second.number == 2
    assert other.number == 1
    assert await SqlTaskStore(sessions).get_by_number(ctx_a, 2) is not None
    await engine.dispose()


async def test_event_claim_is_atomic(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    deduplicator = SqlEventDeduplicator(sessions)
    key = EventKey("src", "chat", "42")

    assert await deduplicator.claim(key) is True
    assert await deduplicator.claim(key) is False
    await engine.dispose()


async def test_access_code_is_hashed_and_single_use(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identities = SqlIdentityStore(sessions)
    teams = SqlTeamStore(sessions)
    codes = SqlAccessCodeStore(sessions)
    owner = await identities.create_user(ExternalIdentity("src", "owner"), "Owner")
    ctx = await teams.ensure_owned_team(owner, "Team")
    created = await codes.create(
        ctx,
        NewAccessCode(
            id=uuid4(),
            code="plain-code",
            purpose=AccessCodePurpose.INVITE,
            expires_at=datetime.now(UTC) + timedelta(hours=1),
            role=Role.MEMBER,
        ),
    )

    async with sessions() as session:
        row = await session.get(AccessCodeRecord, created.id)
        assert row is not None
        assert row.code_hash == hash_access_code("plain-code")
        assert row.code_hash != "plain-code"

    found = await codes.find("plain-code", AccessCodePurpose.INVITE)
    assert found is not None
    assert await codes.consume(ctx, found.id) is True
    assert await codes.consume(ctx, found.id) is False
    await engine.dispose()


async def test_idea_store_filters_by_normalized_text(tmp_path: Path) -> None:
    engine = await _engine(tmp_path)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    identities = SqlIdentityStore(sessions)
    teams = SqlTeamStore(sessions)
    ideas = SqlIdeaStore(sessions)
    owner = await identities.create_user(ExternalIdentity("src", "owner"), "Owner")
    ctx = await teams.ensure_owned_team(owner, "Team")
    await ideas.create(
        ctx,
        NewIdea(text="Новый бот", text_norm="новый бот", author_id=owner.id, tags=("продукт",)),
    )
    found = await ideas.list(ctx, IdeaFilter(query_norm="новый"))
    assert len(found) == 1
    assert found[0].tags == ("продукт",)
    await engine.dispose()

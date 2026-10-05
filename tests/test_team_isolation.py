"""Автоматическая проверка изоляции всех командных таблиц DB-13."""

import os
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID, uuid4

from pydantic import BaseModel
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from teambot.adapters.storage.dialect import create_engine
from teambot.adapters.storage.hashing import hash_access_code
from teambot.adapters.storage.models import (
    AccessCodeRecord,
    Base,
    Chat,
    IdeaRecord,
    IdeaTag,
    Membership,
    Message,
    TaskRecord,
    Team,
    TeamSequence,
    User,
)
from teambot.adapters.storage.repository import TeamScopedRepository
from teambot.adapters.storage.schemas import (
    AccessCodeValues,
    ChatValues,
    IdeaTagValues,
    IdeaValues,
    MembershipValues,
    MessageValues,
    TaskValues,
    TeamSequenceValues,
)
from teambot.core.models import AccessCodePurpose, IdeaStatus, Role, TaskStatus, TeamContext


async def test_every_team_model_is_isolated_by_context(tmp_path: Path) -> None:
    configured_url = os.environ.get("DATABASE_URL", "")
    database_url = (
        configured_url
        if configured_url and make_url(configured_url).get_backend_name() == "postgresql"
        else f"sqlite+aiosqlite:///{tmp_path / 'isolation.db'}"
    )
    engine = create_engine(database_url)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    team_a, team_b = Team(name="A"), Team(name="B")
    user_a, user_b = User(display_name="A"), User(display_name="B")
    async with sessions() as session, session.begin():
        session.add_all([team_a, team_b, user_a, user_b])

    ctx_a = TeamContext(team_a.id, user_a.id, Role.OWNER)
    ctx_b = TeamContext(team_b.id, user_b.id, Role.OWNER)
    now = datetime.now(UTC)
    await _seed_team(sessions, ctx_a, user_a.id, "a", now)
    await _seed_team(sessions, ctx_b, user_b.id, "b", now)

    membership_repo = TeamScopedRepository(sessions, Membership, MembershipValues)
    chat_repo = TeamScopedRepository(sessions, Chat, ChatValues)
    message_repo = TeamScopedRepository(sessions, Message, MessageValues)
    sequence_repo = TeamScopedRepository(sessions, TeamSequence, TeamSequenceValues)
    task_repo = TeamScopedRepository(sessions, TaskRecord, TaskValues)
    idea_repo = TeamScopedRepository(sessions, IdeaRecord, IdeaValues)
    tag_repo = TeamScopedRepository(sessions, IdeaTag, IdeaTagValues)
    code_repo = TeamScopedRepository(sessions, AccessCodeRecord, AccessCodeValues)
    model_by_table = {
        Membership.__table__: membership_repo,
        Chat.__table__: chat_repo,
        Message.__table__: message_repo,
        TeamSequence.__table__: sequence_repo,
        TaskRecord.__table__: task_repo,
        IdeaRecord.__table__: idea_repo,
        IdeaTag.__table__: tag_repo,
        AccessCodeRecord.__table__: code_repo,
    }
    team_tables = {table for table in Base.metadata.tables.values() if "team_id" in table.c}
    assert set(model_by_table) == team_tables

    for table in team_tables:
        repository = cast(
            TeamScopedRepository[DeclarativeBase, BaseModel],
            model_by_table[table],
        )
        rows_a = await repository.list_all(ctx_a)
        rows_b = await repository.list_all(ctx_b)
        assert rows_a and all(vars(row)["team_id"] == team_a.id for row in rows_a), table.name
        assert rows_b and all(vars(row)["team_id"] == team_b.id for row in rows_b), table.name

    foreign_ctx = TeamContext(uuid4(), user_a.id, Role.OWNER)
    assert not await message_repo.list_all(foreign_ctx)
    await engine.dispose()


async def _seed_team(
    sessions: async_sessionmaker[AsyncSession],
    ctx: TeamContext,
    user_id: UUID,
    suffix: str,
    now: datetime,
) -> None:
    membership_repo = TeamScopedRepository(sessions, Membership, MembershipValues)
    chat_repo = TeamScopedRepository(sessions, Chat, ChatValues)
    message_repo = TeamScopedRepository(sessions, Message, MessageValues)
    sequence_repo = TeamScopedRepository(sessions, TeamSequence, TeamSequenceValues)
    task_repo = TeamScopedRepository(sessions, TaskRecord, TaskValues)
    idea_repo = TeamScopedRepository(sessions, IdeaRecord, IdeaValues)
    tag_repo = TeamScopedRepository(sessions, IdeaTag, IdeaTagValues)
    code_repo = TeamScopedRepository(sessions, AccessCodeRecord, AccessCodeValues)

    await membership_repo.add(ctx, MembershipValues(user_id=user_id, role=Role.OWNER))
    chat = await chat_repo.add(ctx, ChatValues(platform="test", chat_id=suffix))
    await message_repo.add(
        ctx,
        MessageValues(
            chat_id=chat.id,
            platform="test",
            message_id=suffix,
            user_id=user_id,
            ts=now,
            raw={},
        ),
    )
    await sequence_repo.add(ctx, TeamSequenceValues(name="tasks", value=1))
    await task_repo.add(
        ctx,
        TaskValues(
            number=1,
            title=f"task-{suffix}",
            status=TaskStatus.OPEN,
            source_type="chat",
            created_by=user_id,
            created_at=now,
        ),
    )
    idea = await idea_repo.add(
        ctx,
        IdeaValues(
            author_id=user_id,
            text=f"idea-{suffix}",
            text_norm=f"idea-{suffix}",
            status=IdeaStatus.ACTIVE,
            created_at=now,
        ),
    )
    await tag_repo.add(
        ctx,
        IdeaTagValues(idea_id=idea.id, tag=suffix, tag_norm=suffix),
    )
    await code_repo.add(
        ctx,
        AccessCodeValues(
            purpose=AccessCodePurpose.INVITE,
            code_hash=hash_access_code(f"code-{suffix}"),
            expires_at=now + timedelta(hours=1),
            created_by=user_id,
            role=Role.MEMBER,
        ),
    )

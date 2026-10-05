"""Юнит-тесты identity/team сервиса на фейковых портах."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest

from teambot.core.errors import AccessCodeError, PermissionDenied
from teambot.core.models import (
    AccessCode,
    AccessCodePurpose,
    ChatRef,
    ExternalIdentity,
    NewAccessCode,
    Role,
    Team,
    TeamContext,
    TeamMember,
    User,
)
from teambot.core.services.identity import IdentityService


class FakeIdentityStore:
    def __init__(self) -> None:
        self.users: dict[ExternalIdentity, User] = {}

    async def find_user(self, identity: ExternalIdentity) -> User | None:
        return self.users.get(identity)

    async def create_user(self, identity: ExternalIdentity, display_name: str) -> User:
        user = User(uuid4(), display_name)
        self.users[identity] = user
        return user

    async def add_identity(self, user_id: UUID, identity: ExternalIdentity) -> None:
        existing = next(user for user in self.users.values() if user.id == user_id)
        self.users[identity] = existing


class FakeTeamStore:
    def __init__(self, team: Team, members: list[TeamMember]) -> None:
        self.team = team
        self.members = members
        self.chats: dict[ChatRef, UUID] = {}

    async def get_context(self, team_id: UUID, user_id: UUID) -> TeamContext | None:
        member = next(
            (item for item in self.members if item.user_id == user_id),
            None,
        )
        if team_id != self.team.id or member is None:
            return None
        return TeamContext(team_id, user_id, member.role)

    async def resolve_chat(self, user_id: UUID, chat: ChatRef) -> TeamContext | None:
        team_id = self.chats.get(chat)
        if team_id is None:
            return None
        return await self.get_context(team_id, user_id)

    async def get_team(self, ctx: TeamContext) -> Team:
        assert ctx.team_id == self.team.id
        return self.team

    async def list_members(self, ctx: TeamContext) -> list[TeamMember]:
        assert ctx.team_id == self.team.id
        return list(self.members)

    async def add_member(self, ctx: TeamContext) -> TeamMember:
        member = TeamMember(ctx.user_id, "Новый участник", ctx.role)
        self.members.append(member)
        return member

    async def bind_chat(self, ctx: TeamContext, chat: ChatRef) -> None:
        self.chats[chat] = ctx.team_id

    async def set_role(
        self,
        ctx: TeamContext,
        user_id: UUID,
        role: Role,
    ) -> TeamMember:
        current = next(member for member in self.members if member.user_id == user_id)
        updated = TeamMember(current.user_id, current.display_name, role)
        self.members[self.members.index(current)] = updated
        return updated

    async def find_owned_team(self, user_id: UUID) -> TeamContext | None:
        owners = [
            member
            for member in self.members
            if member.user_id == user_id and member.role is Role.OWNER
        ]
        if len(owners) != 1:
            return None
        return TeamContext(self.team.id, user_id, Role.OWNER)

    async def ensure_owned_team(self, user: User, team_name: str) -> TeamContext:
        existing = await self.find_owned_team(user.id)
        if existing is not None:
            return existing
        self.team = Team(uuid4(), team_name)
        self.members.append(TeamMember(user.id, user.display_name, Role.OWNER))
        return TeamContext(self.team.id, user.id, Role.OWNER)


class FakeAccessCodeStore:
    def __init__(self) -> None:
        self.codes: dict[UUID, AccessCode] = {}

    async def create(self, ctx: TeamContext, data: NewAccessCode) -> AccessCode:
        access = AccessCode(
            id=data.id,
            code=data.code,
            purpose=data.purpose,
            expires_at=data.expires_at,
            team_id=ctx.team_id,
            role=data.role,
            target_user_id=data.target_user_id,
        )
        self.codes[access.id] = access
        return access

    async def find(
        self,
        code: str,
        purpose: AccessCodePurpose,
    ) -> AccessCode | None:
        return next(
            (
                access
                for access in self.codes.values()
                if access.code == code and access.purpose is purpose
            ),
            None,
        )

    async def consume(self, ctx: TeamContext, code_id: UUID) -> bool:
        access = self.codes[code_id]
        if access.team_id != ctx.team_id or access.used_at is not None:
            return False
        self.codes[code_id] = AccessCode(
            id=access.id,
            code=access.code,
            purpose=access.purpose,
            expires_at=access.expires_at,
            team_id=access.team_id,
            role=access.role,
            target_user_id=access.target_user_id,
            used_at=datetime.now(UTC),
        )
        return True


async def test_invitation_creates_team_scoped_member_once() -> None:
    team = Team(uuid4(), "Разработка")
    owner_user = User(uuid4(), "Владелец")
    owner = TeamMember(owner_user.id, owner_user.display_name, Role.OWNER)
    identities = FakeIdentityStore()
    teams = FakeTeamStore(team, [owner])
    codes = FakeAccessCodeStore()
    service = IdentityService(
        identities,
        teams,
        codes,
        code_factory=lambda: "invite-code",
    )
    owner_ctx = TeamContext(team.id, owner_user.id, Role.OWNER)

    invite = await service.create_invite(owner_ctx, Role.MEMBER)
    identity = ExternalIdentity("channel-a", "new-user")
    joined = await service.accept_invite(identity, invite.code)

    assert joined.team_id == team.id
    assert joined.role is Role.MEMBER
    assert teams.members[-1].user_id == joined.user_id
    with pytest.raises(AccessCodeError):
        await service.accept_invite(ExternalIdentity("channel-a", "other"), invite.code)


async def test_admin_cannot_grant_admin_or_change_owner() -> None:
    team = Team(uuid4(), "Команда")
    owner = TeamMember(uuid4(), "Владелец", Role.OWNER)
    admin = TeamMember(uuid4(), "Администратор", Role.ADMIN)
    teams = FakeTeamStore(team, [owner, admin])
    service = IdentityService(FakeIdentityStore(), teams, FakeAccessCodeStore())
    admin_ctx = TeamContext(team.id, admin.user_id, Role.ADMIN)

    with pytest.raises(PermissionDenied):
        await service.create_invite(admin_ctx, Role.ADMIN)
    with pytest.raises(PermissionDenied):
        await service.set_role(admin_ctx, owner.user_id, Role.MEMBER)


async def test_bootstrap_owner_is_idempotent() -> None:
    identities = FakeIdentityStore()
    teams = FakeTeamStore(Team(uuid4(), "Старая"), [])
    service = IdentityService(identities, teams, FakeAccessCodeStore())
    identity = ExternalIdentity("channel-a", "owner-1")

    first = await service.bootstrap_owner(identity, "Основная")
    second = await service.bootstrap_owner(identity, "Другая")

    assert first.team_id == second.team_id
    assert first.role is Role.OWNER
    assert teams.team.name == "Основная"


async def test_register_does_not_make_random_user_owner() -> None:
    identities = FakeIdentityStore()
    teams = FakeTeamStore(Team(uuid4(), "Чужая"), [])
    service = IdentityService(identities, teams, FakeAccessCodeStore())

    user = await service.register(ExternalIdentity("channel-a", "random-1"), "Случайный")

    assert await teams.find_owned_team(user.id) is None


async def test_link_and_bind_codes_are_single_use_and_expire() -> None:
    team = Team(uuid4(), "Команда")
    owner_user = User(uuid4(), "Владелец")
    owner = TeamMember(owner_user.id, owner_user.display_name, Role.OWNER)
    identities = FakeIdentityStore()
    identities.users[ExternalIdentity("channel-a", "owner-1")] = owner_user
    teams = FakeTeamStore(team, [owner])
    codes = FakeAccessCodeStore()
    now = datetime(2026, 1, 1, tzinfo=UTC)
    service = IdentityService(
        identities,
        teams,
        codes,
        clock=lambda: now,
        code_factory=lambda: "fresh-code",
    )
    ctx = TeamContext(team.id, owner_user.id, Role.OWNER)

    link = await service.create_link_code(ctx)
    linked = await service.link_account(ExternalIdentity("channel-b", "owner-alt"), link.code)
    assert linked.id == owner_user.id
    with pytest.raises(AccessCodeError):
        await service.link_account(ExternalIdentity("channel-b", "other"), link.code)

    bind = await service.create_bind_code(ctx)
    bound = await service.bind_chat(
        owner_user.id,
        ChatRef("channel-a", "chat-2"),
        bind.code,
    )
    assert bound.team_id == team.id
    assert teams.chats[ChatRef("channel-a", "chat-2")] == team.id
    with pytest.raises(AccessCodeError):
        await service.bind_chat(
            owner_user.id,
            ChatRef("channel-a", "chat-3"),
            bind.code,
        )

    expired_codes = FakeAccessCodeStore()
    expired_service = IdentityService(
        identities,
        teams,
        expired_codes,
        clock=lambda: now,
        code_factory=lambda: "expired-code",
        code_lifetime=timedelta(minutes=1),
    )
    invite = await expired_service.create_invite(ctx, Role.MEMBER)
    later = IdentityService(
        identities,
        teams,
        expired_codes,
        clock=lambda: now + timedelta(minutes=2),
    )
    with pytest.raises(AccessCodeError):
        await later.accept_invite(ExternalIdentity("channel-a", "late"), invite.code)

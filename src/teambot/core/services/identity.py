"""Сервис идентичности, команд и ролей этапа M1.

Сервис координирует глобальные идентичности с командными портами. Одноразовый
код сначала безопасно определяет целевую область, после чего все изменения
командных данных выполняются с явным ``TeamContext``.
"""

import secrets
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from teambot.core.errors import (
    AccessCodeError,
    IdentityRequired,
    PermissionDenied,
    TeamRequired,
    ValidationError,
)
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
    role_allows,
)
from teambot.core.ports import AccessCodeStore, IdentityStore, TeamStore

CODE_LIFETIME = timedelta(minutes=15)


class IdentityService:
    """Реализует регистрацию, привязки и управление командой."""

    def __init__(
        self,
        identities: IdentityStore,
        teams: TeamStore,
        codes: AccessCodeStore,
        *,
        clock: Callable[[], datetime] | None = None,
        code_factory: Callable[[], str] | None = None,
        code_lifetime: timedelta | None = None,
    ) -> None:
        """Создаёт сервис с портами и заменяемыми источниками времени/кодов."""
        self._identities = identities
        self._teams = teams
        self._codes = codes
        self._clock = clock or (lambda: datetime.now(UTC))
        self._code_factory = code_factory or (lambda: secrets.token_urlsafe(9))
        self._code_lifetime = code_lifetime or CODE_LIFETIME

    async def register(
        self,
        identity: ExternalIdentity,
        display_name: str | None = None,
        chat: ChatRef | None = None,
    ) -> User:
        """Возвращает существующего либо создаёт нового пользователя.

        Если у пользователя ровно одна команда с ролью владельца, текущий чат
        привязывается автоматически: иначе первый чат нельзя привязать через
        ``/bind``, потому что эта команда сама требует уже известный контекст.
        """
        existing = await self._identities.find_user(identity)
        user = existing
        if user is None:
            clean_name = (display_name or identity.external_user_id).strip()
            if not clean_name:
                raise ValidationError("Имя пользователя не может быть пустым")
            user = await self._identities.create_user(identity, clean_name)
        if chat is not None:
            await self._bind_owned_chat(user.id, chat)
        return user

    async def bootstrap_owner(
        self,
        identity: ExternalIdentity,
        team_name: str,
        display_name: str | None = None,
    ) -> TeamContext:
        """Идемпотентно создаёт первую команду и назначает владельца."""
        clean_name = team_name.strip()
        if not clean_name:
            raise ValidationError("Имя команды не может быть пустым")
        user = await self.register(identity, display_name=display_name)
        return await self._teams.ensure_owned_team(user, clean_name)

    async def identify(self, identity: ExternalIdentity) -> User:
        """Возвращает связанного пользователя или сообщает о регистрации."""
        user = await self._identities.find_user(identity)
        if user is None:
            raise IdentityRequired
        return user

    async def resolve(
        self,
        identity: ExternalIdentity,
        chat: ChatRef,
    ) -> tuple[User, TeamContext]:
        """Разрешает внешний аккаунт и чат в строгий командный контекст."""
        user = await self._identities.find_user(identity)
        if user is None:
            raise IdentityRequired
        ctx = await self._teams.resolve_chat(user.id, chat)
        if ctx is None:
            raise TeamRequired
        return user, ctx

    async def create_link_code(self, ctx: TeamContext) -> AccessCode:
        """Создаёт код для привязки ещё одного аккаунта текущего пользователя."""
        _require_role(ctx, Role.MEMBER)
        return await self._create_code(
            ctx,
            AccessCodePurpose.LINK,
            target_user_id=ctx.user_id,
        )

    async def link_account(self, identity: ExternalIdentity, code: str) -> User:
        """Привязывает текущий внешний аккаунт по одноразовому коду."""
        access = await self._valid_code(code, AccessCodePurpose.LINK)
        if access.target_user_id is None or access.team_id is None:
            raise AccessCodeError
        ctx = await self._teams.get_context(access.team_id, access.target_user_id)
        if ctx is None:
            raise AccessCodeError
        if not await self._codes.consume(ctx, access.id):
            raise AccessCodeError
        await self._identities.add_identity(access.target_user_id, identity)
        user = await self._identities.find_user(identity)
        if user is None:
            raise AccessCodeError
        return user

    async def create_bind_code(self, ctx: TeamContext) -> AccessCode:
        """Создаёт код привязки нового чата к текущей команде."""
        _require_role(ctx, Role.ADMIN)
        return await self._create_code(ctx, AccessCodePurpose.BIND)

    async def bind_chat(self, user_id: UUID, chat: ChatRef, code: str) -> TeamContext:
        """Привязывает чат по коду, проверяя роль пользователя в целевой команде."""
        access = await self._valid_code(code, AccessCodePurpose.BIND)
        if access.team_id is None:
            raise AccessCodeError
        ctx = await self._teams.get_context(access.team_id, user_id)
        if ctx is None:
            raise PermissionDenied
        _require_role(ctx, Role.ADMIN)
        if not await self._codes.consume(ctx, access.id):
            raise AccessCodeError
        await self._teams.bind_chat(ctx, chat)
        return ctx

    async def create_invite(self, ctx: TeamContext, role: Role = Role.MEMBER) -> AccessCode:
        """Создаёт приглашение с ролью не выше полномочий инициатора."""
        _require_role(ctx, Role.ADMIN)
        if role is Role.OWNER or not role_allows(ctx.role, role):
            raise PermissionDenied
        if ctx.role is Role.ADMIN and role is Role.ADMIN:
            raise PermissionDenied
        return await self._create_code(ctx, AccessCodePurpose.INVITE, role=role)

    async def accept_invite(
        self,
        identity: ExternalIdentity,
        code: str,
        chat: ChatRef | None = None,
    ) -> TeamContext:
        """Регистрирует аккаунт при необходимости и принимает приглашение."""
        access = await self._valid_code(code, AccessCodePurpose.INVITE)
        if access.team_id is None or access.role is None:
            raise AccessCodeError
        user = await self.register(identity)
        ctx = TeamContext(access.team_id, user.id, access.role)
        if not await self._codes.consume(ctx, access.id):
            raise AccessCodeError
        await self._teams.add_member(ctx)
        if chat is not None:
            await self._teams.bind_chat(ctx, chat)
        return ctx

    async def team(self, ctx: TeamContext) -> tuple[Team, list[TeamMember]]:
        """Возвращает команду и её участников для роли ``member`` и выше."""
        _require_role(ctx, Role.MEMBER)
        return await self._teams.get_team(ctx), await self._teams.list_members(ctx)

    async def set_role(self, ctx: TeamContext, user_id: UUID, role: Role) -> TeamMember:
        """Назначает участнику роль с защитой роли владельца."""
        _require_role(ctx, Role.ADMIN)
        if role is Role.OWNER or (ctx.role is Role.ADMIN and role is Role.ADMIN):
            raise PermissionDenied
        members = await self._teams.list_members(ctx)
        current = next((member for member in members if member.user_id == user_id), None)
        if current is None:
            raise ValidationError("Участник не найден")
        if current.role is Role.OWNER:
            raise PermissionDenied
        return await self._teams.set_role(ctx, user_id, role)

    async def _create_code(
        self,
        ctx: TeamContext,
        purpose: AccessCodePurpose,
        *,
        role: Role | None = None,
        target_user_id: UUID | None = None,
    ) -> AccessCode:
        return await self._codes.create(
            ctx,
            NewAccessCode(
                id=uuid4(),
                code=self._code_factory(),
                purpose=purpose,
                expires_at=self._clock() + self._code_lifetime,
                role=role,
                target_user_id=target_user_id,
            ),
        )

    async def _valid_code(self, code: str, purpose: AccessCodePurpose) -> AccessCode:
        clean_code = code.strip()
        if not clean_code:
            raise ValidationError("Требуется одноразовый код")
        access = await self._codes.find(clean_code, purpose)
        if access is None or access.used_at is not None or access.expires_at <= self._clock():
            raise AccessCodeError
        return access

    async def _bind_owned_chat(self, user_id: UUID, chat: ChatRef) -> None:
        """Привязывает чат к единственной команде, которой пользователь владеет."""
        existing = await self._teams.resolve_chat(user_id, chat)
        if existing is not None:
            return
        owned = await self._teams.find_owned_team(user_id)
        if owned is None:
            return
        await self._teams.bind_chat(owned, chat)


def _require_role(ctx: TeamContext, required: Role) -> None:
    if not role_allows(ctx.role, required):
        raise PermissionDenied

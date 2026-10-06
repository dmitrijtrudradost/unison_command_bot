"""SQLAlchemy-реализации портов хранения этапа M1.

Модуль принадлежит адаптеру хранения: ядро получает только доменные типы.
Диалектный upsert вызывается через ``dialect.py`` (DB-2).
"""

from collections.abc import Sequence
from datetime import UTC, datetime
from uuid import UUID, uuid4

from sqlalchemy import Table, delete, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session

from teambot.adapters.storage.dialect import portable_upsert
from teambot.adapters.storage.hashing import hash_access_code
from teambot.adapters.storage.models import (
    AccessCodeRecord,
    Chat,
    IdeaRecord,
    IdeaTag,
    InboundEventRecord,
    Membership,
    TaskRecord,
    Team,
    TeamSequence,
    User,
    UserIdentity,
    utc_now,
)
from teambot.core.errors import ValidationError
from teambot.core.models import (
    AccessCode,
    AccessCodePurpose,
    BoundChat,
    ChatRef,
    EventKey,
    ExternalIdentity,
    Idea,
    IdeaFilter,
    IdeaMatch,
    IdeaStatus,
    NewAccessCode,
    NewIdea,
    NewTask,
    Role,
    Task,
    TaskFilter,
    TaskPatch,
    TaskStatus,
    TeamContext,
    TeamMember,
)
from teambot.core.models import (
    Team as DomainTeam,
)
from teambot.core.models import (
    User as DomainUser,
)


def _task_from_row(row: TaskRecord) -> Task:
    return Task(
        id=row.id,
        team_id=row.team_id,
        number=row.number,
        title=row.title,
        status=TaskStatus(row.status),
        created_by=row.created_by,
        description=row.description,
        assignee_id=row.assignee_id,
        due_at=row.due_at,
        created_at=row.created_at,
    )


def _idea_from_row(row: IdeaRecord, tags: tuple[str, ...]) -> Idea:
    return Idea(
        id=row.id,
        team_id=row.team_id,
        author_id=row.author_id,
        text=row.text,
        text_norm=row.text_norm,
        status=IdeaStatus(row.status),
        tags=tags,
        source_message_id=row.source_message_id,
        created_at=row.created_at,
    )


def _user_from_row(row: User) -> DomainUser:
    return DomainUser(id=row.id, display_name=row.display_name)


MAX_CHAT_TITLE_LENGTH = 300


def _clean_chat_title(title: str | None) -> str | None:
    """Нормализует название чата под ограничение колонки ``chats.title``."""
    if title is None:
        return None
    clean_title = title.strip()
    if not clean_title:
        return None
    return clean_title[:MAX_CHAT_TITLE_LENGTH]


class SqlEventDeduplicator:
    """Регистрирует входящие события атомарным upsert без повторной обработки."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохраняет фабрику коротких транзакций."""
        self._sessions = sessions

    async def claim(self, key: EventKey) -> bool:
        """Вставляет ключ; ``False`` означает, что событие уже встречалось."""
        values = {
            "id": uuid4(),
            "platform": key.source,
            "chat_id": key.chat_id,
            "message_id": key.message_id,
            "claimed_at": datetime.now(UTC),
        }

        def _upsert(sync_session: Session) -> int:
            connection = sync_session.connection()
            table = InboundEventRecord.__table__
            assert isinstance(table, Table)
            statement = portable_upsert(
                connection,
                table,
                values,
                ("platform", "chat_id", "message_id"),
            )
            result = connection.execute(statement)
            return int(result.rowcount or 0)

        async with self._sessions() as session, session.begin():
            rowcount = await session.run_sync(_upsert)
        return rowcount == 1


class SqlIdentityStore:
    """Хранит глобальных пользователей и внешние идентичности."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохраняет фабрику сессий."""
        self._sessions = sessions

    async def find_user(self, identity: ExternalIdentity) -> DomainUser | None:
        """Ищет пользователя по непрозрачной внешней идентичности."""
        async with self._sessions() as session:
            row = await session.scalar(
                select(User)
                .join(UserIdentity, UserIdentity.user_id == User.id)
                .where(
                    UserIdentity.platform == identity.source,
                    UserIdentity.platform_user_id == identity.external_user_id,
                )
            )
        return None if row is None else _user_from_row(row)

    async def create_user(self, identity: ExternalIdentity, display_name: str) -> DomainUser:
        """Создаёт пользователя и первую идентичность в одной транзакции."""
        user = User(id=uuid4(), display_name=display_name)
        link = UserIdentity(
            id=uuid4(),
            user_id=user.id,
            platform=identity.source,
            platform_user_id=identity.external_user_id,
        )
        async with self._sessions() as session, session.begin():
            session.add_all([user, link])
        return _user_from_row(user)

    async def add_identity(self, user_id: UUID, identity: ExternalIdentity) -> None:
        """Добавляет идентичность, игнорируя повтор той же пары."""
        values = {
            "id": uuid4(),
            "user_id": user_id,
            "platform": identity.source,
            "platform_user_id": identity.external_user_id,
        }

        def _upsert(sync_session: Session) -> None:
            connection = sync_session.connection()
            table = UserIdentity.__table__
            assert isinstance(table, Table)
            statement = portable_upsert(
                connection,
                table,
                values,
                ("platform", "platform_user_id"),
            )
            connection.execute(statement)

        async with self._sessions() as session, session.begin():
            await session.run_sync(_upsert)


class SqlTeamStore:
    """Управляет командами, членством и привязкой чатов."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохраняет фабрику сессий."""
        self._sessions = sessions

    async def get_context(self, team_id: UUID, user_id: UUID) -> TeamContext | None:
        """Возвращает роль пользователя в указанной команде."""
        async with self._sessions() as session:
            role = await session.scalar(
                select(Membership.role).where(
                    Membership.team_id == team_id,
                    Membership.user_id == user_id,
                )
            )
        if role is None:
            return None
        return TeamContext(team_id, user_id, Role(role))

    async def resolve_chat(self, user_id: UUID, chat: ChatRef) -> TeamContext | None:
        """Разрешает привязанный чат в контекст участника."""
        async with self._sessions() as session:
            row = await session.execute(
                select(Chat.team_id, Membership.role)
                .join(
                    Membership,
                    (Membership.team_id == Chat.team_id) & (Membership.user_id == user_id),
                )
                .where(Chat.platform == chat.source, Chat.chat_id == chat.external_chat_id)
            )
            mapped = row.first()
        if mapped is None:
            return None
        return TeamContext(mapped.team_id, user_id, Role(mapped.role))

    async def get_team(self, ctx: TeamContext) -> DomainTeam:
        """Возвращает команду из области контекста."""
        async with self._sessions() as session:
            row = await session.scalar(select(Team).where(Team.id == ctx.team_id))
        if row is None:
            raise ValidationError("Команда не найдена")
        return DomainTeam(id=row.id, name=row.name)

    async def list_members(self, ctx: TeamContext) -> list[TeamMember]:
        """Возвращает участников только текущей команды."""
        async with self._sessions() as session:
            rows = (
                await session.execute(
                    select(Membership, User)
                    .join(User, User.id == Membership.user_id)
                    .where(Membership.team_id == ctx.team_id)
                    .order_by(Membership.id)
                )
            ).all()
        return [
            TeamMember(membership.user_id, user.display_name, Role(membership.role))
            for membership, user in rows
        ]

    async def add_member(self, ctx: TeamContext) -> TeamMember:
        """Добавляет участника; повторное членство возвращает текущую роль."""
        async with self._sessions() as session, session.begin():
            existing = await session.scalar(
                select(Membership).where(
                    Membership.team_id == ctx.team_id,
                    Membership.user_id == ctx.user_id,
                )
            )
            if existing is None:
                session.add(
                    Membership(
                        id=uuid4(),
                        team_id=ctx.team_id,
                        user_id=ctx.user_id,
                        role=ctx.role.value,
                    )
                )
                role = ctx.role
            else:
                role = Role(existing.role)
            user = await session.get(User, ctx.user_id)
        display_name = user.display_name if user is not None else str(ctx.user_id)
        return TeamMember(ctx.user_id, display_name, role)

    async def bind_chat(
        self,
        ctx: TeamContext,
        chat: ChatRef,
        title: str | None = None,
    ) -> None:
        """Привязывает чат к команде либо подтверждает уже существующую связь.

        Название обновляется только если передано: повторная привязка без
        заголовка не затирает ранее сохранённое имя.
        """
        clean_title = _clean_chat_title(title)
        async with self._sessions() as session, session.begin():
            existing = await session.scalar(
                select(Chat).where(
                    Chat.platform == chat.source,
                    Chat.chat_id == chat.external_chat_id,
                )
            )
            if existing is None:
                session.add(
                    Chat(
                        id=uuid4(),
                        team_id=ctx.team_id,
                        platform=chat.source,
                        chat_id=chat.external_chat_id,
                        title=clean_title,
                    )
                )
                return
            if existing.team_id != ctx.team_id:
                raise ValidationError("Чат уже привязан к другой команде")
            if clean_title is not None:
                existing.title = clean_title

    async def list_chats(self, ctx: TeamContext) -> list[BoundChat]:
        """Возвращает привязки только указанной команды."""
        async with self._sessions() as session:
            rows = (await session.scalars(select(Chat).where(Chat.team_id == ctx.team_id))).all()
        chats = [BoundChat(ChatRef(row.platform, row.chat_id), row.title) for row in rows]
        # Сортировка по непрозрачным идентификаторам, не по отображаемому имени:
        # правило DB про локаль относится к пользовательскому тексту.
        return sorted(chats, key=lambda item: (item.ref.source, item.ref.external_chat_id))

    async def set_role(self, ctx: TeamContext, user_id: UUID, role: Role) -> TeamMember:
        """Обновляет роль участника в команде контекста."""
        async with self._sessions() as session, session.begin():
            membership = await session.scalar(
                select(Membership).where(
                    Membership.team_id == ctx.team_id,
                    Membership.user_id == user_id,
                )
            )
            if membership is None:
                raise ValidationError("Участник не найден")
            membership.role = role.value
            user = await session.get(User, user_id)
        display_name = user.display_name if user is not None else str(user_id)
        return TeamMember(user_id, display_name, role)

    async def remove_member(self, ctx: TeamContext, user_id: UUID) -> None:
        """Удаляет членство только внутри текущей команды."""
        async with self._sessions() as session, session.begin():
            removed_id = (
                await session.scalars(
                    delete(Membership)
                    .where(
                        Membership.team_id == ctx.team_id,
                        Membership.user_id == user_id,
                    )
                    .returning(Membership.id)
                )
            ).first()
        if removed_id is None:
            raise ValidationError("Участник не найден")

    async def unbind_chat(self, ctx: TeamContext, chat: ChatRef) -> None:
        """Удаляет привязку текущего чата к команде контекста."""
        async with self._sessions() as session, session.begin():
            removed_id = (
                await session.scalars(
                    delete(Chat)
                    .where(
                        Chat.team_id == ctx.team_id,
                        Chat.platform == chat.source,
                        Chat.chat_id == chat.external_chat_id,
                    )
                    .returning(Chat.id)
                )
            ).first()
        if removed_id is None:
            raise ValidationError("Чат не привязан к этой команде")

    async def find_owned_team(self, user_id: UUID) -> TeamContext | None:
        """Возвращает контекст, только если владелецская команда одна."""
        async with self._sessions() as session:
            rows = (
                await session.scalars(
                    select(Membership).where(
                        Membership.user_id == user_id,
                        Membership.role == Role.OWNER.value,
                    )
                )
            ).all()
        if len(rows) != 1:
            return None
        membership = rows[0]
        return TeamContext(membership.team_id, user_id, Role.OWNER)

    async def ensure_owned_team(self, user: DomainUser, team_name: str) -> TeamContext:
        """Создаёт команду владельца один раз и инициализирует счётчик задач."""
        existing = await self.find_owned_team(user.id)
        if existing is not None:
            return existing
        team_id = uuid4()
        async with self._sessions() as session, session.begin():
            # Сначала команда: без relationship SQLAlchemy мог бы вставить
            # memberships раньше teams и нарушить внешний ключ.
            session.add(Team(id=team_id, name=team_name))
            await session.flush()
            session.add_all(
                [
                    Membership(
                        id=uuid4(),
                        team_id=team_id,
                        user_id=user.id,
                        role=Role.OWNER.value,
                    ),
                    TeamSequence(id=uuid4(), team_id=team_id, name="tasks", value=0),
                ]
            )
        return TeamContext(team_id, user.id, Role.OWNER)


class SqlAccessCodeStore:
    """Хранит одноразовые коды только в виде криптографического хеша."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохраняет фабрику сессий."""
        self._sessions = sessions

    async def create(self, ctx: TeamContext, data: NewAccessCode) -> AccessCode:
        """Сохраняет хеш кода и возвращает открытое значение для однократного показа."""
        record = AccessCodeRecord(
            id=data.id,
            team_id=ctx.team_id,
            purpose=data.purpose.value,
            code_hash=hash_access_code(data.code),
            expires_at=data.expires_at,
            used_at=None,
            created_by=ctx.user_id,
            target_user_id=data.target_user_id,
            role=None if data.role is None else data.role.value,
        )
        async with self._sessions() as session, session.begin():
            session.add(record)
        return AccessCode(
            id=data.id,
            code=data.code,
            purpose=data.purpose,
            expires_at=data.expires_at,
            team_id=ctx.team_id,
            role=data.role,
            target_user_id=data.target_user_id,
        )

    async def find(self, code: str, purpose: AccessCodePurpose) -> AccessCode | None:
        """Ищет код по хешу до восстановления командного контекста."""
        digest = hash_access_code(code)
        async with self._sessions() as session:
            row = await session.scalar(
                select(AccessCodeRecord).where(
                    AccessCodeRecord.code_hash == digest,
                    AccessCodeRecord.purpose == purpose.value,
                )
            )
        if row is None:
            return None
        return AccessCode(
            id=row.id,
            code=code,
            purpose=AccessCodePurpose(row.purpose),
            expires_at=row.expires_at,
            team_id=row.team_id,
            role=None if row.role is None else Role(row.role),
            target_user_id=row.target_user_id,
            used_at=row.used_at,
        )

    async def consume(self, ctx: TeamContext, code_id: UUID) -> bool:
        """Атомарно помечает код использованным, чтобы повтор не сработал."""
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(AccessCodeRecord)
                .where(
                    AccessCodeRecord.id == code_id,
                    AccessCodeRecord.team_id == ctx.team_id,
                    AccessCodeRecord.used_at.is_(None),
                )
                .values(used_at=datetime.now(UTC))
                .returning(AccessCodeRecord.id)
            )
            consumed = result.scalar_one_or_none()
        return consumed is not None


class SqlTaskStore:
    """Хранилище задач с атомарной нумерацией внутри команды."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохраняет фабрику сессий."""
        self._sessions = sessions

    async def create(self, ctx: TeamContext, task: NewTask) -> Task:
        """Создаёт задачу и увеличивает командный счётчик одним UPDATE."""
        created_at = utc_now()
        task_id = uuid4()
        async with self._sessions() as session, session.begin():
            result = await session.execute(
                update(TeamSequence)
                .where(TeamSequence.team_id == ctx.team_id, TeamSequence.name == "tasks")
                .values(value=TeamSequence.value + 1)
                .returning(TeamSequence.value)
            )
            number = result.scalar_one_or_none()
            if number is None:
                raise ValidationError("Счётчик задач команды не инициализирован")
            row = TaskRecord(
                id=task_id,
                team_id=ctx.team_id,
                number=number,
                title=task.title,
                description=task.description,
                assignee_id=task.assignee_id,
                due_at=task.due_at,
                status=TaskStatus.OPEN.value,
                source_type="chat",
                source_id=None,
                created_by=ctx.user_id,
                created_at=created_at,
            )
            session.add(row)
        return Task(
            id=task_id,
            team_id=ctx.team_id,
            number=number,
            title=task.title,
            status=TaskStatus.OPEN,
            created_by=ctx.user_id,
            description=task.description,
            assignee_id=task.assignee_id,
            due_at=task.due_at,
            created_at=created_at,
        )

    async def update(self, ctx: TeamContext, task_id: UUID, patch: TaskPatch) -> Task:
        """Обновляет задачу только в области текущей команды."""
        async with self._sessions() as session, session.begin():
            row = await session.scalar(
                select(TaskRecord).where(
                    TaskRecord.id == task_id,
                    TaskRecord.team_id == ctx.team_id,
                )
            )
            if row is None:
                raise ValidationError("Задача не найдена")
            if patch.title is not None:
                row.title = patch.title
            if patch.description is not None:
                row.description = patch.description
            if patch.assignee_id is not None:
                row.assignee_id = patch.assignee_id
            if patch.due_at is not None:
                row.due_at = patch.due_at
            if patch.status is not None:
                row.status = patch.status.value
            await session.flush()
            return _task_from_row(row)

    async def list(self, ctx: TeamContext, filt: TaskFilter) -> list[Task]:
        """Возвращает задачи команды, сортируя по числовому номеру."""
        statement = select(TaskRecord).where(TaskRecord.team_id == ctx.team_id)
        if filt.status is not None:
            statement = statement.where(TaskRecord.status == filt.status.value)
        if filt.assignee_id is not None:
            statement = statement.where(TaskRecord.assignee_id == filt.assignee_id)
        statement = statement.order_by(TaskRecord.number, TaskRecord.id)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
        return [_task_from_row(row) for row in rows]

    async def get_by_number(self, ctx: TeamContext, number: int) -> Task | None:
        """Находит задачу по устойчивому номеру внутри команды."""
        async with self._sessions() as session:
            row = await session.scalar(
                select(TaskRecord).where(
                    TaskRecord.team_id == ctx.team_id,
                    TaskRecord.number == number,
                )
            )
        return None if row is None else _task_from_row(row)


class SqlIdeaStore:
    """Хранилище идей и тегов с фильтром по нормализованным колонкам."""

    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        """Сохраняет фабрику сессий."""
        self._sessions = sessions

    async def create(self, ctx: TeamContext, idea: NewIdea) -> Idea:
        """Создаёт идею и связанные теги в одной транзакции."""
        idea_id = uuid4()
        created_at = utc_now()
        record = IdeaRecord(
            id=idea_id,
            team_id=ctx.team_id,
            author_id=idea.author_id,
            text=idea.text,
            text_norm=idea.text_norm,
            status=IdeaStatus.ACTIVE.value,
            source_message_id=idea.source_message_id,
            created_at=created_at,
        )
        tags = [
            IdeaTag(
                id=uuid4(),
                team_id=ctx.team_id,
                idea_id=idea_id,
                tag=tag,
                tag_norm=tag,
            )
            for tag in idea.tags
        ]
        async with self._sessions() as session, session.begin():
            session.add(record)
            await session.flush()
            session.add_all(tags)
        return _idea_from_row(record, idea.tags)

    async def list(self, ctx: TeamContext, filt: IdeaFilter) -> list[Idea]:
        """Возвращает идеи команды; поиск идёт по ``*_norm``, не по исходному тексту."""
        statement = select(IdeaRecord).where(
            IdeaRecord.team_id == ctx.team_id,
            IdeaRecord.status == filt.status.value,
        )
        if filt.query_norm:
            tag_norm = filt.query_norm.removeprefix("#")
            tag_ids = select(IdeaTag.idea_id).where(
                IdeaTag.team_id == ctx.team_id,
                IdeaTag.tag_norm == tag_norm,
            )
            statement = statement.where(
                or_(
                    IdeaRecord.text_norm.contains(filt.query_norm, autoescape=True),
                    IdeaRecord.id.in_(tag_ids),
                )
            )
        if filt.tags_norm:
            for tag_norm in filt.tags_norm:
                statement = statement.where(
                    IdeaRecord.id.in_(
                        select(IdeaTag.idea_id).where(
                            IdeaTag.team_id == ctx.team_id,
                            IdeaTag.tag_norm == tag_norm,
                        )
                    )
                )
        statement = statement.order_by(IdeaRecord.created_at, IdeaRecord.id)
        async with self._sessions() as session:
            rows = (await session.scalars(statement)).all()
            idea_ids = [row.id for row in rows]
            tag_rows: Sequence[IdeaTag] = []
            if idea_ids:
                tag_rows = (
                    await session.scalars(
                        select(IdeaTag)
                        .where(
                            IdeaTag.team_id == ctx.team_id,
                            IdeaTag.idea_id.in_(idea_ids),
                        )
                        .order_by(IdeaTag.id)
                    )
                ).all()
        tags_by_idea: dict[UUID, list[str]] = {idea_id: [] for idea_id in idea_ids}
        for tag in tag_rows:
            tags_by_idea.setdefault(tag.idea_id, []).append(tag.tag)
        return [_idea_from_row(row, tuple(tags_by_idea.get(row.id, ()))) for row in rows]


class NormalizedIdeaIndex:
    """M1-индекс идей по нормализованному тексту и тегам без FTS и векторов."""

    def __init__(self, store: SqlIdeaStore) -> None:
        """Сохраняет хранилище, которое уже фильтрует по команде."""
        self._store = store

    async def index(self, ctx: TeamContext, idea: Idea) -> None:
        """Ничего не делает: нормализованные поля уже записаны хранилищем."""
        del ctx, idea

    async def find_similar(
        self,
        ctx: TeamContext,
        text: str,
        limit: int = 5,
    ) -> list[IdeaMatch]:
        """Ищет идеи той же команды по нормализованной подстроке и тегам."""
        ideas = await self._store.list(ctx, IdeaFilter(query_norm=text))
        return [IdeaMatch(idea=idea, score=1.0) for idea in ideas[:limit]]

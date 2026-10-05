"""SQLAlchemy-модели схемы M0–M1.

Схема реализует раздел 8 ARCHITECTURE.md и правила DB-3…DB-9, DB-13,
DB-15. Идентификаторы и время создаются приложением, а не сервером БД.
"""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from teambot.adapters.storage.dialect import UtcDateTime, metadata

JSON_TYPE = JSON().with_variant(JSONB(), "postgresql")
ROLE_VALUES = ("owner", "admin", "member", "viewer")


def utc_now() -> datetime:
    """Возвращает текущее aware-время UTC для клиентских default."""
    return datetime.now(UTC)


class Base(DeclarativeBase):
    """Общая декларативная база с именованными ограничениями DB-8."""

    metadata = metadata


class Team(Base):
    """Глобальная рабочая группа."""

    __tablename__ = "teams"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)


class User(Base):
    """Глобальный человек, объединяющий внешние идентичности."""

    __tablename__ = "users"

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    display_name: Mapped[str] = mapped_column(String(200), nullable=False)


class UserIdentity(Base):
    """Связь пользователя с идентификатором во внешнем канале."""

    __tablename__ = "user_identities"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "platform_user_id",
            name="uq_user_identities_platform_platform_user_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    platform_user_id: Mapped[str] = mapped_column(String(200), nullable=False)


class Membership(Base):
    """Командная роль пользователя."""

    __tablename__ = "memberships"
    __table_args__ = (
        CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="role_allowed",
        ),
        UniqueConstraint("team_id", "user_id", name="uq_memberships_team_id_user_id"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)


class Chat(Base):
    """Привязанный к команде внешний чат."""

    __tablename__ = "chats"
    __table_args__ = (UniqueConstraint("platform", "chat_id", name="uq_chats_platform_chat_id"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    title: Mapped[str | None] = mapped_column(String(300), nullable=True)


class Message(Base):
    """Идемпотентно сохранённое входящее сообщение команды."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "chat_id",
            "message_id",
            name="uq_messages_platform_chat_id_message_id",
        ),
        Index("ix_messages_team_id_ts", "team_id", "ts"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    chat_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("chats.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    text: Mapped[str | None] = mapped_column(String(10000), nullable=True)
    ts: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False, default=utc_now)
    raw: Mapped[dict[str, Any]] = mapped_column(JSON_TYPE, nullable=False)


class InboundEventRecord(Base):
    """Глобальный ключ идемпотентности входящего события.

    Таблица намеренно без ``team_id``: дедупликация выполняется до разрешения
    команды, а уникальность ``(platform, chat_id, message_id)`` задана
    архитектурой как платформенно-глобальная.
    """

    __tablename__ = "inbound_events"
    __table_args__ = (
        UniqueConstraint(
            "platform",
            "chat_id",
            "message_id",
            name="uq_inbound_events_platform_chat_id_message_id",
        ),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    platform: Mapped[str] = mapped_column(String(32), nullable=False)
    chat_id: Mapped[str] = mapped_column(String(200), nullable=False)
    message_id: Mapped[str] = mapped_column(String(200), nullable=False)
    claimed_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)


class TeamSequence(Base):
    """Атомарный счётчик номеров сущностей внутри команды."""

    __tablename__ = "team_sequences"
    __table_args__ = (UniqueConstraint("team_id", "name", name="uq_team_sequences_team_id_name"),)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    name: Mapped[str] = mapped_column(String(32), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)


class TaskRecord(Base):
    """Командная задача с устойчивым номером."""

    __tablename__ = "tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open', 'done')", name="status_allowed"),
        UniqueConstraint("team_id", "number", name="uq_tasks_team_id_number"),
        Index("ix_tasks_team_id_status", "team_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(2000), nullable=False)
    description: Mapped[str | None] = mapped_column(String(10000), nullable=True)
    assignee_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    due_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False)
    source_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)


class IdeaRecord(Base):
    """Командная идея с нормализованным текстом для поиска M1."""

    __tablename__ = "ideas"
    __table_args__ = (
        CheckConstraint("status IN ('active', 'archived')", name="status_allowed"),
        Index("ix_ideas_team_id_status", "team_id", "status"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    author_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    text: Mapped[str] = mapped_column(String(4000), nullable=False)
    text_norm: Mapped[str] = mapped_column(String(4000), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    source_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)


class IdeaTag(Base):
    """Тег идеи в отдельной таблице вместо массива (DB-5)."""

    __tablename__ = "idea_tags"
    __table_args__ = (
        UniqueConstraint("idea_id", "tag_norm", name="uq_idea_tags_idea_id_tag_norm"),
        Index("ix_idea_tags_team_id_tag_norm", "team_id", "tag_norm"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    idea_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("ideas.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    tag: Mapped[str] = mapped_column(String(64), nullable=False)
    tag_norm: Mapped[str] = mapped_column(String(64), nullable=False)


class AccessCodeRecord(Base):
    """Одноразовый код приглашения, привязки аккаунта или чата."""

    __tablename__ = "access_codes"
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('link', 'bind', 'invite')",
            name="purpose_allowed",
        ),
        CheckConstraint(
            "role IS NULL OR role IN ('owner', 'admin', 'member', 'viewer')",
            name="role_allowed",
        ),
        UniqueConstraint("code_hash", name="uq_access_codes_code_hash"),
        Index("ix_access_codes_team_id_purpose", "team_id", "purpose"),
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True, default=uuid4)
    team_id: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("teams.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    purpose: Mapped[str] = mapped_column(String(16), nullable=False)
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(UtcDateTime(), nullable=False)
    used_at: Mapped[datetime | None] = mapped_column(UtcDateTime(), nullable=True)
    created_by: Mapped[UUID] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="RESTRICT"),
        nullable=False,
        index=True,
    )
    target_user_id: Mapped[UUID | None] = mapped_column(
        Uuid,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    role: Mapped[str | None] = mapped_column(String(16), nullable=True)

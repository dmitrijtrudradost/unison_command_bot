"""Начальная переносимая схема M0.

Revision ID: 0001_initial
Revises:
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op
from teambot.adapters.storage.dialect import UtcDateTime

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = sa.Uuid()
JSON_TYPE = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    """Создаёт глобальные и командные таблицы M0."""
    op.create_table(
        "teams",
        sa.Column("id", UUID, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_teams"),
    )
    op.create_table(
        "users",
        sa.Column("id", UUID, nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_users"),
    )
    op.create_table(
        "user_identities",
        sa.Column("id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("platform_user_id", sa.String(200), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_user_identities_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_user_identities"),
        sa.UniqueConstraint(
            "platform",
            "platform_user_id",
            name="uq_user_identities_platform_platform_user_id",
        ),
    )
    op.create_index("ix_user_identities_user_id", "user_identities", ["user_id"])
    op.create_table(
        "memberships",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("user_id", UUID, nullable=False),
        sa.Column("role", sa.String(16), nullable=False),
        sa.CheckConstraint(
            "role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_memberships_role_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_memberships_team_id_teams", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_memberships_user_id_users", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_memberships"),
        sa.UniqueConstraint("team_id", "user_id", name="uq_memberships_team_id_user_id"),
    )
    op.create_index("ix_memberships_team_id", "memberships", ["team_id"])
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_table(
        "chats",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(200), nullable=False),
        sa.Column("title", sa.String(300), nullable=True),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_chats_team_id_teams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_chats"),
        sa.UniqueConstraint("platform", "chat_id", name="uq_chats_platform_chat_id"),
    )
    op.create_index("ix_chats_team_id", "chats", ["team_id"])
    op.create_table(
        "messages",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("chat_id", UUID, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("message_id", sa.String(200), nullable=False),
        sa.Column("user_id", UUID, nullable=True),
        sa.Column("text", sa.String(10000), nullable=True),
        sa.Column("ts", UtcDateTime(), nullable=False),
        sa.Column("raw", JSON_TYPE, nullable=False),
        sa.ForeignKeyConstraint(
            ["chat_id"], ["chats.id"], name="fk_messages_chat_id_chats", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_messages_team_id_teams", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name="fk_messages_user_id_users", ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_messages"),
        sa.UniqueConstraint(
            "platform", "chat_id", "message_id", name="uq_messages_platform_chat_id_message_id"
        ),
    )
    op.create_index("ix_messages_chat_id", "messages", ["chat_id"])
    op.create_index("ix_messages_team_id", "messages", ["team_id"])
    op.create_index("ix_messages_team_id_ts", "messages", ["team_id", "ts"])
    op.create_index("ix_messages_user_id", "messages", ["user_id"])


def downgrade() -> None:
    """Удаляет таблицы в порядке, обратном внешним ключам."""
    op.drop_table("messages")
    op.drop_table("chats")
    op.drop_table("memberships")
    op.drop_table("user_identities")
    op.drop_table("users")
    op.drop_table("teams")

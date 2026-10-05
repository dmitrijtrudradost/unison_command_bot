"""Схема идей, задач, одноразовых кодов и идемпотентности M1.

Revision ID: 0002_m1_core
Revises: 0001_initial
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from teambot.adapters.storage.dialect import UtcDateTime

revision: str = "0002_m1_core"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

UUID = sa.Uuid()


def upgrade() -> None:
    """Добавляет командные таблицы этапа M1 и глобальные ключи событий."""
    op.create_table(
        "inbound_events",
        sa.Column("id", UUID, nullable=False),
        sa.Column("platform", sa.String(32), nullable=False),
        sa.Column("chat_id", sa.String(200), nullable=False),
        sa.Column("message_id", sa.String(200), nullable=False),
        sa.Column("claimed_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_inbound_events"),
        sa.UniqueConstraint(
            "platform",
            "chat_id",
            "message_id",
            name="uq_inbound_events_platform_chat_id_message_id",
        ),
    )
    op.create_table(
        "team_sequences",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("name", sa.String(32), nullable=False),
        sa.Column("value", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_team_sequences_team_id_teams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_team_sequences"),
        sa.UniqueConstraint("team_id", "name", name="uq_team_sequences_team_id_name"),
    )
    op.create_index("ix_team_sequences_team_id", "team_sequences", ["team_id"])
    op.create_table(
        "tasks",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(2000), nullable=False),
        sa.Column("description", sa.String(10000), nullable=True),
        sa.Column("assignee_id", UUID, nullable=True),
        sa.Column("due_at", UtcDateTime(), nullable=True),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.String(200), nullable=True),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.CheckConstraint("status IN ('open', 'done')", name="ck_tasks_status_allowed"),
        sa.ForeignKeyConstraint(
            ["assignee_id"], ["users.id"], name="fk_tasks_assignee_id_users", ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name="fk_tasks_created_by_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_tasks_team_id_teams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_tasks"),
        sa.UniqueConstraint("team_id", "number", name="uq_tasks_team_id_number"),
    )
    op.create_index("ix_tasks_assignee_id", "tasks", ["assignee_id"])
    op.create_index("ix_tasks_created_by", "tasks", ["created_by"])
    op.create_index("ix_tasks_team_id", "tasks", ["team_id"])
    op.create_index("ix_tasks_team_id_status", "tasks", ["team_id", "status"])
    op.create_table(
        "ideas",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("author_id", UUID, nullable=False),
        sa.Column("text", sa.String(4000), nullable=False),
        sa.Column("text_norm", sa.String(4000), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("source_message_id", sa.String(200), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.CheckConstraint("status IN ('active', 'archived')", name="ck_ideas_status_allowed"),
        sa.ForeignKeyConstraint(
            ["author_id"], ["users.id"], name="fk_ideas_author_id_users", ondelete="RESTRICT"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_ideas_team_id_teams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_ideas"),
    )
    op.create_index("ix_ideas_author_id", "ideas", ["author_id"])
    op.create_index("ix_ideas_team_id", "ideas", ["team_id"])
    op.create_index("ix_ideas_team_id_status", "ideas", ["team_id", "status"])
    op.create_table(
        "idea_tags",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("idea_id", UUID, nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("tag_norm", sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(
            ["idea_id"], ["ideas.id"], name="fk_idea_tags_idea_id_ideas", ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_idea_tags_team_id_teams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_idea_tags"),
        sa.UniqueConstraint("idea_id", "tag_norm", name="uq_idea_tags_idea_id_tag_norm"),
    )
    op.create_index("ix_idea_tags_idea_id", "idea_tags", ["idea_id"])
    op.create_index("ix_idea_tags_team_id", "idea_tags", ["team_id"])
    op.create_index("ix_idea_tags_team_id_tag_norm", "idea_tags", ["team_id", "tag_norm"])
    op.create_table(
        "access_codes",
        sa.Column("id", UUID, nullable=False),
        sa.Column("team_id", UUID, nullable=False),
        sa.Column("purpose", sa.String(16), nullable=False),
        sa.Column("code_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", UtcDateTime(), nullable=False),
        sa.Column("used_at", UtcDateTime(), nullable=True),
        sa.Column("created_by", UUID, nullable=False),
        sa.Column("target_user_id", UUID, nullable=True),
        sa.Column("role", sa.String(16), nullable=True),
        sa.CheckConstraint(
            "purpose IN ('link', 'bind', 'invite')",
            name="ck_access_codes_purpose_allowed",
        ),
        sa.CheckConstraint(
            "role IS NULL OR role IN ('owner', 'admin', 'member', 'viewer')",
            name="ck_access_codes_role_allowed",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"],
            ["users.id"],
            name="fk_access_codes_created_by_users",
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["target_user_id"],
            ["users.id"],
            name="fk_access_codes_target_user_id_users",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["team_id"], ["teams.id"], name="fk_access_codes_team_id_teams", ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name="pk_access_codes"),
        sa.UniqueConstraint("code_hash", name="uq_access_codes_code_hash"),
    )
    op.create_index("ix_access_codes_created_by", "access_codes", ["created_by"])
    op.create_index("ix_access_codes_target_user_id", "access_codes", ["target_user_id"])
    op.create_index("ix_access_codes_team_id", "access_codes", ["team_id"])
    op.create_index(
        "ix_access_codes_team_id_purpose",
        "access_codes",
        ["team_id", "purpose"],
    )


def downgrade() -> None:
    """Удаляет таблицы M1 в порядке внешних ключей."""
    op.drop_table("access_codes")
    op.drop_table("idea_tags")
    op.drop_table("ideas")
    op.drop_table("tasks")
    op.drop_table("team_sequences")
    op.drop_table("inbound_events")

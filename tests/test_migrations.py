"""Проверка миграции с нуля и совпадения схемы с metadata."""

import os
from pathlib import Path

from alembic.config import Config
from pytest import MonkeyPatch
from sqlalchemy import create_engine, inspect
from sqlalchemy.engine import make_url

from alembic import command

POSTGRES_URL = os.environ.get("DATABASE_URL", "")
MIGRATION_TARGETS = ["sqlite"]
if POSTGRES_URL and make_url(POSTGRES_URL).get_backend_name() == "postgresql":
    MIGRATION_TARGETS.append("postgresql")


def test_upgrade_head_and_alembic_check_on_configured_databases(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    root = Path(__file__).resolve().parents[1]
    for target in MIGRATION_TARGETS:
        database_path = tmp_path / f"migration-{target}.db"
        async_url = (
            POSTGRES_URL if target == "postgresql" else f"sqlite+aiosqlite:///{database_path}"
        )
        monkeypatch.setenv("DATABASE_URL", async_url)
        config = Config(root / "alembic.ini")
        config.set_main_option("script_location", str(root / "alembic"))
        config.set_main_option("sqlalchemy.url", async_url.replace("%", "%%"))

        command.downgrade(config, "base")
        command.upgrade(config, "head")
        command.check(config)

        command.downgrade(config, "0001_initial")
        command.upgrade(config, "head")
        command.downgrade(config, "base")
        command.upgrade(config, "0001_initial")
        command.upgrade(config, "head")
        command.check(config)

        if target == "sqlite":
            engine = create_engine(f"sqlite:///{database_path}")
            assert set(inspect(engine).get_table_names()) >= {
                "alembic_version",
                "teams",
                "users",
                "user_identities",
                "memberships",
                "chats",
                "messages",
                "inbound_events",
                "team_sequences",
                "tasks",
                "ideas",
                "idea_tags",
                "access_codes",
            }
            engine.dispose()

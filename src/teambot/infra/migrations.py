"""Программный запуск Alembic перед стартом процесса M0."""

from pathlib import Path

from alembic.config import Config

from alembic import command
from teambot.adapters.storage.dialect import ensure_database_parent


def upgrade_database(database_url: str, project_root: Path | None = None) -> None:
    """Применяет все миграции к базе из ``DATABASE_URL``.

    Аргументы:
        database_url: Единственный источник выбора СУБД.
        project_root: Корень проекта; по умолчанию вычисляется по модулю.
    """
    root = project_root or Path(__file__).resolve().parents[3]
    ensure_database_parent(database_url)
    config = Config(root / "alembic.ini")
    config.set_main_option("script_location", str(root / "alembic"))
    config.set_main_option("sqlalchemy.url", database_url.replace("%", "%%"))
    command.upgrade(config, "head")

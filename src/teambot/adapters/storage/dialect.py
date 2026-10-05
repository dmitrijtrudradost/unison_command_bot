"""Диалектные особенности SQLite и PostgreSQL.

Модуль является единственным местом прикладного кода, где допустимы
диалектные ветвления и служебные SQL-команды (DB-2, DB-4, DB-8, DB-9).
"""

import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import MetaData, Table, event
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.engine import Connection
from sqlalchemy.engine.interfaces import DBAPIConnection, Dialect
from sqlalchemy.engine.url import make_url
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine, create_async_engine
from sqlalchemy.pool import ConnectionPoolEntry
from sqlalchemy.sql.dml import Insert
from sqlalchemy.types import DateTime, TypeDecorator

NAMING_CONVENTION = {
    "ix": "ix_%(table_name)s_%(column_0_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}

metadata = MetaData(naming_convention=NAMING_CONVENTION)


def ensure_database_parent(database_url: str) -> None:
    """Создаёт родительский каталог файловой SQLite перед подключением."""
    url = make_url(database_url)
    if url.get_backend_name() != "sqlite" or not url.database or url.database == ":memory:":
        return
    Path(url.database).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def sqlite_integrity_check(connection: sqlite3.Connection) -> bool:
    """Выполняет разрешённую диалектную проверку целостности SQLite."""
    row = connection.execute("PRAGMA integrity_check").fetchone()
    return bool(row == ("ok",))


async def read_sqlite_pragmas(connection: AsyncConnection) -> tuple[int, str, int]:
    """Читает настройки соединения для readiness и контрактных тестов."""
    foreign_keys = (await connection.exec_driver_sql("PRAGMA foreign_keys")).scalar_one()
    journal_mode = (await connection.exec_driver_sql("PRAGMA journal_mode")).scalar_one()
    busy_timeout = (await connection.exec_driver_sql("PRAGMA busy_timeout")).scalar_one()
    return int(foreign_keys), str(journal_mode), int(busy_timeout)


class UtcDateTime(TypeDecorator[datetime]):
    """Хранит datetime в UTC и всегда возвращает aware-значение.

    На вход принимается только aware-время. SQLite удаляет сведения о часовом
    поясе, поэтому при чтении UTC назначается явно; PostgreSQL возвращаемое
    значение дополнительно нормализуется в UTC.
    """

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Проверяет и нормализует записываемое время."""
        del dialect
        if value is None:
            return None
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("UtcDateTime принимает только aware datetime")
        return value.astimezone(UTC)

    def process_result_value(self, value: datetime | None, dialect: Dialect) -> datetime | None:
        """Восстанавливает UTC timezone после чтения из любого диалекта."""
        del dialect
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)


def create_engine(database_url: str, sqlite_busy_timeout_ms: int = 5000) -> AsyncEngine:
    """Создаёт async engine и настраивает каждое SQLite-соединение.

    Аргументы:
        database_url: URL SQLAlchemy с async-драйвером.
        sqlite_busy_timeout_ms: Максимальное ожидание блокировки SQLite.

    Возвращает:
        Настроенный асинхронный engine без открытого соединения.
    """
    ensure_database_parent(database_url)
    engine = create_async_engine(database_url, pool_pre_ping=True)
    if engine.url.get_backend_name() == "sqlite":

        @event.listens_for(engine.sync_engine, "connect")
        def configure_sqlite(
            dbapi_connection: DBAPIConnection,
            _connection_record: ConnectionPoolEntry,
        ) -> None:
            # PRAGMA должны выполняться для каждого соединения: foreign_keys
            # не является настройкой файла, а busy_timeout относится к handle.
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute(f"PRAGMA busy_timeout={int(sqlite_busy_timeout_ms)}")
            finally:
                cursor.close()

    return engine


def portable_upsert(
    connection: Connection,
    table: Table,
    values: Mapping[str, Any],
    conflict_columns: tuple[str, ...],
    update_values: Mapping[str, Any] | None = None,
) -> Insert:
    """Строит переносимый INSERT ON CONFLICT для текущего соединения.

    Если ``update_values`` не передан, конфликт безопасно игнорируется.
    Поддерживаются только два диалекта, разрешённых этапом M0.
    """
    dialect_name = connection.dialect.name
    statement: Insert
    if dialect_name == "sqlite":
        statement = sqlite_insert(table).values(**values)
    elif dialect_name == "postgresql":
        statement = postgresql_insert(table).values(**values)
    else:
        raise ValueError(f"Неподдерживаемый диалект: {dialect_name}")

    if update_values is None:
        return statement.on_conflict_do_nothing(index_elements=list(conflict_columns))
    return statement.on_conflict_do_update(
        index_elements=list(conflict_columns),
        set_=dict(update_values),
    )

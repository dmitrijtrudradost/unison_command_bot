"""Контрактные проверки диалектного слоя DB-2, DB-4, DB-8 и DB-9."""

from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pytest
from sqlalchemy import Column, Integer, MetaData, String, Table, select
from sqlalchemy.engine import Connection
from sqlalchemy.exc import StatementError
from sqlalchemy.sql.dml import Insert

from teambot.adapters.storage.dialect import (
    UtcDateTime,
    create_engine,
    portable_upsert,
    read_sqlite_pragmas,
)


async def test_sqlite_connection_pragmas(tmp_path: Path) -> None:
    engine = create_engine(
        f"sqlite+aiosqlite:///{tmp_path / 'pragmas.db'}",
        sqlite_busy_timeout_ms=4321,
    )
    async with engine.connect() as connection:
        foreign_keys, journal_mode, busy_timeout = await read_sqlite_pragmas(connection)
    assert foreign_keys == 1
    assert journal_mode.casefold() == "wal"
    assert busy_timeout == 4321
    await engine.dispose()


async def test_utc_datetime_round_trip_and_rejects_naive(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'utc.db'}")
    local_metadata = MetaData()
    records = Table(
        "records",
        local_metadata,
        Column("id", Integer, primary_key=True),
        Column("created_at", UtcDateTime(), nullable=False),
    )
    async with engine.begin() as connection:
        await connection.run_sync(local_metadata.create_all)
        source = datetime(2026, 1, 2, 6, tzinfo=timezone(timedelta(hours=3)))
        await connection.execute(records.insert().values(id=1, created_at=source))
        restored = await connection.scalar(select(records.c.created_at))

        with pytest.raises(StatementError, match="aware"):
            await connection.execute(records.insert().values(id=2, created_at=datetime(2026, 1, 2)))

    assert restored == datetime(2026, 1, 2, 3, tzinfo=UTC)
    assert restored is not None and restored.tzinfo is UTC
    await engine.dispose()


async def test_portable_upsert_updates_on_conflict(tmp_path: Path) -> None:
    engine = create_engine(f"sqlite+aiosqlite:///{tmp_path / 'upsert.db'}")
    local_metadata = MetaData()
    records = Table(
        "records",
        local_metadata,
        Column("key", String(20), primary_key=True),
        Column("value", String(20), nullable=False),
    )
    async with engine.begin() as connection:
        await connection.run_sync(local_metadata.create_all)

        def statement(sync_connection: Connection, value: str) -> Insert:
            return portable_upsert(
                sync_connection,
                records,
                {"key": "same", "value": value},
                ("key",),
                {"value": value},
            )

        first = await connection.run_sync(statement, "one")
        await connection.execute(first)
        second = await connection.run_sync(statement, "two")
        await connection.execute(second)
        value = await connection.scalar(select(records.c.value))

    assert value == "two"
    await engine.dispose()

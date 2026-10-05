"""Проверка согласованного SQLite backup и восстановления DB-15."""

from pathlib import Path

from sqlalchemy import Column, Integer, MetaData, Table, func, select

from teambot.adapters.storage.backup import SqliteBackup
from teambot.adapters.storage.dialect import create_engine


async def test_backup_can_be_verified_and_restored(tmp_path: Path) -> None:
    source = tmp_path / "source.db"
    destination = tmp_path / "backups" / "copy.db"
    metadata = MetaData()
    records = Table(
        "records",
        metadata,
        Column("id", Integer, primary_key=True),
    )
    engine = create_engine(f"sqlite+aiosqlite:///{source}")
    async with engine.begin() as connection:
        await connection.run_sync(metadata.create_all)
        await connection.execute(records.insert().values(id=1))

    backup = SqliteBackup(f"sqlite+aiosqlite:///{source}")
    assert await backup.create(destination) == destination.resolve()
    assert await backup.verify(destination)

    restored_engine = create_engine(f"sqlite+aiosqlite:///{destination}")
    async with restored_engine.connect() as connection:
        assert await connection.scalar(select(func.count()).select_from(records)) == 1
    await restored_engine.dispose()
    await engine.dispose()

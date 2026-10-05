"""Согласованная резервная копия SQLite через backup API.

Копирование файла работающей БД запрещено DB-15: WAL может содержать ещё не
слитые страницы. ``sqlite3.Connection.backup`` создаёт целостный снимок.
"""

import asyncio
import sqlite3
from pathlib import Path

from sqlalchemy.engine import make_url

from teambot.adapters.storage.dialect import sqlite_integrity_check


class SqliteBackup:
    """Создаёт и проверяет резервные копии файловой SQLite-базы."""

    def __init__(self, database_url: str) -> None:
        """Извлекает путь SQLite из URL и отклоняет другие диалекты."""
        url = make_url(database_url)
        if url.get_backend_name() != "sqlite" or not url.database:
            raise ValueError("Резервное копирование M0 поддерживает только файловую SQLite")
        if url.database == ":memory:":
            raise ValueError("In-memory SQLite нельзя резервировать по пути")
        self._source = Path(url.database).resolve()

    async def create(self, destination: Path) -> Path:
        """Создаёт согласованную копию без блокировки event loop."""
        target = await asyncio.to_thread(destination.resolve)
        if target == self._source:
            raise ValueError("Путь резервной копии должен отличаться от исходного")
        await asyncio.to_thread(self._backup_sync, self._source, target)
        return target

    async def verify(self, backup_path: Path) -> bool:
        """Проверяет структурную целостность созданной копии."""
        return await asyncio.to_thread(self._verify_sync, backup_path)

    @staticmethod
    def _backup_sync(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(source) as source_connection:
            with sqlite3.connect(destination) as destination_connection:
                source_connection.backup(destination_connection)

    @staticmethod
    def _verify_sync(path: Path) -> bool:
        with sqlite3.connect(path) as connection:
            return sqlite_integrity_check(connection)

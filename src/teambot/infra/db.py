"""Жизненный цикл подключения к базе данных M0.

Инфраструктура владеет engine и фабрикой сессий, а прикладной доступ к данным
остаётся в репозиториях ``adapters/storage`` (DB-1).
"""

from dataclasses import dataclass

from sqlalchemy import literal, select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from teambot.adapters.storage.dialect import create_engine


@dataclass(slots=True)
class Database:
    """Объединяет engine, сессии и безопасные операции жизненного цикла."""

    engine: AsyncEngine
    sessions: async_sessionmaker[AsyncSession]

    @classmethod
    def create(cls, database_url: str, sqlite_busy_timeout_ms: int = 5000) -> "Database":
        """Создаёт ещё не подключённый объект базы по URL из конфигурации."""
        engine = create_engine(database_url, sqlite_busy_timeout_ms)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        return cls(engine=engine, sessions=sessions)

    async def ready(self) -> bool:
        """Проверяет соединение переносимым выражением SQLAlchemy."""
        async with self.engine.connect() as connection:
            result = await connection.scalar(select(literal(1)))
        return result == 1

    async def close(self) -> None:
        """Освобождает пул соединений при остановке приложения."""
        await self.engine.dispose()

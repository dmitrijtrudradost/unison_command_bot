"""Базовый репозиторий с обязательной изоляцией команд.

Все репозитории командных таблиц наследуются от этого класса. Единственная
точка построения запросов автоматически добавляет предикат ``team_id``
(DB-1 и DB-13).
"""

from collections.abc import Sequence
from typing import cast

from pydantic import BaseModel
from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from teambot.core.models import TeamContext


class TeamScopedRepository[ModelT: DeclarativeBase, ValuesT: BaseModel]:
    """Предоставляет безопасные операции над одной командной моделью."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        model: type[ModelT],
        values_type: type[ValuesT],
    ) -> None:
        """Сохраняет фабрику сессий, ORM-модель и входную схему Pydantic."""
        if "team_id" not in model.__table__.c:
            raise ValueError("TeamScopedRepository требует колонку team_id")
        self._session_factory = session_factory
        self._model = model
        self._values_type = values_type

    def scoped_select(self, ctx: TeamContext) -> Select[tuple[ModelT]]:
        """Строит SELECT, всегда ограниченный командой из контекста."""
        statement = select(self._model).where(self._model.__table__.c.team_id == ctx.team_id)
        return cast(Select[tuple[ModelT]], statement)

    async def list_all(self, ctx: TeamContext) -> Sequence[ModelT]:
        """Возвращает строки только текущей команды.

        Аргументы:
            ctx: Обязательный контекст команды и действующего пользователя.

        Возвращает:
            Последовательность ORM-объектов без текстовой SQL-сортировки.
        """
        async with self._session_factory() as session:
            result = await session.scalars(self.scoped_select(ctx))
            return cast(Sequence[ModelT], result.all())

    async def add(self, ctx: TeamContext, values: ValuesT) -> ModelT:
        """Добавляет проверенную строку, принудительно подставляя команду."""
        if not isinstance(values, self._values_type):
            raise TypeError(f"Ожидались значения {self._values_type.__name__}")
        safe_values = values.model_dump(mode="python")
        safe_values["team_id"] = ctx.team_id
        instance = self._model(**safe_values)
        async with self._session_factory() as session, session.begin():
            session.add(instance)
        return instance

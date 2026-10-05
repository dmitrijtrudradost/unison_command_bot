"""Сервис задач этапа M1.

Сервис реализует валидацию и RBAC поверх единственного разрешённого контракта
``TaskStore``. Номер задачи выдаёт хранилище атомарно и остаётся постоянным
внутри команды (DB-9).
"""

from teambot.core.errors import NotFoundError, PermissionDenied, ValidationError
from teambot.core.models import (
    NewTask,
    Role,
    Task,
    TaskFilter,
    TaskPatch,
    TaskStatus,
    TeamContext,
    role_allows,
)
from teambot.core.ports import TaskStore

MAX_TASK_TITLE_LENGTH = 2000


class TaskService:
    """Управляет задачами команды через порт хранилища."""

    def __init__(self, store: TaskStore) -> None:
        """Создаёт сервис.

        Аргументы:
            store: хранилище, самостоятельно фильтрующее данные по команде.
        """
        self._store = store

    async def add(self, ctx: TeamContext, title: str) -> Task:
        """Создаёт задачу от имени текущего пользователя.

        Исключения:
            PermissionDenied: роль ниже ``member``.
            ValidationError: заголовок пуст или слишком длинный.
        """
        _require_role(ctx, Role.MEMBER)
        clean_title = _validate_title(title)
        return await self._store.create(
            ctx,
            NewTask(title=clean_title, assignee_id=ctx.user_id),
        )

    async def list(
        self,
        ctx: TeamContext,
        status: TaskStatus | None = TaskStatus.OPEN,
        *,
        only_mine: bool = False,
    ) -> list[Task]:
        """Возвращает задачи команды с фильтром статуса и исполнителя."""
        _require_role(ctx, Role.MEMBER if only_mine else Role.VIEWER)
        assignee_id = ctx.user_id if only_mine else None
        return await self._store.list(ctx, TaskFilter(status=status, assignee_id=assignee_id))

    async def complete(self, ctx: TeamContext, number: int) -> Task:
        """Завершает задачу по её устойчивому номеру в команде."""
        _require_role(ctx, Role.MEMBER)
        task = await self._by_number(ctx, number)
        return await self._store.update(ctx, task.id, TaskPatch(status=TaskStatus.DONE))

    async def edit(self, ctx: TeamContext, number: int, title: str) -> Task:
        """Изменяет заголовок задачи по устойчивому номеру."""
        _require_role(ctx, Role.MEMBER)
        task = await self._by_number(ctx, number)
        return await self._store.update(
            ctx,
            task.id,
            TaskPatch(title=_validate_title(title)),
        )

    async def _by_number(self, ctx: TeamContext, number: int) -> Task:
        if number < 1:
            raise ValidationError("Номер задачи должен быть положительным")
        task = await self._store.get_by_number(ctx, number)
        if task is None:
            raise NotFoundError("Задача с таким номером не найдена")
        return task


def _require_role(ctx: TeamContext, required: Role) -> None:
    if not role_allows(ctx.role, required):
        raise PermissionDenied


def _validate_title(title: str) -> str:
    clean_title = title.strip()
    if not clean_title or len(clean_title) > MAX_TASK_TITLE_LENGTH:
        raise ValidationError("Недопустимая длина текста задачи")
    return clean_title

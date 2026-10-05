"""Юнит-тесты сервисов задач и идей на фейковых портах."""

from dataclasses import replace
from uuid import UUID, uuid4

import pytest

from teambot.core.errors import PermissionDenied, ValidationError
from teambot.core.models import (
    Idea,
    IdeaFilter,
    IdeaMatch,
    NewIdea,
    NewTask,
    Role,
    Task,
    TaskFilter,
    TaskPatch,
    TaskStatus,
    TeamContext,
)
from teambot.core.services.ideas import IdeaService
from teambot.core.services.tasks import TaskService


class FakeTaskStore:
    def __init__(self) -> None:
        self.tasks: list[Task] = []

    async def create(self, ctx: TeamContext, task: NewTask) -> Task:
        number = (
            max((item.number for item in self.tasks if item.team_id == ctx.team_id), default=0) + 1
        )
        created = Task(
            id=uuid4(),
            team_id=ctx.team_id,
            number=number,
            title=task.title,
            status=TaskStatus.OPEN,
            created_by=ctx.user_id,
            assignee_id=task.assignee_id,
        )
        self.tasks.append(created)
        return created

    async def update(self, ctx: TeamContext, task_id: UUID, patch: TaskPatch) -> Task:
        current = next(task for task in self.tasks if task.id == task_id)
        updated = replace(
            current,
            title=patch.title if patch.title is not None else current.title,
            status=patch.status if patch.status is not None else current.status,
        )
        self.tasks[self.tasks.index(current)] = updated
        return updated

    async def list(self, ctx: TeamContext, filt: TaskFilter) -> list[Task]:
        return [
            task
            for task in self.tasks
            if task.team_id == ctx.team_id
            and (filt.status is None or task.status is filt.status)
            and (filt.assignee_id is None or task.assignee_id == filt.assignee_id)
        ]

    async def get_by_number(self, ctx: TeamContext, number: int) -> Task | None:
        return next(
            (task for task in self.tasks if task.team_id == ctx.team_id and task.number == number),
            None,
        )


class FakeIdeaStore:
    def __init__(self) -> None:
        self.ideas: list[Idea] = []

    async def create(self, ctx: TeamContext, idea: NewIdea) -> Idea:
        created = Idea(
            id=uuid4(),
            team_id=ctx.team_id,
            author_id=idea.author_id,
            text=idea.text,
            text_norm=idea.text_norm,
            tags=idea.tags,
            source_message_id=idea.source_message_id,
        )
        self.ideas.append(created)
        return created

    async def list(self, ctx: TeamContext, filt: IdeaFilter) -> list[Idea]:
        return [
            idea
            for idea in self.ideas
            if idea.team_id == ctx.team_id
            and (filt.query_norm is None or filt.query_norm in idea.text_norm)
        ]


class FakeIdeaIndex:
    def __init__(self) -> None:
        self.indexed: list[tuple[TeamContext, Idea]] = []

    async def index(self, ctx: TeamContext, idea: Idea) -> None:
        self.indexed.append((ctx, idea))

    async def find_similar(
        self,
        ctx: TeamContext,
        text: str,
        limit: int = 5,
    ) -> list[IdeaMatch]:
        return [
            IdeaMatch(idea, 1.0)
            for indexed_ctx, idea in self.indexed
            if indexed_ctx.team_id == ctx.team_id and text in idea.text_norm
        ][:limit]


async def test_task_service_validates_rbac_and_updates_by_number() -> None:
    store = FakeTaskStore()
    service = TaskService(store)
    member = TeamContext(uuid4(), uuid4(), Role.MEMBER)
    viewer = TeamContext(member.team_id, uuid4(), Role.VIEWER)

    task = await service.add(member, "  Проверить отчёт  ")
    assert task.title == "Проверить отчёт"
    assert task.assignee_id == member.user_id

    edited = await service.edit(member, 1, "Исправить отчёт")
    assert edited.title == "Исправить отчёт"
    completed = await service.complete(member, 1)
    assert completed.status is TaskStatus.DONE
    assert completed.number == 1

    with pytest.raises(PermissionDenied):
        await service.add(viewer, "Нельзя")
    with pytest.raises(ValidationError):
        await service.add(member, " ")


async def test_idea_service_normalizes_indexes_and_checks_role() -> None:
    store = FakeIdeaStore()
    index = FakeIdeaIndex()
    service = IdeaService(store, index)
    member = TeamContext(uuid4(), uuid4(), Role.MEMBER)

    idea = await service.add(member, "  Новый   БОТ #Продукт  ", source_message_id="42")

    assert idea.text == "Новый БОТ #Продукт"
    assert idea.text_norm == "новый бот #продукт"
    assert idea.tags == ("продукт",)
    assert index.indexed == [(member, idea)]
    assert await service.list(member, "НОВЫЙ") == [idea]

    viewer = TeamContext(member.team_id, uuid4(), Role.VIEWER)
    with pytest.raises(PermissionDenied):
        await service.add(viewer, "Идея")

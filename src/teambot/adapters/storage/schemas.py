"""Проверяемые входные данные репозиториев M0.

Модели Pydantic проверяют типы и ограничения до обращения к SQLAlchemy, как
требует DB-6. Они относятся к адаптеру хранения и не попадают в доменное ядро.
"""

from datetime import datetime
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field

from teambot.core.events import JsonValue
from teambot.core.models import AccessCodePurpose, IdeaStatus, Role, TaskStatus


class RepositoryValues(BaseModel):
    """Запрещает неописанные поля во входных данных репозитория."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class MembershipValues(RepositoryValues):
    """Проверяет данные нового членства в команде."""

    user_id: UUID
    role: Role


class ChatValues(RepositoryValues):
    """Проверяет данные нового командного чата."""

    platform: str = Field(min_length=1, max_length=32)
    chat_id: str = Field(min_length=1, max_length=200)
    title: str | None = Field(default=None, max_length=300)


class MessageValues(RepositoryValues):
    """Проверяет данные нового сообщения до записи в БД."""

    chat_id: UUID
    platform: str = Field(min_length=1, max_length=32)
    message_id: str = Field(min_length=1, max_length=200)
    user_id: UUID | None = None
    text: str | None = Field(default=None, max_length=10000)
    ts: AwareDatetime
    raw: dict[str, JsonValue]

    def as_repository_values(self) -> dict[str, object]:
        """Возвращает значения с обычным ``datetime`` для SQLAlchemy."""
        values = self.model_dump(mode="python")
        # AwareDatetime является аннотацией Pydantic, а фактическое значение —
        # стандартный datetime; явная проверка сохраняет точную типизацию.
        if not isinstance(values["ts"], datetime):
            raise TypeError("ts должен быть datetime")
        return values


class TeamSequenceValues(RepositoryValues):
    """Проверяет данные счётчика командной последовательности."""

    name: str = Field(min_length=1, max_length=32)
    value: int = Field(ge=0)


class TaskValues(RepositoryValues):
    """Проверяет данные новой задачи до записи в БД."""

    number: int = Field(ge=1)
    title: str = Field(min_length=1, max_length=2000)
    description: str | None = Field(default=None, max_length=10000)
    assignee_id: UUID | None = None
    due_at: AwareDatetime | None = None
    status: TaskStatus
    source_type: str = Field(min_length=1, max_length=32)
    source_id: str | None = Field(default=None, max_length=200)
    created_by: UUID
    created_at: AwareDatetime


class IdeaValues(RepositoryValues):
    """Проверяет данные новой идеи до записи в БД."""

    author_id: UUID
    text: str = Field(min_length=1, max_length=4000)
    text_norm: str = Field(min_length=1, max_length=4000)
    status: IdeaStatus
    source_message_id: str | None = Field(default=None, max_length=200)
    created_at: AwareDatetime


class IdeaTagValues(RepositoryValues):
    """Проверяет данные тега идеи."""

    idea_id: UUID
    tag: str = Field(min_length=1, max_length=64)
    tag_norm: str = Field(min_length=1, max_length=64)


class AccessCodeValues(RepositoryValues):
    """Проверяет данные одноразового кода до записи хеша."""

    purpose: AccessCodePurpose
    code_hash: str = Field(min_length=64, max_length=64)
    expires_at: AwareDatetime
    used_at: AwareDatetime | None = None
    created_by: UUID
    target_user_id: UUID | None = None
    role: Role | None = None

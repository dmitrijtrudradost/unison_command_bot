"""Доменные типы ядра Team Bot.

Модуль содержит независимые от хранилища модели этапов M0–M1. Типы передаются
между оркестратором, сервисами и портами согласно разделам 6, 8 и 9
``ARCHITECTURE.md``. Здесь намеренно нет ORM-моделей и платформенных значений.
"""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path
from typing import Literal
from uuid import UUID

from teambot.core.events import JsonValue


class Role(StrEnum):
    """Перечисляет роли участника команды от максимальной к минимальной."""

    OWNER = "owner"
    ADMIN = "admin"
    MEMBER = "member"
    VIEWER = "viewer"


ROLE_LEVEL: dict[Role, int] = {
    Role.VIEWER: 0,
    Role.MEMBER: 1,
    Role.ADMIN: 2,
    Role.OWNER: 3,
}


def role_allows(actual: Role, required: Role) -> bool:
    """Проверяет, включает ли фактическая роль требуемые права.

    Аргументы:
        actual: роль действующего участника.
        required: минимальная роль операции.

    Возвращает:
        ``True``, если операция разрешена иерархией ролей.
    """
    return ROLE_LEVEL[actual] >= ROLE_LEVEL[required]


class TaskStatus(StrEnum):
    """Перечисляет состояния внутренней задачи M1."""

    OPEN = "open"
    DONE = "done"


class IdeaStatus(StrEnum):
    """Перечисляет состояния идеи на этапе M1."""

    ACTIVE = "active"
    ARCHIVED = "archived"


class AccessCodePurpose(StrEnum):
    """Определяет допустимое назначение одноразового кода."""

    LINK = "link"
    BIND = "bind"
    INVITE = "invite"


@dataclass(frozen=True, slots=True)
class TeamContext:
    """Задаёт обязательную область команды и действующего пользователя.

    Атрибуты:
        team_id: идентификатор рабочей группы.
        user_id: идентификатор действующего пользователя.
        role: роль пользователя именно в указанной группе.
    """

    team_id: UUID
    user_id: UUID
    role: Role


@dataclass(frozen=True, slots=True)
class CommandSpec:
    """Описывает slash-команду, её права, синтаксис и обработчик ядра.

    Атрибуты:
        syntax_ru: краткая форма вызова для справки.
        usage_ru: готовый пример, который можно отправить в чат.
    """

    name: str
    description_ru: str
    min_role: Role | None
    stage: str
    handler: str
    syntax_ru: str
    usage_ru: str


@dataclass(frozen=True, slots=True)
class User:
    """Представляет глобального пользователя без привязки к каналу."""

    id: UUID
    display_name: str


@dataclass(frozen=True, slots=True)
class ExternalIdentity:
    """Представляет внешний аккаунт в нейтральных терминах.

    Атрибут ``source`` является непрозрачным идентификатором адаптера. Ядро не
    перечисляет и не интерпретирует возможные значения.
    """

    source: str
    external_user_id: str


@dataclass(frozen=True, slots=True)
class ChatRef:
    """Представляет внешний чат без знания о конкретном канале."""

    source: str
    external_chat_id: str


@dataclass(frozen=True, slots=True)
class BoundChat:
    """Описывает привязанный к команде внешний чат."""

    ref: ChatRef
    title: str | None = None


@dataclass(frozen=True, slots=True)
class Team:
    """Представляет рабочую группу."""

    id: UUID
    name: str


@dataclass(frozen=True, slots=True)
class TeamMember:
    """Представляет участника команды для просмотра и управления ролями."""

    user_id: UUID
    display_name: str
    role: Role


@dataclass(frozen=True, slots=True)
class NewAccessCode:
    """Содержит параметры создаваемого одноразового кода."""

    id: UUID
    code: str
    purpose: AccessCodePurpose
    expires_at: datetime
    role: Role | None = None
    target_user_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class AccessCode:
    """Представляет проверенный одноразовый код из хранилища."""

    id: UUID
    code: str
    purpose: AccessCodePurpose
    expires_at: datetime
    team_id: UUID | None = None
    role: Role | None = None
    target_user_id: UUID | None = None
    used_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class EventKey:
    """Задаёт минимальный ключ идемпотентности входящего события."""

    source: str
    chat_id: str
    message_id: str


@dataclass(frozen=True, slots=True)
class RawRequest:
    """Хранит нейтральное представление входящего HTTP-запроса коннектора."""

    headers: dict[str, str]
    body: bytes
    query: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class MeetingRef:
    """Ссылается на встречу во внешней системе без раскрытия её API."""

    external_id: str


@dataclass(frozen=True, slots=True)
class MeetingArtifacts:
    """Объединяет локальные артефакты встречи, полученные коннектором."""

    media_paths: list[Path] = field(default_factory=list)
    transcript_path: Path | None = None
    chat_path: Path | None = None
    participants: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Segment:
    """Описывает распознанный временной сегмент речи."""

    start_sec: float
    end_sec: float
    text: str


@dataclass(frozen=True, slots=True)
class SpeakerTurn:
    """Описывает интервал речи одного обезличенного говорящего."""

    start_sec: float
    end_sec: float
    speaker_label: str


@dataclass(frozen=True, slots=True)
class LLMRequest:
    """Описывает запрос к маршрутизатору языковых моделей."""

    data_class: str
    prompt: str
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class LLMResponse:
    """Описывает нормализованный ответ языковой модели."""

    content: str
    provider: str
    model: str


@dataclass(frozen=True, slots=True)
class NewTask:
    """Содержит проверенные данные для создания задачи."""

    title: str
    description: str | None = None
    assignee_id: UUID | None = None
    due_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Task:
    """Представляет внутреннюю задачу команды.

    ``number`` — устойчивый номер внутри команды. Он не зависит от текущего
    фильтра списка и используется командами ``/done`` и ``/edit``.
    """

    id: UUID
    team_id: UUID
    number: int
    title: str
    status: TaskStatus
    created_by: UUID
    description: str | None = None
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class TaskPatch:
    """Содержит изменяемые поля задачи; ``None`` означает отсутствие изменения."""

    title: str | None = None
    description: str | None = None
    assignee_id: UUID | None = None
    due_at: datetime | None = None
    status: TaskStatus | None = None


@dataclass(frozen=True, slots=True)
class TaskFilter:
    """Задаёт переносимые критерии выборки задач."""

    status: TaskStatus | None = None
    assignee_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class NewIdea:
    """Содержит проверенные данные для создания идеи."""

    text: str
    text_norm: str
    author_id: UUID
    source_message_id: str | None = None
    tags: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IdeaFilter:
    """Задаёт переносимые критерии списка идей."""

    status: IdeaStatus = IdeaStatus.ACTIVE
    query_norm: str | None = None
    tags_norm: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExternalRef:
    """Ссылается на задачу во внешнем трекере."""

    tracker: str
    external_id: str


@dataclass(frozen=True, slots=True)
class ExternalChange:
    """Описывает входящее изменение задачи из внешнего трекера."""

    ref: ExternalRef
    changed_at: datetime
    fields: dict[str, JsonValue]


@dataclass(frozen=True, slots=True)
class Idea:
    """Представляет идею команды для хранения и индексирования."""

    id: UUID
    team_id: UUID
    author_id: UUID
    text: str
    text_norm: str
    status: IdeaStatus = IdeaStatus.ACTIVE
    tags: tuple[str, ...] = ()
    source_message_id: str | None = None
    created_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class IdeaMatch:
    """Представляет найденную похожую идею и оценку близости."""

    idea: Idea
    score: float


@dataclass(frozen=True, slots=True)
class RecoverableJob:
    """Описывает активное задание, восстанавливаемое при запуске процесса."""

    id: UUID
    name: str
    run_at: datetime
    payload: dict[str, JsonValue]
    schedule_kind: Literal["once"] = "once"

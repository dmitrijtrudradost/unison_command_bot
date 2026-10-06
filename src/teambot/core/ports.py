"""Порты гексагональной архитектуры Team Bot.

Контракты соответствуют разделу 6 ARCHITECTURE.md. Здесь нет реализаций и
импортов инфраструктуры: адаптеры подключаются только в ``bootstrap.py``.
"""

from collections.abc import Awaitable, Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol
from uuid import UUID

from teambot.core.events import Attachment, Capabilities, InboundEvent, JsonValue, OutboundMessage
from teambot.core.models import (
    AccessCode,
    AccessCodePurpose,
    BoundChat,
    ChatRef,
    CommandSpec,
    EventKey,
    ExternalChange,
    ExternalIdentity,
    ExternalRef,
    Idea,
    IdeaFilter,
    IdeaMatch,
    LLMRequest,
    LLMResponse,
    MeetingArtifacts,
    MeetingRef,
    NewAccessCode,
    NewIdea,
    NewTask,
    RawRequest,
    RecoverableJob,
    Role,
    Segment,
    SpeakerTurn,
    Task,
    TaskFilter,
    TaskPatch,
    Team,
    TeamContext,
    TeamMember,
    User,
)


class ChannelAdapter(Protocol):
    """Определяет двусторонний адаптер командного чата."""

    platform: str
    capabilities: Capabilities

    async def start(self, on_event: Callable[[InboundEvent], Awaitable[None]]) -> None:
        """Запускает приём событий и передаёт каждое событие обработчику."""
        ...

    async def send(self, msg: OutboundMessage) -> None:
        """Отправляет нормализованное сообщение в канал."""
        ...

    async def download(self, attachment: Attachment) -> bytes:
        """Скачивает вложение по непрозрачным данным адаптера."""
        ...

    async def publish_commands(self, commands: list[CommandSpec]) -> None:
        """Публикует меню команд либо безопасно ничего не делает."""
        ...


class MeetingConnector(Protocol):
    """Определяет получение ссылок и артефактов встреч."""

    platform: str

    async def handle_webhook(self, request: RawRequest) -> list[MeetingRef]:
        """Проверяет входящий запрос и извлекает ссылки на встречи."""
        ...

    async def fetch_artifacts(self, ref: MeetingRef) -> MeetingArtifacts:
        """Загружает доступные артефакты указанной встречи."""
        ...


class SpeechToText(Protocol):
    """Определяет локальное преобразование речи в текст."""

    async def transcribe(self, audio_path: Path, language: str = "ru") -> list[Segment]:
        """Распознаёт аудиофайл и возвращает упорядоченные сегменты."""
        ...


class Diarizer(Protocol):
    """Определяет локальное разделение речи по говорящим."""

    async def diarize(self, audio_path: Path) -> list[SpeakerTurn]:
        """Определяет интервалы говорящих в аудиофайле."""
        ...


class LLMClient(Protocol):
    """Определяет единый маршрут обращения к языковым моделям."""

    async def complete(self, req: LLMRequest) -> LLMResponse:
        """Выполняет запрос с учётом его класса данных."""
        ...


class TaskStore(Protocol):
    """Определяет хранилище внутренних задач с изоляцией команд."""

    async def create(self, ctx: TeamContext, task: NewTask) -> Task:
        """Создаёт задачу внутри команды из контекста."""
        ...

    async def update(self, ctx: TeamContext, task_id: UUID, patch: TaskPatch) -> Task:
        """Обновляет задачу, доступную в контексте команды."""
        ...

    async def list(self, ctx: TeamContext, filt: TaskFilter) -> list[Task]:
        """Возвращает задачи команды по переносимому фильтру."""
        ...

    async def get_by_number(self, ctx: TeamContext, number: int) -> Task | None:
        """Возвращает задачу по устойчивому номеру внутри команды."""
        ...


class EventDeduplicator(Protocol):
    """Атомарно регистрирует ключи входящих событий до побочных эффектов."""

    async def claim(self, key: EventKey) -> bool:
        """Регистрирует событие и сообщает, было ли оно новым.

        Реализация обязана атомарно обеспечивать уникальность тройки полей
        ключа. ``False`` означает, что событие уже обрабатывалось.
        """
        ...


class IdentityStore(Protocol):
    """Хранит глобальных пользователей и связи с внешними аккаунтами."""

    async def find_user(self, identity: ExternalIdentity) -> User | None:
        """Возвращает пользователя, связанного с внешним аккаунтом."""
        ...

    async def create_user(self, identity: ExternalIdentity, display_name: str) -> User:
        """Создаёт пользователя и первую внешнюю идентичность атомарно."""
        ...

    async def add_identity(self, user_id: UUID, identity: ExternalIdentity) -> None:
        """Привязывает внешний аккаунт к существующему пользователю."""
        ...


class TeamStore(Protocol):
    """Управляет командами, членством и чатами со строгим TeamContext."""

    async def get_context(self, team_id: UUID, user_id: UUID) -> TeamContext | None:
        """Находит роль пользователя в явно указанной команде."""
        ...

    async def resolve_chat(self, user_id: UUID, chat: ChatRef) -> TeamContext | None:
        """Разрешает привязанный чат в контекст участвующего пользователя."""
        ...

    async def get_team(self, ctx: TeamContext) -> Team:
        """Возвращает команду только в области переданного контекста."""
        ...

    async def list_members(self, ctx: TeamContext) -> list[TeamMember]:
        """Возвращает участников только указанной команды."""
        ...

    async def add_member(self, ctx: TeamContext) -> TeamMember:
        """Добавляет пользователя из контекста в указанную команду."""
        ...

    async def bind_chat(
        self,
        ctx: TeamContext,
        chat: ChatRef,
        title: str | None = None,
    ) -> None:
        """Привязывает чат к команде действующего администратора."""
        ...

    async def list_chats(self, ctx: TeamContext) -> list[BoundChat]:
        """Возвращает чаты, привязанные только к указанной команде."""
        ...

    async def set_role(self, ctx: TeamContext, user_id: UUID, role: Role) -> TeamMember:
        """Изменяет роль участника в области команды администратора."""
        ...

    async def remove_member(self, ctx: TeamContext, user_id: UUID) -> None:
        """Удаляет членство пользователя только в указанной команде."""
        ...

    async def unbind_chat(self, ctx: TeamContext, chat: ChatRef) -> None:
        """Отвязывает чат от команды действующего администратора."""
        ...

    async def find_owned_team(self, user_id: UUID) -> TeamContext | None:
        """Возвращает единственную команду, где пользователь владелец.

        Если владелецских команд несколько, возвращает ``None``: неоднозначность
        нельзя разрешать без явной привязки чата.
        """
        ...

    async def ensure_owned_team(self, user: User, team_name: str) -> TeamContext:
        """Идемпотентно создаёт команду с пользователем-владельцем."""
        ...


class ChatPresence(Protocol):
    """Проверяет, может ли канал действовать в уже известном чате."""

    async def is_member(self, chat: ChatRef) -> bool | None:
        """Возвращает доступность чата без знания о конкретной платформе.

        ``True`` — бот состоит в чате, ``False`` — нет, ``None`` — этот
        адаптер чат не обслуживает.
        """
        ...


class AccessCodeStore(Protocol):
    """Хранит одноразовые коды привязки, чатов и приглашений."""

    async def create(self, ctx: TeamContext, data: NewAccessCode) -> AccessCode:
        """Создаёт код в области команды действующего пользователя."""
        ...

    async def find(self, code: str, purpose: AccessCodePurpose) -> AccessCode | None:
        """Находит код до определения целевой команды.

        Это единственная нетимовая операция порта: код является защищённым
        указателем на область команды. Любое изменение выполняется через
        ``consume`` с восстановленным ``TeamContext``.
        """
        ...

    async def consume(self, ctx: TeamContext, code_id: UUID) -> bool:
        """Атомарно помечает код использованным в его команде."""
        ...


class IdeaStore(Protocol):
    """Определяет хранилище идей с обязательной изоляцией команд."""

    async def create(self, ctx: TeamContext, idea: NewIdea) -> Idea:
        """Создаёт идею внутри команды из контекста."""
        ...

    async def list(self, ctx: TeamContext, filt: IdeaFilter) -> list[Idea]:
        """Возвращает идеи команды по переносимому фильтру."""
        ...


class TaskSyncAdapter(Protocol):
    """Резервирует контракт синхронизации с внешним трекером этапа 2."""

    async def push(self, task: Task) -> ExternalRef:
        """Передаёт внутреннюю задачу во внешний трекер."""
        ...

    async def pull_changes(self, since: datetime) -> list[ExternalChange]:
        """Получает внешние изменения после указанного момента UTC."""
        ...


class Scheduler(Protocol):
    """Определяет заменяемый планировщик, не являющийся источником истины."""

    async def schedule_once(
        self,
        name: str,
        run_at: datetime,
        payload: dict[str, JsonValue],
    ) -> str:
        """Ставит одноразовое задание и возвращает идентификатор планировщика."""
        ...

    async def schedule_cron(
        self,
        name: str,
        cron: str,
        payload: dict[str, JsonValue],
    ) -> str:
        """Ставит периодическое задание по cron-выражению."""
        ...

    async def cancel(self, job_id: str) -> None:
        """Удаляет задание из планировщика, если оно существует."""
        ...


class IdeaIndex(Protocol):
    """Определяет заменяемый индекс похожих идей."""

    async def index(self, ctx: TeamContext, idea: Idea) -> None:
        """Индексирует идею только в области команды."""
        ...

    async def find_similar(
        self,
        ctx: TeamContext,
        text: str,
        limit: int = 5,
    ) -> list[IdeaMatch]:
        """Находит похожие идеи только внутри команды."""
        ...


class JobRecoverySource(Protocol):
    """Читает активные задания из основного хранилища для восстановления."""

    async def list_team_contexts(self) -> list[TeamContext]:
        """Возвращает контексты команд с активными заданиями."""
        ...

    async def list_active(self, ctx: TeamContext) -> list[RecoverableJob]:
        """Возвращает активные задания строго в области одной команды."""
        ...


class JobExecutor(Protocol):
    """Исполняет восстановленное задание идемпотентным способом."""

    async def execute(self, ctx: TeamContext, job: RecoverableJob) -> bool:
        """Выполняет действие и сообщает, было ли оно применено впервые."""
        ...

"""Оркестратор входящих команд этапа M1.

Оркестратор первым атомарно дедуплицирует событие, разбирает только
slash-команды, разрешает ``TeamContext``, проверяет реестр RBAC и вызывает
доменные сервисы. Свободный текст намеренно игнорируется до этапа M2.
"""

from dataclasses import dataclass
from uuid import UUID

from teambot.core import messages
from teambot.core.commands import available_commands, get_command
from teambot.core.errors import (
    AccessCodeError,
    DomainError,
    IdentityRequired,
    NotFoundError,
    PermissionDenied,
    TeamRequired,
    ValidationError,
)
from teambot.core.events import Attachment, InboundEvent, OutboundMessage
from teambot.core.models import (
    ChatRef,
    CommandSpec,
    EventKey,
    ExternalIdentity,
    Role,
    Task,
    TaskStatus,
    TeamContext,
    role_allows,
)
from teambot.core.ports import EventDeduplicator
from teambot.core.services.ideas import IdeaService
from teambot.core.services.identity import IdentityService
from teambot.core.services.tasks import TaskService


@dataclass(frozen=True, slots=True)
class ParsedCommand:
    """Содержит нормализованное имя команды и оставшиеся аргументы."""

    name: str
    arguments: str


def parse_command(text: str | None) -> ParsedCommand | None:
    """Разбирает slash-команду без платформенных расширений синтаксиса.

    Свободный текст, одиночный слеш и команды с суффиксом после ``@`` не
    интерпретируются ядром: адаптер обязан передать каноническое имя.
    """
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return None
    head, _, arguments = stripped.partition(" ")
    name = head[1:].casefold()
    if not name:
        return None
    return ParsedCommand(name=name, arguments=arguments.strip())


class Orchestrator:
    """Маршрутизирует дедуплицированные входящие slash-команды."""

    def __init__(
        self,
        deduplicator: EventDeduplicator,
        identity: IdentityService,
        tasks: TaskService,
        ideas: IdeaService,
    ) -> None:
        """Создаёт оркестратор из портов и сервисов M1."""
        self._deduplicator = deduplicator
        self._identity = identity
        self._tasks = tasks
        self._ideas = ideas

    async def handle(self, event: InboundEvent) -> list[OutboundMessage]:
        """Обрабатывает одно входящее событие идемпотентно.

        Возвращает:
            Ноль или одно сообщение. Повтор и свободный текст возвращают
            пустой список и не вызывают бизнес-сервисы.
        """
        key = EventKey(event.platform, event.chat_id, event.message_id)
        if not await self._deduplicator.claim(key):
            return []
        parsed = parse_command(event.text)
        if parsed is None:
            return []
        spec = get_command(parsed.name)
        if spec is None:
            return [self._reply(event, messages.UNKNOWN_COMMAND)]
        identity = ExternalIdentity(event.platform, event.platform_user_id)
        chat = ChatRef(event.platform, event.chat_id)
        try:
            result = await self._dispatch(spec, parsed.arguments, identity, chat, event)
        except PermissionDenied:
            result = messages.PERMISSION_DENIED
        except IdentityRequired:
            result = messages.IDENTITY_REQUIRED
        except TeamRequired:
            result = messages.TEAM_REQUIRED
        except AccessCodeError:
            result = messages.ACCESS_CODE_INVALID
        except ValidationError:
            result = messages.format_invalid_usage(spec)
        except NotFoundError:
            result = messages.NOT_FOUND
        except DomainError:
            result = messages.INVALID_ARGUMENTS
        if isinstance(result, OutboundMessage):
            return [result]
        return [self._reply(event, result)]

    async def _dispatch(
        self,
        spec: CommandSpec,
        arguments: str,
        identity: ExternalIdentity,
        chat: ChatRef,
        event: InboundEvent,
    ) -> str | OutboundMessage:
        if spec.handler == "start":
            if arguments:
                await self._identity.accept_invite(identity, arguments, chat)
            else:
                await self._identity.register(
                    identity,
                    display_name=event.display_name,
                    chat=chat,
                )
            return messages.START
        if spec.handler == "link":
            if arguments:
                await self._identity.link_account(identity, arguments)
                return messages.ACCOUNT_LINKED
            _, ctx = await self._identity.resolve(identity, chat)
            code = await self._identity.create_link_code(ctx)
            return messages.format_link_code(code.code)
        if spec.handler == "bind" and arguments:
            user = await self._identity.identify(identity)
            await self._identity.bind_chat(user.id, chat, arguments)
            return messages.CHAT_BOUND
        if spec.handler == "help":
            role = await self._optional_role(identity, chat)
            return messages.format_help(available_commands(role))

        _, ctx = await self._identity.resolve(identity, chat)
        self._check_access(ctx, spec)

        if spec.handler == "add":
            await self._tasks.add(ctx, arguments)
            return messages.TASK_ADDED
        if spec.handler == "list_tasks":
            return messages.format_tasks(await self._list_tasks(ctx, arguments))
        if spec.handler == "list_csv":
            return _export_reply(
                event,
                messages.CSV_EXPORT_CAPTION,
                "tasks.csv",
                "text/csv",
                messages.format_tasks_csv(await self._tasks.list(ctx, status=None)),
            )
        if spec.handler == "list_html":
            return _export_reply(
                event,
                messages.HTML_EXPORT_CAPTION,
                "tasks.html",
                "text/html",
                messages.format_tasks_html(await self._tasks.list(ctx, status=None)),
            )
        if spec.handler == "summary":
            return messages.format_summary(await self._tasks.list(ctx, status=None))
        if spec.handler == "my":
            return messages.format_tasks(await self._tasks.list(ctx, status=None, only_mine=True))
        if spec.handler == "done":
            await self._tasks.complete(ctx, _parse_number(arguments))
            return messages.TASK_DONE
        if spec.handler == "edit":
            number, title = _split_number_and_text(arguments)
            await self._tasks.edit(ctx, number, title)
            return messages.TASK_EDITED
        if spec.handler == "idea":
            await self._ideas.add(ctx, arguments, source_message_id=event.message_id)
            return messages.IDEA_ADDED
        if spec.handler == "ideas":
            return messages.format_ideas(await self._ideas.list(ctx, arguments or None))
        if spec.handler == "bind":
            code = await self._identity.create_bind_code(ctx)
            return messages.format_bind_code(code.code)
        if spec.handler == "team":
            team, members = await self._identity.team(ctx)
            return messages.format_team(team, members)
        if spec.handler == "invite":
            role = _parse_role(arguments, default=Role.MEMBER)
            code = await self._identity.create_invite(ctx, role)
            return messages.format_invite(code.code, role)
        if spec.handler == "role":
            user_id, role = _parse_role_change(arguments)
            await self._identity.set_role(ctx, user_id, role)
            return messages.ROLE_CHANGED
        raise ValidationError("Обработчик команды не реализован")

    async def _optional_role(
        self,
        identity: ExternalIdentity,
        chat: ChatRef,
    ) -> Role | None:
        try:
            _, ctx = await self._identity.resolve(identity, chat)
        except (IdentityRequired, TeamRequired):
            return None
        return ctx.role

    async def _list_tasks(self, ctx: TeamContext, arguments: str) -> list[Task]:
        normalized = arguments.casefold() or "open"
        statuses = {
            "open": TaskStatus.OPEN,
            "done": TaskStatus.DONE,
            "all": None,
        }
        if normalized not in statuses:
            raise ValidationError("Неизвестный фильтр задач")
        return await self._tasks.list(ctx, statuses[normalized])

    @staticmethod
    def _check_access(ctx: TeamContext, spec: CommandSpec) -> None:
        if spec.min_role is not None and not role_allows(ctx.role, spec.min_role):
            raise PermissionDenied

    @staticmethod
    def _reply(event: InboundEvent, text: str) -> OutboundMessage:
        return OutboundMessage(chat_id=event.chat_id, text=text, reply_to=event.message_id)


def _export_reply(
    event: InboundEvent,
    caption: str,
    filename: str,
    mime_type: str,
    content: str,
) -> OutboundMessage:
    """Собирает исходящее сообщение с файлом экспорта без записи текста в логи."""
    return OutboundMessage(
        chat_id=event.chat_id,
        text=caption,
        reply_to=event.message_id,
        attachments=[
            Attachment(
                id=filename,
                kind="file",
                filename=filename,
                mime_type=mime_type,
                metadata={"content": content},
            )
        ],
    )


def _parse_number(value: str) -> int:
    try:
        return int(value)
    except ValueError as error:
        raise ValidationError("Ожидается номер") from error


def _split_number_and_text(value: str) -> tuple[int, str]:
    number, separator, text = value.partition(" ")
    if not separator or not text.strip():
        raise ValidationError("Ожидаются номер и текст")
    return _parse_number(number), text


def _parse_role(value: str, *, default: Role) -> Role:
    if not value:
        return default
    try:
        return Role(value.casefold())
    except ValueError as error:
        raise ValidationError("Неизвестная роль") from error


def _parse_role_change(value: str) -> tuple[UUID, Role]:
    user_id_text, separator, role_text = value.partition(" ")
    if not separator:
        raise ValidationError("Ожидаются пользователь и роль")
    try:
        user_id = UUID(user_id_text)
    except ValueError as error:
        raise ValidationError("Некорректный идентификатор пользователя") from error
    return user_id, _parse_role(role_text.strip(), default=Role.MEMBER)

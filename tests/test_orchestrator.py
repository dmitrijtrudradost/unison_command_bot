"""Тесты реестра и идемпотентной маршрутизации команд M1."""

from datetime import UTC, datetime
from uuid import uuid4

from test_core_services import FakeIdeaIndex, FakeIdeaStore, FakeTaskStore
from test_identity_service import (
    FakeAccessCodeStore,
    FakeIdentityStore,
    FakeTeamStore,
)

from teambot.core.commands import COMMANDS
from teambot.core.events import InboundEvent
from teambot.core.messages import (
    ACCOUNT_LINKED,
    CHAT_BOUND,
    IDEA_ADDED,
    NOT_FOUND,
    PERMISSION_DENIED,
    ROLE_CHANGED,
    START,
    TASK_ADDED,
    TASK_DONE,
    TASK_EDITED,
    format_invalid_usage,
)
from teambot.core.models import (
    ChatRef,
    EventKey,
    ExternalIdentity,
    Role,
    Team,
    TeamMember,
    User,
)
from teambot.core.orchestrator import Orchestrator
from teambot.core.services.ideas import IdeaService
from teambot.core.services.identity import IdentityService
from teambot.core.services.tasks import TaskService


class FakeDeduplicator:
    def __init__(self) -> None:
        self.claimed: set[EventKey] = set()

    async def claim(self, key: EventKey) -> bool:
        if key in self.claimed:
            return False
        self.claimed.add(key)
        return True


def make_event(
    message_id: str,
    text: str,
    *,
    user_id: str = "user-1",
    chat_id: str = "chat-1",
) -> InboundEvent:
    return InboundEvent(
        platform="channel-a",
        chat_id=chat_id,
        message_id=message_id,
        platform_user_id=user_id,
        text=text,
        attachments=[],
        reply_to=None,
        thread_id=None,
        ts=datetime.now(UTC),
        raw={},
        display_name="Участник",
    )


def build_orchestrator() -> tuple[Orchestrator, FakeTaskStore]:
    team = Team(uuid4(), "Команда")
    user = User(uuid4(), "Участник")
    identities = FakeIdentityStore()
    identity = ExternalIdentity("channel-a", "user-1")
    identities.users[identity] = user
    teams = FakeTeamStore(
        team,
        [TeamMember(user.id, user.display_name, Role.MEMBER)],
    )
    teams.chats[ChatRef("channel-a", "chat-1")] = team.id
    task_store = FakeTaskStore()
    orchestrator = Orchestrator(
        FakeDeduplicator(),
        IdentityService(identities, teams, FakeAccessCodeStore()),
        TaskService(task_store),
        IdeaService(FakeIdeaStore(), FakeIdeaIndex()),
    )
    return orchestrator, task_store


def test_m1_registry_has_canonical_order_and_roles() -> None:
    assert [command.name for command in COMMANDS] == [
        "start",
        "add",
        "list",
        "list_csv",
        "list_html",
        "summary",
        "help",
        "my",
        "done",
        "edit",
        "idea",
        "ideas",
        "link",
        "bind",
        "team",
        "invite",
        "role",
    ]
    assert next(command for command in COMMANDS if command.name == "ideas").min_role is Role.VIEWER
    assert next(command for command in COMMANDS if command.name == "bind").min_role is Role.ADMIN


async def test_duplicate_event_does_not_repeat_side_effect() -> None:
    orchestrator, store = build_orchestrator()
    event = make_event("same", "/add Подготовить релиз")

    first = await orchestrator.handle(event)
    second = await orchestrator.handle(event)

    assert first[0].text == "Задача добавлена."
    assert second == []
    assert len(store.tasks) == 1


async def test_free_text_is_ignored_without_side_effects() -> None:
    orchestrator, store = build_orchestrator()

    response = await orchestrator.handle(make_event("free", "Подготовить релиз"))

    assert response == []
    assert store.tasks == []


async def test_list_csv_returns_file_attachment() -> None:
    orchestrator, store = build_orchestrator()
    await orchestrator.handle(make_event("1", "/add Первая"))
    replies = await orchestrator.handle(make_event("2", "/list_csv"))

    assert replies[0].text == "Список задач в CSV."
    assert replies[0].attachments[0].filename == "tasks.csv"
    assert "Первая" in str(replies[0].attachments[0].metadata["content"])
    assert store.tasks[0].number == 1


async def test_help_and_unknown_command() -> None:
    orchestrator, _store = build_orchestrator()
    help_reply = await orchestrator.handle(make_event("h", "/help"))
    unknown = await orchestrator.handle(make_event("u", "/nonesuch"))

    assert "/add — Добавить задачу" in help_reply[0].text
    assert "Синтаксис: /add <текст>" in help_reply[0].text
    assert "Пример: /add Подготовить отчёт к пятнице" in help_reply[0].text
    assert unknown[0].text == "Неизвестная команда. Используйте /help."


async def test_all_m1_commands_and_permission_errors() -> None:
    team = Team(uuid4(), "Команда")
    owner_user = User(uuid4(), "Владелец")
    identities = FakeIdentityStore()
    owner_identity = ExternalIdentity("channel-a", "owner-1")
    identities.users[owner_identity] = owner_user
    teams = FakeTeamStore(
        team,
        [TeamMember(owner_user.id, owner_user.display_name, Role.OWNER)],
    )
    teams.chats[ChatRef("channel-a", "chat-1")] = team.id
    codes = FakeAccessCodeStore()
    issued = iter(["invite-1", "link-1", "bind-1"])
    task_store = FakeTaskStore()
    orchestrator = Orchestrator(
        FakeDeduplicator(),
        IdentityService(identities, teams, codes, code_factory=lambda: next(issued)),
        TaskService(task_store),
        IdeaService(FakeIdeaStore(), FakeIdeaIndex()),
    )

    async def owner(message_id: str, text: str) -> str:
        replies = await orchestrator.handle(
            make_event(message_id, text, user_id="owner-1"),
        )
        return replies[0].text

    assert await owner("s", "/start") == START
    assert await owner("a", "/add Подготовить релиз") == TASK_ADDED
    assert "1. ○ Подготовить релиз" in await owner("l", "/list")
    csv_reply = await orchestrator.handle(make_event("c", "/list_csv", user_id="owner-1"))
    assert csv_reply[0].attachments[0].filename == "tasks.csv"
    html_reply = await orchestrator.handle(make_event("ht", "/list_html", user_id="owner-1"))
    assert html_reply[0].attachments[0].filename == "tasks.html"
    assert "Всего задач: 1" in await owner("sum", "/summary")
    assert "/help — Справка" in await owner("h1", "/help")
    assert "1. ○ Подготовить релиз" in await owner("my", "/my")
    assert await owner("ed", "/edit 1 Новый текст") == TASK_EDITED
    assert await owner("dn", "/done 1") == TASK_DONE
    assert await owner("id", "/idea Новый бот #продукт") == IDEA_ADDED
    assert "Новый бот #продукт" in await owner("ids", "/ideas продукт")
    assert "Команда: Команда" in await owner("tm", "/team")
    assert "Код приглашения для роли member: invite-1" in await owner("inv", "/invite")
    assert "Код привязки аккаунта: link-1" in await owner("lk", "/link")
    assert "Код привязки чата: bind-1" in await owner("bd", "/bind")
    add_help = next(command for command in COMMANDS if command.name == "add")
    done_help = next(command for command in COMMANDS if command.name == "done")
    assert await owner("ba", "/add") == format_invalid_usage(add_help)
    assert await owner("db", "/done abc") == format_invalid_usage(done_help)
    assert await owner("dm", "/done 99") == NOT_FOUND

    joined = await orchestrator.handle(
        make_event("st2", "/start invite-1", user_id="member-1", chat_id="chat-2"),
    )
    assert joined[0].text == START
    role_reply = await owner("rl", f"/role {teams.members[-1].user_id} viewer")
    assert role_reply == ROLE_CHANGED

    linked = await orchestrator.handle(
        make_event("ln", "/link link-1", user_id="owner-alt"),
    )
    assert linked[0].text == ACCOUNT_LINKED
    bound = await orchestrator.handle(
        make_event("bn", "/bind bind-1", user_id="owner-1", chat_id="chat-3"),
    )
    assert bound[0].text == CHAT_BOUND

    viewer_add = await orchestrator.handle(
        make_event("va", "/add Нельзя", user_id="member-1", chat_id="chat-2"),
    )
    assert viewer_add[0].text == PERMISSION_DENIED
    assert len(task_store.tasks) == 1

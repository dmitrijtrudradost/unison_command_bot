"""Канонический реестр slash-команд этапа M1.

Порядок соответствует разделу 9.1 ``ARCHITECTURE.md``: сначала сохранены
команды прототипа, затем добавлены команды M1. Адаптеры публикуют этот реестр,
а оркестратор использует его для маршрутизации и единой проверки RBAC.
"""

import re

from teambot.core.models import CommandSpec, Role, role_allows

COMMANDS: tuple[CommandSpec, ...] = (
    CommandSpec(
        "start",
        "Начать",
        None,
        "existing",
        "start",
        "/start [код]",
        "/start Ab3xY9kLm2",
    ),
    CommandSpec(
        "add",
        "Добавить задачу",
        Role.MEMBER,
        "existing",
        "add",
        "/add <текст>",
        "/add Подготовить отчёт к пятнице",
    ),
    CommandSpec(
        "list",
        "Список задач",
        Role.VIEWER,
        "existing",
        "list_tasks",
        "/list [open|done|all]",
        "/list open",
    ),
    CommandSpec(
        "list_csv",
        "Список в csv",
        Role.VIEWER,
        "existing",
        "list_csv",
        "/list_csv",
        "/list_csv",
    ),
    CommandSpec(
        "list_html",
        "Список в html",
        Role.VIEWER,
        "existing",
        "list_html",
        "/list_html",
        "/list_html",
    ),
    CommandSpec(
        "summary",
        "Итоги задач",
        Role.VIEWER,
        "existing",
        "summary",
        "/summary",
        "/summary",
    ),
    CommandSpec("help", "Справка", None, "M1", "help", "/help", "/help"),
    CommandSpec(
        "my",
        "Мои задачи",
        Role.MEMBER,
        "M1",
        "my",
        "/my",
        "/my",
    ),
    CommandSpec(
        "done",
        "Завершить задачу",
        Role.MEMBER,
        "M1",
        "done",
        "/done <номер>",
        "/done 1",
    ),
    CommandSpec(
        "edit",
        "Изменить задачу",
        Role.MEMBER,
        "M1",
        "edit",
        "/edit <номер> <новый текст>",
        "/edit 1 Подготовить отчёт к понедельнику",
    ),
    CommandSpec(
        "idea",
        "Добавить идею",
        Role.MEMBER,
        "M1",
        "idea",
        "/idea <текст>",
        "/idea Сделать дашборд для отчётов #продукт #аналитика",
    ),
    CommandSpec(
        "ideas",
        "Список идей",
        Role.VIEWER,
        "M1",
        "ideas",
        "/ideas [текст]",
        "/ideas #продукт",
    ),
    CommandSpec(
        "link",
        "Привязать аккаунт",
        None,
        "M1",
        "link",
        "/link [код]",
        "/link Ab3xY9kLm2",
    ),
    CommandSpec(
        "bind",
        "Привязать чат к команде",
        Role.ADMIN,
        "M1",
        "bind",
        "/bind [код]",
        "/bind Ab3xY9kLm2",
    ),
    CommandSpec(
        "team",
        "Моя команда",
        Role.MEMBER,
        "M1",
        "team",
        "/team",
        "/team",
    ),
    CommandSpec(
        "invite",
        "Пригласить в команду",
        Role.ADMIN,
        "M1",
        "invite",
        "/invite [роль]",
        "/invite member",
    ),
    CommandSpec(
        "role",
        "Назначить роль",
        Role.ADMIN,
        "M1",
        "role",
        "/role <uuid> <роль>",
        "/role 11111111-1111-1111-1111-111111111111 viewer",
    ),
)

_COMMAND_NAME = re.compile(r"^[a-z0-9_]{1,32}$")
_COMMANDS_BY_NAME = {command.name: command for command in COMMANDS}

if len(_COMMANDS_BY_NAME) != len(COMMANDS) or any(
    _COMMAND_NAME.fullmatch(command.name) is None for command in COMMANDS
):
    raise RuntimeError("Реестр команд содержит повтор или недопустимое имя")


def get_command(name: str) -> CommandSpec | None:
    """Возвращает описание команды по имени без начального слеша.

    Аргументы:
        name: нормализованное имя команды.

    Возвращает:
        Спецификацию команды либо ``None`` для неизвестного имени.
    """
    return _COMMANDS_BY_NAME.get(name)


def available_commands(role: Role | None) -> tuple[CommandSpec, ...]:
    """Возвращает команды, доступные пользователю с указанной ролью.

    Аргументы:
        role: роль в текущей команде или ``None`` вне команды.

    Возвращает:
        Команды в каноническом порядке меню.
    """
    return tuple(
        command
        for command in COMMANDS
        if command.min_role is None or (role is not None and role_allows(role, command.min_role))
    )

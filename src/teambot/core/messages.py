"""Русские пользовательские тексты и форматирование ответов M1.

Модуль является единственным местом ядра, где собираются сообщения для
пользователя. Бизнес-сервисы возвращают доменные модели и не зависят от языка.
"""

import csv
import html
import io

from teambot.core.models import CommandSpec, Idea, Role, Task, Team, TeamMember

START = "Team Bot готов. Используйте /help, чтобы увидеть доступные команды."
CHANNEL_DISABLED = "Канал мессенджера отключён: токен не задан."
CSV_EXPORT_CAPTION = "Список задач в CSV."
HTML_EXPORT_CAPTION = "Список задач в HTML."
IDENTITY_REQUIRED = "Сначала используйте /start или привяжите аккаунт командой /link <код>."
TEAM_REQUIRED = "Этот чат не привязан к доступной вам команде."
PERMISSION_DENIED = "Недостаточно прав для этой команды."
UNKNOWN_COMMAND = "Неизвестная команда. Используйте /help."
INVALID_ARGUMENTS = "Проверьте аргументы команды."
NOT_FOUND = "Не найдено."
ACCESS_CODE_INVALID = "Код недействителен, уже использован или истёк."
TASK_ADDED = "Задача добавлена."
TASK_DONE = "Задача завершена."
TASK_EDITED = "Задача изменена."
IDEA_ADDED = "Идея добавлена."
NO_TASKS = "Задач не найдено."
NO_IDEAS = "Идей не найдено."
CHAT_BOUND = "Чат привязан к команде."
ACCOUNT_LINKED = "Аккаунт привязан."
ROLE_CHANGED = "Роль участника изменена."


def format_command_help(command: CommandSpec) -> str:
    """Формирует синтаксис и пример одной команды."""
    return (
        f"/{command.name} — {command.description_ru}\n"
        f"Синтаксис: {command.syntax_ru}\n"
        f"Пример: {command.usage_ru}"
    )


def format_help(commands: tuple[CommandSpec, ...]) -> str:
    """Формирует справку из доступной части реестра команд."""
    return "\n\n".join(format_command_help(command) for command in commands)


def format_invalid_usage(command: CommandSpec) -> str:
    """Формирует ответ на неверные аргументы вместе с хелпом этой команды."""
    return f"{INVALID_ARGUMENTS}\n{format_command_help(command)}"


def format_tasks(tasks: list[Task]) -> str:
    """Формирует список задач с устойчивыми командными номерами."""
    if not tasks:
        return NO_TASKS
    lines: list[str] = []
    for task in tasks:
        marker = "✓" if task.status.value == "done" else "○"
        lines.append(f"{task.number}. {marker} {task.title}")
    return "\n".join(lines)


def format_tasks_csv(tasks: list[Task]) -> str:
    """Формирует CSV-экспорт задач в памяти.

    Начальный BOM нужен, чтобы Excel на Windows открыл файл как UTF-8,
    а не как системную ANSI-кодировку и не испортил кириллицу.
    """
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(("number", "status", "title"))
    for task in tasks:
        writer.writerow((task.number, task.status.value, task.title))
    return "\ufeff" + stream.getvalue()


def format_tasks_html(tasks: list[Task]) -> str:
    """Формирует безопасный HTML-экспорт задач."""
    rows = "".join(
        "<tr>"
        f"<td>{task.number}</td><td>{html.escape(task.status.value)}</td>"
        f"<td>{html.escape(task.title)}</td>"
        "</tr>"
        for task in tasks
    )
    return (
        "<table><thead><tr><th>№</th><th>Статус</th><th>Задача</th></tr></thead>"
        f"<tbody>{rows}</tbody></table>"
    )


def format_summary(tasks: list[Task]) -> str:
    """Формирует краткие итоги по текущему списку задач."""
    done = sum(task.status.value == "done" for task in tasks)
    return f"Всего задач: {len(tasks)}. Открыто: {len(tasks) - done}. Завершено: {done}."


def format_ideas(ideas: list[Idea]) -> str:
    """Формирует нумерованный список идей."""
    if not ideas:
        return NO_IDEAS
    return "\n".join(f"{number}. {idea.text}" for number, idea in enumerate(ideas, start=1))


def format_team(team: Team, members: list[TeamMember]) -> str:
    """Формирует список участников и ролей команды."""
    lines = [f"Команда: {team.name}"]
    lines.extend(
        f"{number}. {member.display_name} — {member.role.value} ({member.user_id})"
        for number, member in enumerate(members, start=1)
    )
    return "\n".join(lines)


def format_invite(code: str, role: Role) -> str:
    """Формирует ответ с одноразовым кодом приглашения."""
    return f"Код приглашения для роли {role.value}: {code}"


def format_link_code(code: str) -> str:
    """Формирует ответ с кодом привязки дополнительного аккаунта."""
    return f"Код привязки аккаунта: {code}"


def format_bind_code(code: str) -> str:
    """Формирует ответ с кодом привязки нового чата."""
    return f"Код привязки чата: {code}"

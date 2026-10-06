"""Проверки пользовательских текстов, которые зависят от кодировки файла."""

from uuid import uuid4

from teambot.core.messages import format_chats, format_tasks_csv
from teambot.core.models import BoundChat, ChatRef, Task, TaskStatus, Team


def test_tasks_csv_starts_with_utf8_bom_and_keeps_cyrillic() -> None:
    csv_text = format_tasks_csv(
        [
            Task(
                id=uuid4(),
                team_id=uuid4(),
                number=1,
                title="Подготовить отчёт",
                status=TaskStatus.OPEN,
                created_by=uuid4(),
            )
        ]
    )

    assert csv_text.startswith("\ufeff")
    assert "Подготовить отчёт" in csv_text
    assert csv_text.encode("utf-8").startswith(b"\xef\xbb\xbf")


def test_format_chats_shows_presence_and_empty_state() -> None:
    team = Team(uuid4(), "Команда")
    chats = [
        BoundChat(ChatRef("channel-a", "1"), "Группа"),
        BoundChat(ChatRef("channel-a", "2"), None),
    ]

    text = format_chats(team, chats, [True, False])

    assert text.startswith("Чаты команды: Команда")
    assert "1. Группа (1) — бот в чате" in text
    assert "2. 2 (2) — бот не в чате" in text
    assert format_chats(team, [], []) == "Привязанных чатов нет."

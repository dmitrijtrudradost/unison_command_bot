"""Проверки пользовательских текстов, которые зависят от кодировки файла."""

from uuid import uuid4

from teambot.core.messages import format_tasks_csv
from teambot.core.models import Task, TaskStatus


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

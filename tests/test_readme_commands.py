"""Сверка таблицы команд README с реестром core/commands.py."""

from pathlib import Path

from teambot.core.commands import COMMANDS


def test_readme_documents_every_registry_command() -> None:
    readme = Path(__file__).resolve().parents[1] / "README.md"
    text = readme.read_text(encoding="utf-8").replace("\\|", "|")
    for command in COMMANDS:
        assert f"`/{command.name}`" in text, command.name
        assert command.description_ru in text, command.name
        assert command.syntax_ru in text, command.name
        assert command.usage_ru in text, command.name

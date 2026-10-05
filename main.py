"""Единственная исполняемая точка входа Team Bot.

Модуль только разбирает режим запуска, вызывает композицию из
``teambot.bootstrap`` и запускает ASGI-сервер (ARCHITECTURE.md, раздел 4.1).
"""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path

# Позволяет выполнить ``python main.py`` до установки пакета. При запуске через
# uv пакет также устанавливается из src-layout, поэтому путь остаётся тем же.
sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import uvicorn  # noqa: E402

from teambot.bootstrap import build_application  # noqa: E402
from teambot.infra.config import get_settings  # noqa: E402
from teambot.infra.migrations import upgrade_database  # noqa: E402


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    """Разбирает режим процесса.

    Аргументы:
        argv: Аргументы без имени программы; ``None`` означает ``sys.argv``.

    Возвращает:
        Пространство имён с выбранным режимом. Режим worker появится на M2.5.
    """
    parser = argparse.ArgumentParser(description="Team Bot")
    parser.add_argument(
        "mode",
        nargs="?",
        default="app",
        choices=("app",),
        help="режим процесса; сейчас доступен только app",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Собирает и запускает основной процесс приложения.

    Аргументы:
        argv: Необязательный набор аргументов для тестируемого запуска.

    Возвращает:
        Код завершения процесса после штатной остановки сервера.
    """
    parse_args(argv)
    settings = get_settings()
    upgrade_database(settings.database_url)
    application = build_application(settings)
    uvicorn.run(
        application.web,
        host=application.settings.app_host,
        port=application.settings.app_port,
        log_config=None,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

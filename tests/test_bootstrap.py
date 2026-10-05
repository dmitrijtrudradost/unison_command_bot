"""Проверка сборки процесса M1 без активного канала Telegram."""

from pathlib import Path

from pytest import MonkeyPatch

from teambot.adapters.channels.telegram import TelegramSettings
from teambot.bootstrap import build_application
from teambot.infra.config import Settings


async def test_application_starts_without_telegram_token(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    settings = Settings(database_url=f"sqlite+aiosqlite:///{tmp_path / 'app.db'}")
    application = build_application(
        settings=settings,
        telegram_settings=TelegramSettings(telegram_bot_token=None),
    )
    try:
        assert application.telegram is None
    finally:
        await application.database.close()

"""Контрактные проверки адаптера Telegram без сети."""

from datetime import UTC, datetime
from typing import Any, cast

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest
from aiogram.methods import SendMessage
from aiogram.types import Message
from pydantic import SecretStr

from teambot.adapters.channels.telegram import (
    TelegramAdapter,
    TelegramSettings,
    inbound_event_from_message,
    split_text,
)
from teambot.core.commands import COMMANDS
from teambot.core.events import Attachment, Capabilities, InboundEvent, OutboundMessage


class RecordingBot:
    def __init__(self) -> None:
        self.messages: list[tuple[int, str, int | None]] = []
        self.documents: list[Any] = []
        self.commands: list[Any] = []
        self.downloaded: list[str] = []

    async def send_message(
        self,
        chat_id: int,
        text: str,
        reply_to_message_id: int | None = None,
        parse_mode: str | None = None,
    ) -> None:
        del parse_mode
        self.messages.append((chat_id, text, reply_to_message_id))

    async def send_document(self, chat_id: int, document: Any) -> None:
        self.documents.append((chat_id, document))

    async def set_my_commands(self, commands: list[Any]) -> None:
        self.commands = commands

    async def download(self, file: str, destination: Any) -> None:
        self.downloaded.append(file)
        destination.write(b"file-bytes")


def _settings() -> TelegramSettings:
    return TelegramSettings(
        telegram_bot_token=SecretStr("123:test-token"),
        telegram_bootstrap_owner_id="99",
    )


def test_inbound_event_strips_bot_suffix_and_hides_raw_payload() -> None:
    message = Message.model_validate(
        {
            "message_id": 7,
            "date": datetime(2026, 1, 2, tzinfo=UTC),
            "chat": {"id": 55, "type": "private"},
            "from": {
                "id": 99,
                "is_bot": False,
                "first_name": "Анна",
                "last_name": "Иванова",
            },
            "text": "/start@DemoBot code-1",
        }
    )

    event = inbound_event_from_message(message)

    assert event.platform == "telegram"
    assert event.chat_id == "55"
    assert event.message_id == "7"
    assert event.platform_user_id == "99"
    assert event.text == "/start code-1"
    assert event.display_name == "Анна Иванова"
    assert event.raw == {}


def test_split_text_respects_telegram_limit() -> None:
    assert split_text("abcdef", limit=4) == ["abcd", "ef"]


async def test_send_splits_text_and_sends_export_file() -> None:
    bot = RecordingBot()
    adapter = TelegramAdapter(_settings(), bot=cast(Bot, bot))
    adapter.capabilities = Capabilities(
        buttons=True,
        markdown=True,
        max_text_len=4,
        files=True,
        threads=True,
        message_edit=True,
    )

    await adapter.send(
        OutboundMessage(
            chat_id="55",
            text="x" * 10,
            attachments=[
                Attachment(
                    id="tasks.csv",
                    filename="tasks.csv",
                    mime_type="text/csv",
                    metadata={"content": "number,status\n1,open\n"},
                )
            ],
        )
    )

    assert [text for _chat, text, _reply in bot.messages] == ["xxxx", "xxxx", "xx"]
    assert bot.documents
    assert bot.documents[0][1].filename == "tasks.csv"


async def test_markdown_falls_back_to_plain_text() -> None:
    class MarkdownFailingBot(RecordingBot):
        async def send_message(
            self,
            chat_id: int,
            text: str,
            reply_to_message_id: int | None = None,
            parse_mode: str | None = None,
        ) -> None:
            if parse_mode:
                raise TelegramBadRequest(
                    method=SendMessage(chat_id=chat_id, text=text),
                    message="Bad Request: can't parse entities",
                )
            await super().send_message(chat_id, text, reply_to_message_id)

    bot = MarkdownFailingBot()
    adapter = TelegramAdapter(_settings(), bot=cast(Bot, bot))
    await adapter.send(OutboundMessage(chat_id="55", text="*привет*", format="markdown"))

    assert bot.messages == [(55, "*привет*", None)]


async def test_handle_message_forwards_event_to_orchestrator() -> None:
    bot = RecordingBot()
    adapter = TelegramAdapter(_settings(), bot=cast(Bot, bot))
    received: list[str | None] = []

    async def on_event(event: InboundEvent) -> list[OutboundMessage]:
        received.append(event.text)
        return [OutboundMessage(chat_id=event.chat_id, text="принято")]

    adapter._on_event = on_event
    message = Message.model_validate(
        {
            "message_id": 8,
            "date": datetime(2026, 1, 2, tzinfo=UTC),
            "chat": {"id": 55, "type": "private"},
            "from": {"id": 99, "is_bot": False, "first_name": "Анна"},
            "text": "/help",
        }
    )

    await adapter._handle_message(message)

    assert received == ["/help"]
    assert bot.messages == [(55, "принято", None)]


async def test_publish_commands_and_download() -> None:
    bot = RecordingBot()
    adapter = TelegramAdapter(_settings(), bot=cast(Bot, bot))
    await adapter.publish_commands(list(COMMANDS))
    payload = await adapter.download(Attachment(id="file", metadata={"file_id": "file-1"}))

    assert [command.command for command in bot.commands] == [item.name for item in COMMANDS]
    assert payload == b"file-bytes"
    assert bot.downloaded == ["file-1"]

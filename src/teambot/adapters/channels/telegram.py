"""Адаптер Telegram на long polling.

Платформенные детали Bot API живут только здесь и в ``bootstrap.py``.
Ядро получает ``InboundEvent`` и отдаёт ``OutboundMessage`` (раздел 6).
Webhook на этапе M1 не используется.
"""

from collections.abc import Awaitable, Callable
from datetime import UTC
from io import BytesIO

import structlog
from aiogram import Bot, Dispatcher
from aiogram.enums import ChatMemberStatus, ParseMode
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError
from aiogram.types import (
    BotCommand,
    BufferedInputFile,
    Chat,
    Message,
)
from pydantic import SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from teambot.core.commands import COMMANDS
from teambot.core.events import Attachment, Capabilities, InboundEvent, OutboundMessage
from teambot.core.models import ChatRef, CommandSpec

logger = structlog.get_logger(__name__)

TELEGRAM_TEXT_LIMIT = 4096
TELEGRAM_SOURCE = "telegram"
_ACTIVE_MEMBER_STATUSES = {
    ChatMemberStatus.CREATOR,
    ChatMemberStatus.ADMINISTRATOR,
    ChatMemberStatus.MEMBER,
    ChatMemberStatus.RESTRICTED,
}


class TelegramSettings(BaseSettings):
    """Читает настройки канала Telegram из окружения, минуя общее ядро."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    telegram_bot_token: SecretStr | None = None
    telegram_bootstrap_owner_id: str | None = None
    telegram_webhook_secret: SecretStr | None = None

    @field_validator(
        "telegram_bot_token",
        "telegram_bootstrap_owner_id",
        "telegram_webhook_secret",
        mode="before",
    )
    @classmethod
    def empty_optional_value_as_none(cls, value: object) -> object:
        """Преобразует пустую строку шаблона в ``None``."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


def load_telegram_settings() -> TelegramSettings:
    """Загружает настройки канала из окружения."""
    return TelegramSettings()


def inbound_event_from_message(message: Message) -> InboundEvent:
    """Приводит сообщение Telegram к каноническому входящему событию.

    Аргументы:
        message: объект aiogram без обращения к сети.

    Возвращает:
        Нормализованное событие. Текст команды очищается от суффикса бота.
    """
    sender = message.from_user
    platform_user_id = "" if sender is None else str(sender.id)
    display_name = None if sender is None else _display_name(sender.first_name, sender.last_name)
    text = _canonical_command_text(message.text or message.caption)
    attachments = _attachments_from_message(message)
    occurred = message.date
    if occurred.tzinfo is None:
        occurred = occurred.replace(tzinfo=UTC)
    return InboundEvent(
        platform=TELEGRAM_SOURCE,
        chat_id=str(message.chat.id),
        message_id=str(message.message_id),
        platform_user_id=platform_user_id,
        text=text,
        attachments=attachments,
        reply_to=None
        if message.reply_to_message is None
        else str(message.reply_to_message.message_id),
        thread_id=None if message.message_thread_id is None else str(message.message_thread_id),
        ts=occurred,
        raw={},
        display_name=display_name,
        chat_title=_chat_title(message.chat),
    )


def split_text(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    """Режет длинный ответ на части, допустимые Bot API."""
    if not text:
        return [""]
    return [text[index : index + limit] for index in range(0, len(text), limit)]


def _canonical_command_text(text: str | None) -> str | None:
    if text is None:
        return None
    stripped = text.strip()
    if not stripped.startswith("/"):
        return stripped
    head, _, arguments = stripped.partition(" ")
    name = head[1:].split("@", 1)[0]
    if not arguments:
        return f"/{name}"
    return f"/{name} {arguments}"


def _display_name(first_name: str, last_name: str | None) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()


def _chat_title(chat: Chat) -> str | None:
    """Возвращает человекочитаемое имя чата без передачи типа платформы в ядро.

    У групп есть ``title``. Личный чат его не имеет, поэтому берётся имя
    собеседника. Пустое значение оставляет идентификатор как запасной
    вариант на стороне форматирования ``/chats``.
    """
    if chat.title:
        return chat.title
    first_name = chat.first_name or ""
    name = _display_name(first_name, chat.last_name)
    return name or None


def _attachments_from_message(message: Message) -> list[Attachment]:
    document = message.document
    if document is None or document.file_id is None:
        return []
    return [
        Attachment(
            id=document.file_id,
            kind="file",
            filename=document.file_name,
            mime_type=document.mime_type,
            size=document.file_size,
            metadata={"file_id": document.file_id},
        )
    ]


class TelegramAdapter:
    """Реализует ChannelAdapter для Telegram через long polling."""

    platform = TELEGRAM_SOURCE
    capabilities = Capabilities(
        buttons=True,
        markdown=True,
        max_text_len=TELEGRAM_TEXT_LIMIT,
        files=True,
        threads=True,
        message_edit=True,
    )

    def __init__(
        self,
        settings: TelegramSettings,
        bot: Bot | None = None,
        dispatcher: Dispatcher | None = None,
    ) -> None:
        """Создаёт адаптер; сеть не открывается до ``start``."""
        if settings.telegram_bot_token is None:
            raise ValueError("Токен Telegram не задан")
        self._settings = settings
        self._bot = bot or Bot(token=settings.telegram_bot_token.get_secret_value())
        self._dispatcher = dispatcher or Dispatcher()
        self._on_event: Callable[[InboundEvent], Awaitable[list[OutboundMessage]]] | None = None
        self._dispatcher.message.register(self._handle_message)

    async def start(
        self,
        on_event: Callable[[InboundEvent], Awaitable[list[OutboundMessage]]],
    ) -> None:
        """Запускает long polling и передаёт события в оркестратор.

        ``handle_signals=False`` нужен, чтобы не перехватывать сигналы uvicorn.
        """
        self._on_event = on_event
        await self._bot.delete_webhook(drop_pending_updates=False)
        await logger.ainfo("telegram_polling_started")
        await self._dispatcher.start_polling(self._bot, handle_signals=False)

    async def stop(self) -> None:
        """Останавливает polling и закрывает HTTP-сессию бота."""
        await self._dispatcher.stop_polling()
        await self._bot.session.close()
        await logger.ainfo("telegram_polling_stopped")

    async def send(self, msg: OutboundMessage) -> None:
        """Отправляет текст частями и вложения-файлы из метаданных экспорта."""
        chat_id = int(msg.chat_id)
        chunks = split_text(msg.text, self.capabilities.max_text_len)
        reply_to = None if msg.reply_to is None else int(msg.reply_to)
        for chunk in chunks:
            await self._send_text(chat_id, chunk, reply_to, msg.format)
            reply_to = None
        for attachment in msg.attachments:
            payload = attachment.metadata.get("content")
            if not isinstance(payload, str) or attachment.filename is None:
                continue
            document = BufferedInputFile(payload.encode("utf-8"), filename=attachment.filename)
            await self._bot.send_document(chat_id=chat_id, document=document)

    async def download(self, attachment: Attachment) -> bytes:
        """Скачивает файл Telegram по ``file_id`` из метаданных вложения."""
        file_id = attachment.metadata.get("file_id")
        if not isinstance(file_id, str) or not file_id:
            raise ValueError("Вложение не содержит file_id")
        buffer = BytesIO()
        await self._bot.download(file_id, destination=buffer)
        return buffer.getvalue()

    async def publish_commands(self, commands: list[CommandSpec]) -> None:
        """Публикует меню команд через setMyCommands."""
        bot_commands = [
            BotCommand(command=command.name, description=command.description_ru[:256])
            for command in commands or list(COMMANDS)
        ]
        await self._bot.set_my_commands(bot_commands)

    async def is_member(self, chat: ChatRef) -> bool | None:
        """Проверяет, состоит ли бот в уже известном чате Telegram.

        Bot API не отдаёт полный список групп. ``getChatMember`` работает
        только для чата, чей идентификатор уже есть в привязке. Чужой
        ``source`` возвращает ``None``, чтобы оркестратор спросил другой
        адаптер. Ошибки доступа трактуются как «бота в чате нет», а не как
        неизвестность: это типичный ответ после кика или удаления группы.
        """
        if chat.source != TELEGRAM_SOURCE:
            return None
        try:
            chat_id = int(chat.external_chat_id)
        except ValueError:
            return False
        try:
            member = await self._bot.get_chat_member(chat_id, self._bot.id)
        except (TelegramBadRequest, TelegramForbiddenError):
            return False
        return member.status in _ACTIVE_MEMBER_STATUSES

    async def _send_text(
        self,
        chat_id: int,
        text: str,
        reply_to: int | None,
        text_format: str,
    ) -> None:
        """Отправляет текст; при ошибке разметки повторяет сообщение как plain."""
        parse_mode = ParseMode.MARKDOWN if text_format == "markdown" else None
        if parse_mode is None:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to,
            )
            return
        try:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to,
                parse_mode=parse_mode,
            )
        except TelegramBadRequest:
            await self._bot.send_message(
                chat_id=chat_id,
                text=text,
                reply_to_message_id=reply_to,
            )

    async def _handle_message(self, message: Message) -> None:
        if self._on_event is None:
            return
        event = inbound_event_from_message(message)
        await logger.ainfo(
            "telegram_message_received",
            chat_id=event.chat_id,
            message_id=event.message_id,
        )
        replies = await self._on_event(event)
        for reply in replies:
            await self.send(reply)

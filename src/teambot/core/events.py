"""Канонические события каналов, не зависящие от конкретной платформы.

Модуль образует границу между адаптерами и ядром по контрактам раздела 6
ARCHITECTURE.md. Сырые данные сохраняются для диагностики, но запрещены к
передаче в логи.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal

type JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


@dataclass(frozen=True, slots=True)
class Attachment:
    """Описывает вложение без платформенных деталей.

    Атрибуты:
        id: Непрозрачный идентификатор вложения в исходном канале.
        kind: Унифицированный вид содержимого.
        filename: Исходное имя файла, если оно известно.
        mime_type: MIME-тип, заявленный платформой.
        size: Размер в байтах, если он известен.
        metadata: Дополнительные данные, необходимые адаптеру для скачивания.
    """

    id: str
    kind: Literal["file", "image", "audio", "video", "other"] = "file"
    filename: str | None = None
    mime_type: str | None = None
    size: int | None = None
    metadata: dict[str, JsonValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Button:
    """Описывает переносимую кнопку ответа.

    Атрибуты:
        text: Текст, который видит пользователь.
        value: Непрозрачное значение, возвращаемое адаптером в ядро.
        url: Внешняя ссылка; взаимоисключающая с интерактивным значением.
    """

    text: str
    value: str | None = None
    url: str | None = None


@dataclass(frozen=True, slots=True)
class InboundEvent:
    """Представляет нормализованное входящее сообщение.

    Пара ``platform``, ``chat_id`` и ``message_id`` служит ключом
    идемпотентности. Поле ``ts`` должно содержать aware-время в UTC.
    ``chat_title`` — человекочитаемое имя чата от адаптера, без типа
    платформы; ядро сохраняет его при привязке для ``/chats``.
    """

    platform: str
    chat_id: str
    message_id: str
    platform_user_id: str
    text: str | None
    attachments: list[Attachment]
    reply_to: str | None
    thread_id: str | None
    ts: datetime
    raw: dict[str, JsonValue]
    display_name: str | None = None
    chat_title: str | None = None


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """Представляет независимое от платформы исходящее сообщение."""

    chat_id: str
    text: str
    format: Literal["plain", "markdown"] = "plain"
    buttons: list[Button] = field(default_factory=list)
    reply_to: str | None = None
    attachments: list[Attachment] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class Capabilities:
    """Фиксирует возможности канала для мягкой деградации ответа."""

    buttons: bool
    markdown: bool
    max_text_len: int
    files: bool
    threads: bool
    message_edit: bool

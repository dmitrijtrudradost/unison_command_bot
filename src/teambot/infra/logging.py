"""Безопасная настройка структурных логов приложения.

Процессор рекурсивно удаляет секреты, содержимое сообщений, транскрипты и
сырые payload до сериализации (ARCHITECTURE.md, раздел 13). Защита действует
одинаково для словарей, последовательностей и вложенных структур.
"""

import logging
from collections.abc import Mapping, MutableMapping, Sequence
from typing import Any

import structlog

REDACTED = "<redacted>"
_SENSITIVE_KEY_PARTS = frozenset(
    {
        "api_key",
        "authorization",
        "body",
        "content",
        "cookie",
        "message",
        "password",
        "personal",
        "prompt",
        "raw",
        "secret",
        "text",
        "token",
        "transcript",
    }
)


def _is_sensitive_key(key: object) -> bool:
    """Проверяет имя поля по закрытому набору чувствительных признаков."""
    normalized = str(key).casefold().replace("-", "_")
    return any(part in normalized for part in _SENSITIVE_KEY_PARTS)


def sanitize(value: object) -> object:
    """Рекурсивно заменяет значения чувствительных полей безопасным маркером.

    Аргументы:
        value: Произвольная структура, предназначенная для записи в лог.

    Возвращает:
        Новую безопасную структуру; исходные коллекции не изменяются.
    """
    if isinstance(value, Mapping):
        return {
            str(key): REDACTED if _is_sensitive_key(key) else sanitize(item)
            for key, item in value.items()
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [sanitize(item) for item in value]
    return value


def sanitize_event(
    _logger: object,
    _method_name: str,
    event_dict: MutableMapping[str, Any],
) -> Mapping[str, Any]:
    """Очищает событие structlog перед передачей следующим процессорам."""
    sanitized = sanitize(dict(event_dict))
    if not isinstance(sanitized, dict):  # pragma: no cover — контракт structlog.
        raise TypeError("Событие structlog должно быть словарём")
    return sanitized


def configure_logging(level: str = "INFO") -> None:
    """Настраивает JSON-логи процесса с предварительной санитизацией.

    Аргументы:
        level: Стандартное имя минимального уровня логирования.

    Исключения:
        ValueError: Передано неизвестное имя уровня.
    """
    numeric_level = logging.getLevelNamesMapping().get(level.upper())
    if numeric_level is None:
        raise ValueError(f"Неизвестный уровень логирования: {level}")

    logging.basicConfig(level=numeric_level, format="%(message)s")
    structlog.configure(
        processors=[
            sanitize_event,
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.format_exc_info,
            structlog.processors.JSONRenderer(ensure_ascii=False),
        ],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(),
        cache_logger_on_first_use=True,
    )

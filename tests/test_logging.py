"""Проверки рекурсивной защиты чувствительных данных в логах."""

from teambot.infra.logging import REDACTED, sanitize


def test_sanitize_redacts_nested_sensitive_fields() -> None:
    payload: dict[str, object] = {
        "message_text": "секретный текст",
        "items": [{"api-key": "secret"}, {"safe_id": "42"}],
    }
    source: dict[str, object] = {
        "event": "received",
        "payload": payload,
    }

    assert sanitize(source) == {
        "event": "received",
        "payload": {
            "message_text": REDACTED,
            "items": [{"api-key": REDACTED}, {"safe_id": "42"}],
        },
    }
    assert payload["message_text"] == "секретный текст"

"""Проверки типизированных настроек без платформенных секретов в ядре."""

from pathlib import Path

from pytest import MonkeyPatch

from teambot.infra.config import Settings


def test_integration_settings_are_loaded_without_exposing_secrets(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("PROXYAPI_KEY", "proxy-secret")
    monkeypatch.setenv("INITIAL_TEAM_NAME", "Альфа")

    settings = Settings()

    assert settings.proxyapi_base_url == "https://api.proxyapi.ru/v1"
    assert settings.initial_team_name == "Альфа"
    assert settings.proxyapi_key is not None
    assert settings.proxyapi_key.get_secret_value() == "proxy-secret"
    assert "proxy-secret" not in repr(settings)
    assert not hasattr(settings, "telegram_bot_token")


def test_empty_optional_integration_values_become_none(
    monkeypatch: MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.chdir(tmp_path)
    for name in (
        "PROXYAPI_KEY",
        "ZAI_API_KEY",
        "GIGACHAT_API_KEY",
        "LOCAL_LLM_URL",
        "HF_TOKEN",
    ):
        monkeypatch.setenv(name, "  ")

    settings = Settings()

    assert settings.proxyapi_key is None
    assert settings.zai_api_key is None
    assert settings.gigachat_api_key is None
    assert settings.local_llm_url is None
    assert settings.hf_token is None

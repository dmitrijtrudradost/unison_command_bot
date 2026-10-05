"""Типизированная конфигурация приложения из переменных окружения.

Модуль реализует правило хранения секретов из раздела 13 ARCHITECTURE.md.
Файл ``.env`` предназначен только для локальной разработки и не коммитится.
"""

from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Содержит настройки каркаса M0 с проверкой типов и ограничений."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
        frozen=True,
    )

    app_env: Literal["development", "test", "production"] = "development"
    app_host: str = "127.0.0.1"
    app_port: int = Field(default=8000, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    database_url: str = "sqlite+aiosqlite:///./data/teambot.db"
    sqlite_busy_timeout_ms: int = Field(default=5000, ge=0)
    sqlite_backup_dir: str = "./data/backups"
    sqlite_backup_cron: str = "0 3 * * *"
    retention_audio_days: int = Field(default=30, ge=1)
    initial_team_name: str = Field(default="Команда", min_length=1, max_length=200)
    access_code_ttl_minutes: int = Field(default=15, ge=1, le=24 * 60)

    proxyapi_base_url: str = "https://api.proxyapi.ru/v1"
    proxyapi_key: SecretStr | None = None
    zai_api_key: SecretStr | None = None
    gigachat_api_key: SecretStr | None = None
    local_llm_url: str | None = None
    hf_token: SecretStr | None = None

    @field_validator(
        "proxyapi_key",
        "zai_api_key",
        "gigachat_api_key",
        "local_llm_url",
        "hf_token",
        mode="before",
    )
    @classmethod
    def empty_optional_value_as_none(cls, value: object) -> object:
        """Преобразует пустое значение из шаблона окружения в ``None``."""
        if isinstance(value, str) and not value.strip():
            return None
        return value


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Загружает и кеширует настройки процесса.

    Возвращает:
        Валидированный неизменяемый в рамках процесса объект настроек.

    Исключения:
        pydantic.ValidationError: Переменная окружения имеет неверный тип.
    """
    return Settings()

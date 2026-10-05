"""Фабрика FastAPI и служебные проверки состояния M0.

HTTP-слой не обращается к хранилищу напрямую (DB-1). Проверка готовности
получает абстрактную асинхронную пробу из точки сборки приложения.
"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import TypedDict

import structlog
from fastapi import FastAPI, HTTPException, status

type ReadinessProbe = Callable[[], Awaitable[bool]]
type LifecycleHook = Callable[[], Awaitable[None]]

logger = structlog.get_logger(__name__)


class StatusResponse(TypedDict):
    """Описывает стабильный JSON-ответ служебных маршрутов."""

    status: str


def create_app(
    readiness_probe: ReadinessProbe | None = None,
    startup: LifecycleHook | None = None,
    shutdown: LifecycleHook | None = None,
) -> FastAPI:
    """Создаёт HTTP-приложение с проверками жизни и готовности.

    Аргументы:
        readiness_probe: Необязательная проба собранных инфраструктурных
            зависимостей. Возвращает ``True``, когда приложение готово.
        startup: Необязательный асинхронный запуск собранных адаптеров.
        shutdown: Необязательная асинхронная остановка собранных адаптеров.

    Возвращает:
        Настроенный экземпляр FastAPI.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """Запускает и останавливает собранные адаптеры процесса."""
        if startup is not None:
            await startup()
        app.state.started = True
        try:
            yield
        finally:
            app.state.started = False
            if shutdown is not None:
                await shutdown()

    app = FastAPI(title="Team Bot", version="0.1.0", lifespan=lifespan)
    app.state.started = False

    @app.get("/healthz", tags=["system"])
    async def healthz() -> StatusResponse:
        """Подтверждает, что HTTP-процесс работает."""
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    async def readyz() -> StatusResponse:
        """Проверяет завершение запуска и доступность собранных зависимостей."""
        ready = bool(app.state.started)
        if ready and readiness_probe is not None:
            try:
                ready = await readiness_probe()
            except Exception as error:
                # В лог попадает только тип исключения: тексты драйверов могут
                # содержать адреса и реквизиты подключения.
                await logger.awarning("readiness_probe_failed", error_type=type(error).__name__)
                ready = False
        if not ready:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Приложение ещё не готово",
            )
        return {"status": "ready"}

    return app

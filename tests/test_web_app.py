"""Проверки служебных HTTP-маршрутов каркаса."""

from httpx import ASGITransport, AsyncClient

from teambot.web.app import create_app


async def test_health_and_readiness() -> None:
    async def ready() -> bool:
        return True

    app = create_app(ready)
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            health = await client.get("/healthz")
            readiness = await client.get("/readyz")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert readiness.status_code == 200
    assert readiness.json() == {"status": "ready"}


async def test_readiness_reports_unavailable_dependency() -> None:
    async def not_ready() -> bool:
        return False

    app = create_app(not_ready)
    transport = ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/readyz")

    assert response.status_code == 503

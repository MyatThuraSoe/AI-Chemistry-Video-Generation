"""FastAPI application factory."""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.errors import register_exception_handlers
from app.api.middleware import register_middleware
from app.api.routes import public_router, v1_router
from app.config import Settings
from app.container import Container
from app.observability.logging import configure_logging

logger = logging.getLogger(__name__)


def create_app(
    settings: Settings | None = None,
    *,
    container: Container | None = None,
) -> FastAPI:
    resolved_settings = settings or (container.settings if container else Settings())
    configure_logging(resolved_settings)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_container = app.state.container
        if active_container is None:
            active_container = Container(app.state.settings)
            app.state.container = active_container
        active_container.log_startup()
        if (
            active_container.settings.worker_mode == "embedded"
            and active_container.worker_pool is not None
        ):
            await active_container.start_workers()
        try:
            yield
        finally:
            await active_container.shutdown()

    app = FastAPI(
        title="Chemistry Video Service",
        version=resolved_settings.pipeline_version,
        description=(
            "Asynchronous backend that generates validated, narrated chemistry explainer videos."
        ),
        lifespan=lifespan,
    )
    app.state.settings = resolved_settings
    app.state.container = container

    register_exception_handlers(app)
    register_middleware(app)
    app.include_router(public_router)
    app.include_router(v1_router)
    return app


app = create_app()


__all__ = ["app", "create_app"]

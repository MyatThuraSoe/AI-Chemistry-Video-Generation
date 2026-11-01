"""FastAPI dependencies: container access, authentication and rate limiting."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, Request

from app.container import Container
from app.domain.errors import RateLimitedError, UnauthorizedError
from app.services.job_service import JobService


def get_container(request: Request) -> Container:
    container: Container | None = getattr(request.app.state, "container", None)
    if container is None:
        raise RuntimeError("Application container is not initialized")
    return container


def get_job_service(
    container: Annotated[Container, Depends(get_container)],
) -> JobService:
    return container.job_service


def require_api_key(
    request: Request,
    x_api_key: Annotated[str | None, Header(alias="X-API-Key")] = None,
) -> None:
    container = get_container(request)
    expected = container.settings.api_key
    if expected and x_api_key != expected:
        raise UnauthorizedError()


def enforce_rate_limit(request: Request) -> None:
    container = get_container(request)
    limiter = container.rate_limiter
    if not limiter.enabled:
        return
    client = request.client.host if request.client else "unknown"
    retry_after = limiter.check(client)
    if retry_after is not None:
        raise RateLimitedError(retry_after)


JobServiceDep = Annotated[JobService, Depends(get_job_service)]

__all__ = [
    "JobServiceDep",
    "enforce_rate_limit",
    "get_container",
    "get_job_service",
    "require_api_key",
]

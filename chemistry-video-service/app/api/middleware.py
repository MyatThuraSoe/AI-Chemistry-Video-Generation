"""HTTP middleware: request IDs, structured access logs and body-size limits."""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from app.domain.errors import ErrorBody, ErrorCode, ErrorResponse
from app.observability.logging import log_event, request_id_var

logger = logging.getLogger(__name__)

REQUEST_ID_HEADER = "X-Request-ID"


def register_middleware(app: FastAPI) -> None:
    max_bytes = app.state.settings.max_request_bytes

    @app.middleware("http")
    async def request_context(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_var.set(request_id)
        client_ip = request.client.host if request.client else None
        started = time.perf_counter()
        log_event(
            logger,
            "request_received",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            client_ip=client_ip,
        )

        content_length = request.headers.get("content-length")
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                declared = 0
            if declared > max_bytes:
                body = ErrorResponse(
                    error=ErrorBody(
                        code=ErrorCode.REQUEST_TOO_LARGE,
                        message="The request body is larger than the configured limit.",
                        retryable=False,
                        details={"max_request_bytes": max_bytes},
                    )
                ).model_dump(mode="json", exclude_none=True)
                response: Response = JSONResponse(status_code=413, content=body)
                response.headers[REQUEST_ID_HEADER] = request_id
                log_event(
                    logger,
                    "request_completed",
                    request_id=request_id,
                    method=request.method,
                    path=request.url.path,
                    status_code=413,
                    duration_ms=int((time.perf_counter() - started) * 1000),
                )
                request_id_var.reset(token)
                return response

        try:
            response = await call_next(request)
        except Exception:
            log_event(
                logger,
                "request_completed",
                level=logging.ERROR,
                request_id=request_id,
                method=request.method,
                path=request.url.path,
                status_code=500,
                duration_ms=int((time.perf_counter() - started) * 1000),
            )
            request_id_var.reset(token)
            raise

        response.headers[REQUEST_ID_HEADER] = request_id
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        log_event(
            logger,
            "request_completed",
            request_id=request_id,
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=int((time.perf_counter() - started) * 1000),
        )
        request_id_var.reset(token)
        return response


__all__ = ["register_middleware"]

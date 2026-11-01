"""Uniform error responses. Internal details never reach API clients."""

from __future__ import annotations

import logging
from collections.abc import Mapping

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.responses import Response

from app.domain.errors import AppError, ErrorBody, ErrorCode, ErrorResponse, RateLimitedError

logger = logging.getLogger(__name__)


def _error_response(
    status_code: int,
    body: ErrorBody,
    *,
    headers: Mapping[str, str] | None = None,
) -> JSONResponse:
    payload = ErrorResponse(error=body).model_dump(mode="json", exclude_none=True)
    return JSONResponse(status_code=status_code, content=payload, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        headers: dict[str, str] = {}
        if isinstance(exc, RateLimitedError) and exc.details:
            headers["Retry-After"] = str(exc.details.get("retry_after_seconds", 60))
        return _error_response(exc.http_status, exc.to_body(), headers=headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = []
        for item in exc.errors():
            location = [str(part) for part in item.get("loc", ()) if part != "body"]
            errors.append(
                {
                    "field": ".".join(location) or "body",
                    "message": item.get("msg", "Invalid value"),
                    "type": item.get("type", "value_error"),
                }
            )
        first = errors[0] if errors else {"field": "body", "message": "Invalid request"}
        if first["type"] == "missing":
            message = f"Field '{first['field']}' is required."
        else:
            message = f"Field '{first['field']}': {first['message']}."
        return _error_response(
            400,
            ErrorBody(
                code=ErrorCode.INVALID_REQUEST,
                message=message,
                retryable=False,
                details={"errors": errors},
            ),
        )

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        request: Request,
        exc: StarletteHTTPException,
    ) -> Response:
        if exc.status_code == 404:
            body = ErrorBody(
                code=ErrorCode.INVALID_REQUEST,
                message="The requested endpoint does not exist.",
                retryable=False,
            )
        else:
            body = ErrorBody(
                code=ErrorCode.INVALID_REQUEST,
                message=str(exc.detail),
                retryable=False,
            )
        return _error_response(exc.status_code, body, headers=exc.headers)

    @app.exception_handler(Exception)
    async def handle_unexpected(
        request: Request,
        exc: Exception,
    ) -> JSONResponse:
        logger.exception(
            "Unhandled exception while serving %s %s",
            request.method,
            request.url.path,
            extra={
                "event": "unhandled_request_error",
                "method": request.method,
                "path": request.url.path,
            },
        )
        return _error_response(
            500,
            ErrorBody(
                code=ErrorCode.INTERNAL_ERROR,
                message="An unexpected internal error occurred.",
                retryable=True,
            ),
        )


__all__ = ["register_exception_handlers"]

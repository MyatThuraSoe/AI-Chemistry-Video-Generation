"""Structured JSON logging and request correlation."""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any

from app.config import Settings

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
job_id_var: ContextVar[str | None] = ContextVar("job_id", default=None)

_LOG_EXTRA_FIELDS = (
    "request_id",
    "job_id",
    "concept_id",
    "stage",
    "progress",
    "duration_ms",
    "attempt",
    "error_code",
    "status_code",
    "method",
    "path",
    "client_ip",
)


class JsonLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "level": record.levelname.lower(),
            "event": getattr(record, "event", record.getMessage()),
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", None) or request_id_var.get()
        if request_id:
            payload["request_id"] = request_id
        job_id = getattr(record, "job_id", None) or job_id_var.get()
        if job_id:
            payload["job_id"] = job_id
        for key in _LOG_EXTRA_FIELDS:
            if key in {"request_id", "job_id"}:
                continue
            value = getattr(record, key, None)
            if value is not None:
                payload[key] = value
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


class TextLogFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        event = getattr(record, "event", None)
        base = f"{self.formatTime(record, '%H:%M:%S')} {record.levelname:<7} {record.name}"
        if event:
            base += f" event={event}"
        message = record.getMessage()
        if message and message != event:
            base += f" message={message}"
        for key in _LOG_EXTRA_FIELDS:
            value = getattr(record, key, None)
            if value is not None:
                base += f" {key}={value}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def configure_logging(settings: Settings) -> None:
    root = logging.getLogger()
    for handler in list(root.handlers):
        if getattr(handler, "_chemistry_service", False):
            root.removeHandler(handler)
            handler.close()
    handler = logging.StreamHandler(sys.stdout)
    handler._chemistry_service = True  # type: ignore[attr-defined]
    handler.setFormatter(
        JsonLogFormatter() if settings.log_format == "json" else TextLogFormatter()
    )
    root.addHandler(handler)
    root.setLevel(settings.log_level)
    for name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


def log_event(
    logger: logging.Logger,
    event: str,
    *,
    level: int = logging.INFO,
    message: str | None = None,
    exc_info: bool = False,
    **fields: Any,
) -> None:
    """Log a structured event without accidentally overwriting LogRecord fields."""
    reserved = set(logging.LogRecord("", 0, "", 0, "", (), None).__dict__)
    extra = {"event": event}
    for key, value in fields.items():
        if key in reserved or key in {"event", "message"}:
            continue
        extra[key] = value
    logger.log(level, message or event, extra=extra, exc_info=exc_info)

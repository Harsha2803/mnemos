"""Structured logging.

JSON in every environment except local, where a human is reading the terminal.
The request id is bound to a contextvar at the middleware boundary, so every log
line emitted anywhere downstream carries it without being passed around.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
org_id_var: ContextVar[str | None] = ContextVar("org_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)


def _bind_context(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    for key, var in (
        ("request_id", request_id_var),
        ("org_id", org_id_var),
        ("user_id", user_id_var),
    ):
        value = var.get()
        if value is not None:
            event[key] = value
    return event


def configure_logging(*, level: str = "INFO", json_output: bool = True) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _bind_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    processors.append(
        structlog.processors.JSONRenderer()
        if json_output
        else structlog.dev.ConsoleRenderer(colors=True)
    )

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[level.upper()]
        ),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stdout),
        cache_logger_on_first_use=True,
    )

    # Route stdlib loggers (uvicorn, sqlalchemy, alembic) through the same sink so
    # a single container log stream is uniformly parseable.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]

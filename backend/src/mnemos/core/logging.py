"""Structured logging.

JSON in every environment except local, where a human is reading the terminal.
The request id is bound to a contextvar at the middleware boundary, so every log
line emitted anywhere downstream carries it without being passed around.

**Per-session log files, opt-in.** When a caller's session is resolved
(`entrypoints/api/security.py`'s guard), its id is bound to `session_id_var` the
same way. If `session_log_enabled` is on, every log line carrying a session id —
which, once bound, is every line for the rest of that request — is *also*
appended, as its own JSON line, to `{session_log_dir}/{session_id}.log`. This is
a developer convenience for finding "what did this login session do", not a
product feature: off by default (so `pytest` — which authenticates hundreds of
throwaway sessions — never touches the working tree), on only where
`docker-compose.yml` sets `MNEMOS_SESSION_LOG_ENABLED`, and the directory it
writes to is gitignored.
"""

from __future__ import annotations

import json
import logging
import sys
from contextvars import ContextVar
from pathlib import Path
from typing import Any, Final

import structlog

request_id_var: ContextVar[str | None] = ContextVar("request_id", default=None)
org_id_var: ContextVar[str | None] = ContextVar("org_id", default=None)
user_id_var: ContextVar[str | None] = ContextVar("user_id", default=None)
session_id_var: ContextVar[str | None] = ContextVar("session_id", default=None)

#: Relative to the process's working directory — `/app` in every container, which
#: `docker-compose.yml` bind-mounts from the repo's own `./logs` for the services
#: that resolve a session (`api`, `realtime`), so a file written here lands
#: directly in the working tree at `logs/sessions/`. Tests that turn the feature
#: on for a single case must pass their own `tmp_path`-based `session_log_dir`
#: rather than relying on this default, precisely so a test run never writes here.
SESSION_LOG_DIR: Final = Path("logs/sessions")


def _bind_context(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
    for key, var in (
        ("request_id", request_id_var),
        ("org_id", org_id_var),
        ("user_id", user_id_var),
        ("session_id", session_id_var),
    ):
        value = var.get()
        if value is not None:
            event[key] = value
    return event


def _session_log_writer(log_dir: Path) -> Any:
    """One JSON line per event, appended to the file named by that event's session.

    A plain `open(..., "a").write(...)` rather than a second `logging` handler: a
    handler would need its own formatter and its own filter to reproduce exactly
    the fields the main pipeline already assembled by this point in the chain
    (level, timestamp, request/org/user id), and would risk drifting from them.
    Placed *before* the renderer, so `event` is still the plain dict every other
    processor sees — this only reads it, and returns it unchanged for whichever
    renderer runs next.
    """

    def _write(_logger: Any, _name: str, event: dict[str, Any]) -> dict[str, Any]:
        session_id = event.get("session_id")
        if session_id:
            path = log_dir / f"{session_id}.log"
            with path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, default=str, sort_keys=True) + "\n")
        return event

    return _write


def configure_logging(
    *,
    level: str = "INFO",
    json_output: bool = True,
    session_log_enabled: bool = False,
    session_log_dir: Path = SESSION_LOG_DIR,
) -> None:
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _bind_context,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if session_log_enabled:
        session_log_dir.mkdir(parents=True, exist_ok=True)
        processors.append(_session_log_writer(session_log_dir))
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
        # `False`, not the more-common `True`: with caching on, a logger that has
        # already logged once locks onto whatever `structlog.configure()` said at
        # that moment and silently ignores every later call to this function —
        # `get_logger(__name__)` is evaluated once at import time, so any module
        # imported before a later `configure_logging()` call (every entrypoint
        # calls it fresh in its own `lifespan`, and the test suite constructs
        # several different apps per process) would keep the *first* process's
        # settings forever. This app is not high-throughput enough for the
        # per-call processor lookup this trades away to matter.
        cache_logger_on_first_use=False,
    )

    # Route stdlib loggers (uvicorn, sqlalchemy, alembic) through the same sink so
    # a single container log stream is uniformly parseable.
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level.upper())
    for noisy in ("uvicorn.access", "sqlalchemy.engine.Engine", "botocore", "boto3"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)  # type: ignore[no-any-return]

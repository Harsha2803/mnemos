"""nl2sql flow domain: pure text-shaping over an execution outcome. No
SQLAlchemy, no FastAPI, no I/O — the same discipline `features/*/domain`
follows."""

from __future__ import annotations

from mnemos.flows.nl2sql.domain.prompt import (
    NARRATION_SYSTEM_PROMPT,
    build_result_block,
    denial_narration,
    execution_error_narration,
)

__all__ = [
    "NARRATION_SYSTEM_PROMPT",
    "build_result_block",
    "denial_narration",
    "execution_error_narration",
]

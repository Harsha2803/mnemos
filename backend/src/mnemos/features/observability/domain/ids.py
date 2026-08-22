"""Typed identifier for the audit log. See `identity/domain/ids.py` for why
this is `NewType` rather than a bare `UUID`."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

AuditLogId = NewType("AuditLogId", UUID)

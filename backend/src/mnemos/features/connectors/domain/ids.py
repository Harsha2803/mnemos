"""Typed identifiers for the connectors domain. See `identity/domain/ids.py`
for why these are `NewType` rather than bare `UUID`."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

SourceId = NewType("SourceId", UUID)

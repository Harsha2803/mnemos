"""Typed identifiers for the knowledge domain. See `identity/domain/ids.py`
for why these are `NewType` rather than bare `UUID`."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

DocumentId = NewType("DocumentId", UUID)
ChunkId = NewType("ChunkId", UUID)

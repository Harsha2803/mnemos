"""Typed identifiers for the datasources domain. See `identity/domain/ids.py`
for why these are `NewType` rather than bare `UUID`."""

from __future__ import annotations

from typing import NewType
from uuid import UUID

DatasourceId = NewType("DatasourceId", UUID)
SqlRunId = NewType("SqlRunId", UUID)

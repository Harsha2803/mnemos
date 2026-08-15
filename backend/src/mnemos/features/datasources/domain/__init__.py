"""Datasources domain: pure types, no SQLAlchemy, no FastAPI, no I/O."""

from __future__ import annotations

from mnemos.features.datasources.domain.context import render_schema_context
from mnemos.features.datasources.domain.generation import (
    NL2SQL_SYSTEM_PROMPT,
    extract_sql_statement,
)
from mnemos.features.datasources.domain.glossary import GlossaryTermRow
from mnemos.features.datasources.domain.guard import GuardVerdict, guard_sql
from mnemos.features.datasources.domain.ids import DatasourceId, SqlRunId
from mnemos.features.datasources.domain.schema import (
    IntrospectedColumn,
    IntrospectedTable,
    SchemaObjectDraft,
    build_schema_objects,
)

__all__ = [
    "NL2SQL_SYSTEM_PROMPT",
    "DatasourceId",
    "GlossaryTermRow",
    "GuardVerdict",
    "IntrospectedColumn",
    "IntrospectedTable",
    "SchemaObjectDraft",
    "SqlRunId",
    "build_schema_objects",
    "extract_sql_statement",
    "guard_sql",
    "render_schema_context",
]

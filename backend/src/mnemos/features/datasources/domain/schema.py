"""Pure shaping of a warehouse's introspected schema into cacheable rows.

No SQLAlchemy, no `information_schema` SQL — those are `adapters/introspection.py`'s
job. This module only answers "given tables and columns, what rows does
`sql_schema_object` need", which is what makes it testable without a database.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class IntrospectedTable:
    schema_name: str
    table_name: str
    row_estimate: int | None


@dataclass(frozen=True, slots=True)
class IntrospectedColumn:
    schema_name: str
    table_name: str
    column_name: str
    data_type: str
    is_nullable: bool


@dataclass(frozen=True, slots=True)
class SchemaObjectDraft:
    """One row ready to upsert into `sql_schema_object`.

    Table-level rows (`column_name is None`) exist so a table with zero columns
    visible to the role — or simply the table's row estimate — is still
    represented; column-level rows carry the type information the generator
    needs to avoid guessing.
    """

    schema_name: str
    table_name: str
    column_name: str | None
    data_type: str | None
    is_nullable: bool | None
    row_estimate: int | None


def build_schema_objects(
    *, tables: list[IntrospectedTable], columns: list[IntrospectedColumn]
) -> list[SchemaObjectDraft]:
    """One table-level draft per table, carrying its row estimate, plus one
    column-level draft per column. Order is stable — table first, then its
    columns in the order they were introspected — because callers persist this
    list and a stable order makes a diff between two refreshes readable.
    """
    row_estimates = {(t.schema_name, t.table_name): t.row_estimate for t in tables}
    drafts: list[SchemaObjectDraft] = [
        SchemaObjectDraft(
            schema_name=t.schema_name,
            table_name=t.table_name,
            column_name=None,
            data_type=None,
            is_nullable=None,
            row_estimate=t.row_estimate,
        )
        for t in tables
    ]
    drafts.extend(
        SchemaObjectDraft(
            schema_name=c.schema_name,
            table_name=c.table_name,
            column_name=c.column_name,
            data_type=c.data_type,
            is_nullable=c.is_nullable,
            row_estimate=row_estimates.get((c.schema_name, c.table_name)),
        )
        for c in columns
    )
    return drafts

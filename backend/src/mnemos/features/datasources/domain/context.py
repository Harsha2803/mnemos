"""Render cached schema plus business glossary into the text block `A3`
deliverable 3's prompt assembles from.

Pure: no SQLAlchemy, no model call, no I/O — `DatasourceService.render_context`
is the only caller, and it does nothing but fetch the two lists this takes.
Deliberately not built in deliverable 1 (TRACKER §5): there was no glossary to
render yet, and a function with nothing to feed it is the placeholder rule 5
forbids.
"""

from __future__ import annotations

from mnemos.features.datasources.domain.glossary import GlossaryTermRow
from mnemos.features.datasources.domain.schema import SchemaObjectDraft


def render_schema_context(
    *, schema_objects: list[SchemaObjectDraft], glossary_terms: list[GlossaryTermRow]
) -> str:
    """Group `schema_objects` by table (the table-level row, then its columns,
    in the order deliverable 1 wrote them), then list the glossary. Glossary
    comes after the schema so the model reads the columns a term maps onto
    before it reads the term itself.
    """
    if not schema_objects and not glossary_terms:
        return ""

    sections: list[str] = []

    if schema_objects:
        table_order: list[tuple[str, str]] = []
        tables: dict[tuple[str, str], list[SchemaObjectDraft]] = {}
        for row in schema_objects:
            key = (row.schema_name, row.table_name)
            if key not in tables:
                tables[key] = []
                table_order.append(key)
            tables[key].append(row)

        table_blocks: list[str] = []
        for schema_name, table_name in table_order:
            rows = tables[(schema_name, table_name)]
            table_row = next((r for r in rows if r.column_name is None), None)
            estimate = (
                f" (~{table_row.row_estimate} rows)"
                if table_row is not None and table_row.row_estimate is not None
                else ""
            )
            column_lines = [
                f"- {r.column_name} ({r.data_type}{', nullable' if r.is_nullable else ''})"
                for r in rows
                if r.column_name is not None
            ]
            table_blocks.append(
                "\n".join([f"### {schema_name}.{table_name}{estimate}", *column_lines])
            )
        sections.append("\n\n".join(["## Schema", *table_blocks]))

    if glossary_terms:
        term_lines = []
        for t in glossary_terms:
            synonyms = f" (also: {', '.join(t.synonyms)})" if t.synonyms else ""
            expression = f" — `{t.sql_expression}`" if t.sql_expression else ""
            term_lines.append(f"- **{t.term}**{synonyms}: {t.definition}{expression}")
        sections.append("\n".join(["## Business glossary", *term_lines]))

    return "\n\n".join(sections) + "\n"

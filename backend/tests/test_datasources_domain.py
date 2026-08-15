"""Pure `features/datasources/domain` functions — no database, no I/O.

`build_schema_objects` is the one function here with a shape worth pinning
down: a table-level draft (`column_name is None`) per table, carrying that
table's row estimate, plus one column-level draft per column. Getting that
shape wrong is silent — the caller would still write *some* rows, just not
ones that round-trip correctly through `sql_schema_object`'s unique
constraint (`adapters/models.py`'s own docstring on why `column_name` is
nullable).
"""

from __future__ import annotations

from mnemos.features.datasources.domain import (
    GlossaryTermRow,
    IntrospectedColumn,
    IntrospectedTable,
    SchemaObjectDraft,
    build_schema_objects,
    render_schema_context,
)


def test_build_schema_objects_emits_one_table_row_and_one_row_per_column() -> None:
    tables = [IntrospectedTable(schema_name="analytics", table_name="region", row_estimate=4)]
    columns = [
        IntrospectedColumn(
            schema_name="analytics",
            table_name="region",
            column_name="region_id",
            data_type="integer",
            is_nullable=False,
        ),
        IntrospectedColumn(
            schema_name="analytics",
            table_name="region",
            column_name="region_name",
            data_type="text",
            is_nullable=False,
        ),
    ]

    drafts = build_schema_objects(tables=tables, columns=columns)

    assert len(drafts) == 3
    table_draft = drafts[0]
    assert table_draft.column_name is None
    assert table_draft.row_estimate == 4
    assert table_draft.data_type is None

    column_drafts = drafts[1:]
    assert {d.column_name for d in column_drafts} == {"region_id", "region_name"}
    # Column-level drafts inherit the table's row estimate too — a reader of
    # just the column rows should not have to join back to the table row to
    # know roughly how big the table is.
    assert all(d.row_estimate == 4 for d in column_drafts)


def test_build_schema_objects_handles_a_table_with_no_visible_columns() -> None:
    tables = [IntrospectedTable(schema_name="analytics", table_name="empty", row_estimate=0)]

    drafts = build_schema_objects(tables=tables, columns=[])

    assert len(drafts) == 1
    assert drafts[0].column_name is None
    assert drafts[0].table_name == "empty"


def test_build_schema_objects_leaves_row_estimate_null_for_an_unmatched_column() -> None:
    """A column whose table did not come back in the tables query (should not
    happen, but the join is a dict lookup, not an assumption) degrades to a
    null row estimate rather than raising."""
    columns = [
        IntrospectedColumn(
            schema_name="analytics",
            table_name="orphan",
            column_name="id",
            data_type="integer",
            is_nullable=False,
        )
    ]

    drafts = build_schema_objects(tables=[], columns=columns)

    assert len(drafts) == 1
    assert drafts[0].row_estimate is None


def test_build_schema_objects_is_empty_for_an_empty_warehouse() -> None:
    assert build_schema_objects(tables=[], columns=[]) == []


def test_render_schema_context_groups_columns_under_their_table_with_the_row_estimate() -> None:
    schema_objects = [
        SchemaObjectDraft(
            schema_name="analytics",
            table_name="region",
            column_name=None,
            data_type=None,
            is_nullable=None,
            row_estimate=4,
        ),
        SchemaObjectDraft(
            schema_name="analytics",
            table_name="region",
            column_name="region_id",
            data_type="integer",
            is_nullable=False,
            row_estimate=4,
        ),
        SchemaObjectDraft(
            schema_name="analytics",
            table_name="region",
            column_name="country",
            data_type="text",
            is_nullable=True,
            row_estimate=4,
        ),
    ]

    context = render_schema_context(schema_objects=schema_objects, glossary_terms=[])

    assert "## Schema" in context
    assert "### analytics.region (~4 rows)" in context
    assert "- region_id (integer)" in context
    assert "- country (text, nullable)" in context
    assert "## Business glossary" not in context


def test_render_schema_context_lists_glossary_terms_with_synonyms_and_expression() -> None:
    terms = [
        GlossaryTermRow(
            term="revenue",
            definition="Net amount collected for completed orders.",
            sql_expression="SUM(analytics.sales_order.net_amount)",
            synonyms=["sales", "income"],
        )
    ]

    context = render_schema_context(schema_objects=[], glossary_terms=terms)

    assert "## Business glossary" in context
    assert "**revenue**" in context
    assert "(also: sales, income)" in context
    assert "Net amount collected for completed orders." in context
    assert "`SUM(analytics.sales_order.net_amount)`" in context
    assert "## Schema" not in context


def test_render_schema_context_puts_schema_before_glossary() -> None:
    schema_objects = [
        SchemaObjectDraft(
            schema_name="analytics",
            table_name="region",
            column_name=None,
            data_type=None,
            is_nullable=None,
            row_estimate=None,
        )
    ]
    terms = [
        GlossaryTermRow(term="revenue", definition="Net sales.", sql_expression=None, synonyms=[])
    ]

    context = render_schema_context(schema_objects=schema_objects, glossary_terms=terms)

    assert context.index("## Schema") < context.index("## Business glossary")


def test_render_schema_context_is_empty_string_with_nothing_cached() -> None:
    assert render_schema_context(schema_objects=[], glossary_terms=[]) == ""


def test_render_schema_context_handles_a_table_with_no_visible_columns() -> None:
    schema_objects = [
        SchemaObjectDraft(
            schema_name="analytics",
            table_name="empty",
            column_name=None,
            data_type=None,
            is_nullable=None,
            row_estimate=0,
        )
    ]

    context = render_schema_context(schema_objects=schema_objects, glossary_terms=[])

    assert "### analytics.empty (~0 rows)" in context

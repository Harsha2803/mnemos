"""Datasources: the NL2SQL registry, its safety ledger, and business vocabulary.

`sql_run` records a verdict **per attempt**, not per question. The flow is
allowed to repair a failed query, and the interesting evidence is the rejected
first attempt — a table that only stores the final successful SQL throws away
the proof that the guard works.

`authorized_tables` and `denied_tables` are stored alongside so an audit can show
that an unauthorized table never even reached the bundle, rather than that it was
removed from the answer afterwards.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import SqlVerdict, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class SqlDatasource(Base, TimestampMixin):
    """A registered warehouse.

    The DSN is stored encrypted and the *read-only* credential is the only one
    the flow ever holds. The AST guard is the second line of defence; the first
    is that the role physically cannot write.
    """

    __tablename__ = "sql_datasource"
    __table_args__ = (
        UniqueConstraint("org_id", "slug", name="uq_sql_datasource_org_id_slug"),
        CheckConstraint("dialect IN ('postgres')", name="dialect_supported"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)

    # The `SqlDialect` port exists so adding Snowflake or BigQuery is an adapter
    # plus a row here. Only Postgres is implemented, because it is the only one
    # that is free.
    dialect: Mapped[str] = mapped_column(
        String(32), nullable=False, server_default=text("'postgres'")
    )
    dsn_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    read_only_role: Mapped[str] = mapped_column(Text, nullable=False)

    # Allowlist. Empty means "nothing", never "everything" — the default must be
    # deny or a misconfiguration becomes an exfiltration path.
    allowed_schemas: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    allowed_tables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    acl_tag_ids: Mapped[list[uuid.UUID]] = mapped_column(
        ARRAY(UUID(as_uuid=True)), nullable=False, server_default=text("'{}'::uuid[]")
    )

    statement_timeout_ms: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("15000")
    )
    max_rows: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("5000"))
    is_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("true"))
    introspected_at: Mapped[datetime | None] = mapped_column(nullable=True)


class SqlSchemaObject(Base):
    """Introspected schema, cached as retrievable claims.

    Schema is fed to the model through the same retrieval path as everything
    else, so a 400-table warehouse does not become a 200k-token prompt.
    """

    __tablename__ = "sql_schema_object"
    __table_args__ = (
        # Explicitly short: Postgres truncates identifiers at 63 bytes, and a
        # truncated constraint name is one that `downgrade()` cannot drop.
        UniqueConstraint(
            "datasource_id",
            "schema_name",
            "table_name",
            "column_name",
            name="uq_sql_schema_object_qualified_column",
        ),
        Index("ix_sql_schema_object_org_id_datasource_id", "org_id", "datasource_id"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sql_datasource.id", ondelete="CASCADE"), nullable=False
    )
    schema_name: Mapped[str] = mapped_column(Text, nullable=False)
    table_name: Mapped[str] = mapped_column(Text, nullable=False)
    # Null for a table-level row; set for a column-level row.
    column_name: Mapped[str | None] = mapped_column(Text, nullable=True)
    data_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_nullable: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    sample_values: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    row_estimate: Mapped[int | None] = mapped_column(Integer, nullable=True)
    introspected_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)


class GlossaryTerm(Base, TimestampMixin):
    """Business vocabulary. "Active customer" means something specific, and the
    model will invent a definition if nobody supplies one."""

    __tablename__ = "glossary_term"
    __table_args__ = (
        UniqueConstraint(
            "org_id", "datasource_id", "term", name="uq_glossary_term_org_id_datasource_id_term"
        ),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    datasource_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sql_datasource.id", ondelete="CASCADE"), nullable=True
    )
    term: Mapped[str] = mapped_column(Text, nullable=False)
    definition: Mapped[str] = mapped_column(Text, nullable=False)
    sql_expression: Mapped[str | None] = mapped_column(Text, nullable=True)
    synonyms: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )


class SqlRun(Base):
    """One generation attempt and what the guard decided about it."""

    __tablename__ = "sql_run"
    __table_args__ = (
        CheckConstraint(check_in("verdict", SqlVerdict), name="verdict_valid"),
        UniqueConstraint("message_id", "attempt", name="uq_sql_run_message_id_attempt"),
        Index("ix_sql_run_org_id_created_at", "org_id", "created_at"),
        Index("ix_sql_run_org_id_verdict", "org_id", "verdict"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    datasource_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("sql_datasource.id", ondelete="CASCADE"), nullable=False
    )
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("chat_message.id", ondelete="CASCADE"), nullable=True
    )
    attempt: Mapped[int] = mapped_column(Integer, nullable=False, server_default=text("1"))

    question: Mapped[str] = mapped_column(Text, nullable=False)
    generated_sql: Mapped[str] = mapped_column(Text, nullable=False)
    verdict: Mapped[str] = mapped_column(String(48), nullable=False)
    verdict_detail: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Proof that the guard walked the whole tree. A DML node hidden in a CTE or
    # the second branch of a UNION is the failure mode a regex-based check has.
    authorized_tables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )
    denied_tables: Mapped[list[str]] = mapped_column(
        JSONB, nullable=False, server_default=text("'[]'::jsonb")
    )

    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    row_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    truncated: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_detail: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"), nullable=False)

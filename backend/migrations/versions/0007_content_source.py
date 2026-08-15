"""content_source — registered connectors for B1's `SourceConnector` port:
where a source's content lives (an S3/MinIO bucket+prefix, a local-filesystem
root, or a curated HTTP URL list) and how to reach it, encrypted at rest the
same way `sql_datasource.dsn_encrypted` is.

The first migration since `M2`. RLS is applied directly in this revision
rather than deferred to a follow-up the way `0004`→`0006` needed two steps for
the tables that existed before the GUC-tolerance fix — this table is created
after that fix landed, so it gets the corrected policy expression
(`NULLIF(..., '')`) from the start, and `0004`/`0006` were frozen to a literal
table list precisely so they do not also try to touch this table before it
exists (see their own updated docstrings).

Revision ID: 0007
Revises: 0006
Created: 2026-08-15
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POLICY = "org_isolation"


def upgrade() -> None:
    op.create_table(
        "content_source",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("org_id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("config_encrypted", sa.LargeBinary(), nullable=False),
        sa.Column("is_enabled", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("last_listed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "kind IN ('minio', 's3', 'local_fs', 'http')",
            name=op.f("ck_content_source_kind_valid"),
        ),
        sa.ForeignKeyConstraint(
            ["org_id"], ["org.id"], name=op.f("fk_content_source_org_id_org"), ondelete="CASCADE"
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_content_source")),
        sa.UniqueConstraint("org_id", "slug", name="uq_content_source_org_id_slug"),
    )
    op.create_index(op.f("ix_content_source_org_id"), "content_source", ["org_id"], unique=False)

    op.execute("ALTER TABLE content_source ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_source FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON content_source
        USING (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
        WITH CHECK (org_id = NULLIF(current_setting('app.current_org', true), '')::uuid)
        """
    )


def downgrade() -> None:
    op.execute(f"DROP POLICY IF EXISTS {POLICY} ON content_source")
    op.execute("ALTER TABLE content_source NO FORCE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE content_source DISABLE ROW LEVEL SECURITY")
    op.drop_index(op.f("ix_content_source_org_id"), table_name="content_source")
    op.drop_table("content_source")

"""row-level security on every tenant-scoped table

Tenant isolation is a property of the database, not a convention in the service
layer. Every org-scoped table gets a policy keyed on the `app.current_org` GUC,
which `Database.session()` sets inside the transaction.

Two details carry the guarantee:

* **`FORCE ROW LEVEL SECURITY`.** Plain `ENABLE` exempts the table owner — and
  the application connects as the owner, so `ENABLE` alone would mean the policy
  never applies in the one process it exists to constrain.

* **`current_setting('app.current_org', true)`.** The `true` makes a missing
  setting return NULL rather than raise. `org_id = NULL` is NULL, never true, so
  a query that forgot to scope itself returns **zero rows**. The failure mode of
  forgetting is an empty page, not another tenant's data.

`org` itself is deliberately excluded: a user must be able to resolve their own
org row before the GUC can be set from it.

Not covered here, and stated so it is not mistaken for an oversight: RLS binds
the application role. A superuser, and anyone with `BYPASSRLS`, is unaffected.
The application role is neither.

Revision ID: 0004
Revises: 0003
Created: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mnemos.platform.models import ORG_SCOPED_TABLES

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen at the time this revision was written. Importing the live tuple would
# make an already-applied migration change meaning when a table is added later;
# a migration must describe the past, not track the present.
TABLES: tuple[str, ...] = ORG_SCOPED_TABLES

POLICY = "org_isolation"


def upgrade() -> None:
    for table in TABLES:
        op.execute(f"ALTER TABLE {table} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} FORCE ROW LEVEL SECURITY")
        op.execute(
            f"""
            CREATE POLICY {POLICY} ON {table}
            USING (org_id = current_setting('app.current_org', true)::uuid)
            WITH CHECK (org_id = current_setting('app.current_org', true)::uuid)
            """
        )

    # Migrations and the one-shot bootstrap need to write across orgs. A named
    # role with BYPASSRLS is the honest way to do that: the exemption is visible
    # in `pg_roles` and grantable, rather than hidden in a policy exception that
    # applies to everyone all the time.
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'mnemos_admin') THEN
                CREATE ROLE mnemos_admin NOLOGIN BYPASSRLS;
            END IF;
        END $$;
        """
    )


def downgrade() -> None:
    for table in reversed(TABLES):
        op.execute(f"DROP POLICY IF EXISTS {POLICY} ON {table}")
        op.execute(f"ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {table} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP ROLE IF EXISTS mnemos_admin")

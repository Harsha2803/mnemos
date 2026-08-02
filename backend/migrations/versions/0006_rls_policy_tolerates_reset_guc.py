"""make an unscoped query return zero rows instead of raising

Migration `0004` wrote the org-isolation policy as::

    org_id = current_setting('app.current_org', true)::uuid

and documented the intent: the `true` suppresses the "unrecognized parameter"
error, so a missing setting yields NULL, `org_id = NULL` is NULL rather than true,
and a query that forgot to scope itself returns zero rows. The failure mode of
forgetting was supposed to be an empty page, not a breach.

That holds only on a connection that has *never* been scoped. `set_config(...,
is_local => true)` reverts the value at the end of the transaction, but a
dot-qualified placeholder GUC, once assigned, remains **defined as the empty
string** rather than becoming undefined again. So on any connection that has
served one scoped request, `current_setting('app.current_org', true)` returns
`''`, and `''::uuid` raises `22P02 invalid input syntax for type uuid`.

Observed as `mnemos_app`, in this order on one connection::

    BEGIN; SELECT set_config('app.current_org', '<org>', true);
    SELECT count(*) FROM tag;   -- 1, correct
    COMMIT;
    SELECT count(*) FROM tag;   -- ERROR: invalid input syntax for type uuid: ""

Every connection in the pool is reused, so this is the ordinary case, not the
exotic one. The consequence is that forgetting to scope a query surfaces as an
intermittent 500 that depends on which pooled connection served the request —
and an error that appears under load and vanishes in a unit test is the most
expensive shape a bug can have.

`NULLIF(..., '')` collapses "never set" and "set and reverted" into the same NULL,
which is what `0004` intended and described. The security property is unchanged in
both revisions: neither version can ever match another tenant's rows. What changes
is that the documented failure mode is now the actual one.

Revision ID: 0006
Revises: 0005
Created: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mnemos.platform.models import ORG_SCOPED_TABLES

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Frozen at the time this revision was written, for the same reason 0004 freezes
# its own copy: a migration must describe the past, not track the present.
TABLES: tuple[str, ...] = ORG_SCOPED_TABLES

POLICY = "org_isolation"

TOLERANT = "NULLIF(current_setting('app.current_org', true), '')::uuid"
ORIGINAL = "current_setting('app.current_org', true)::uuid"


def _rewrite(expression: str) -> None:
    for table in TABLES:
        # ALTER POLICY replaces the expression in place, so no window exists in
        # which the table is readable without a policy.
        op.execute(
            f"""
            ALTER POLICY {POLICY} ON {table}
            USING (org_id = {expression})
            WITH CHECK (org_id = {expression})
            """
        )


def upgrade() -> None:
    _rewrite(TOLERANT)


def downgrade() -> None:
    _rewrite(ORIGINAL)

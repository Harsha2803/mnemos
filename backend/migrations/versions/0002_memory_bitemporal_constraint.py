"""bitemporal exclusion constraint on memory

The invariant: for a given (org, subject, predicate, scope), at most one *fact*
may be believed-live over any instant of world time.

`EXCLUDE USING gist` is the only way to state that in Postgres. A unique index
cannot express it, because the thing that must not collide is an *overlap of
ranges*, not an equality of values. `btree_gist` is what lets the scalar equality
columns sit in the same GiST index as the range column.

The constraint is partial in two ways, and both matter:

* `retracted_at IS NULL` — a retracted claim is history. History is allowed to
  overlap; that is the entire point of keeping it.
* `kind = 'fact'` — observations accumulate. "The user mentioned X on Tuesday"
  and "the user mentioned X again on Friday" are both true at once.

With this in place, application code that writes a new value without closing the
old one gets an integrity error instead of two live truths. The rule is enforced
where it cannot be forgotten.

Revision ID: 0002
Revises: 0001
Created: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CONSTRAINT_NAME = "ex_memory_one_live_fact_per_scope"


def upgrade() -> None:
    op.execute(
        f"""
        ALTER TABLE memory ADD CONSTRAINT {CONSTRAINT_NAME}
        EXCLUDE USING gist (
            org_id      WITH =,
            subject_id  WITH =,
            predicate   WITH =,
            scope_hash  WITH =,
            valid_range WITH &&
        )
        WHERE (retracted_at IS NULL AND kind = 'fact')
        """
    )

    # Supersession must form a DAG. A cycle would make "which claim is current"
    # unanswerable, and the retrieval path would loop resolving it.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION memory_edge_reject_cycle() RETURNS trigger AS $$
        BEGIN
            IF EXISTS (
                WITH RECURSIVE reachable(id) AS (
                    SELECT dst_id FROM memory_edge
                     WHERE src_id = NEW.dst_id AND kind = 'supersedes'
                    UNION
                    SELECT e.dst_id FROM memory_edge e
                      JOIN reachable r ON e.src_id = r.id
                     WHERE e.kind = 'supersedes'
                )
                SELECT 1 FROM reachable WHERE id = NEW.src_id
            ) THEN
                RAISE EXCEPTION
                    'supersession cycle: % -> % closes a loop', NEW.src_id, NEW.dst_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER memory_edge_no_cycle
        BEFORE INSERT OR UPDATE ON memory_edge
        FOR EACH ROW WHEN (NEW.kind = 'supersedes')
        EXECUTE FUNCTION memory_edge_reject_cycle();
        """
    )


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS memory_edge_no_cycle ON memory_edge")
    op.execute("DROP FUNCTION IF EXISTS memory_edge_reject_cycle()")
    op.execute(f"ALTER TABLE memory DROP CONSTRAINT IF EXISTS {CONSTRAINT_NAME}")

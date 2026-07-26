"""monthly partitions for inference_call

`inference_call` was created `PARTITION BY RANGE (occurred_at)` in 0001. A
partitioned table with no partitions accepts no rows, so the partitions have to
exist before the first request — creating them lazily on write is a race between
every concurrent request that arrives in a new month.

This revision creates the current month plus twelve ahead, and a `DEFAULT`
partition so a row can never be rejected for arriving outside the range. The
default is a safety net, not a plan: rows landing there are a signal that nobody
extended the window, which is what `mnemosctl db ensure-partitions` (run monthly)
is for.

Retention then becomes `DROP TABLE inference_call_2026_01` — instant, and it
returns the disk. A `DELETE` on an unpartitioned table of this shape leaves dead
tuples that vacuum has to chase.

Revision ID: 0003
Revises: 0002
Created: 2026-07-26
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Anchored, not `date.today()`: a migration must produce the same schema whenever
# it is run, or two environments migrated a month apart diverge.
FIRST_MONTH = date(2026, 1, 1)
MONTHS_AHEAD = 24


def _month_bounds(index: int) -> tuple[str, date, date]:
    year = FIRST_MONTH.year + (FIRST_MONTH.month - 1 + index) // 12
    month = (FIRST_MONTH.month - 1 + index) % 12 + 1
    start = date(year, month, 1)
    end = date(year + (month == 12), month % 12 + 1, 1)
    return f"inference_call_{year}_{month:02d}", start, end


def upgrade() -> None:
    for index in range(MONTHS_AHEAD):
        name, start, end = _month_bounds(index)
        op.execute(
            f"CREATE TABLE {name} PARTITION OF inference_call "
            f"FOR VALUES FROM ('{start}') TO ('{end}')"
        )
    op.execute("CREATE TABLE inference_call_default PARTITION OF inference_call DEFAULT")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS inference_call_default")
    for index in reversed(range(MONTHS_AHEAD)):
        name, _, _ = _month_bounds(index)
        op.execute(f"DROP TABLE IF EXISTS {name}")

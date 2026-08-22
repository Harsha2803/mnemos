"""chat_message_search — a generated `tsvector` column plus a GIN index over
`chat_message.content`, for `C3` deliverable 4's history search
(`SqlChatRepository.search_sessions`).

`GENERATED ALWAYS AS (...) STORED` rather than a trigger or an
application-maintained column: Postgres keeps it consistent with `content` on
every insert and update with no code on this side that could drift out of
sync with it. Reversible — dropping the column also drops the index that
depends on it, but the index is dropped explicitly first for a clean,
readable downgrade rather than relying on cascade.

Revision ID: 0008
Revises: 0007
Created: 2026-08-22
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE chat_message
        ADD COLUMN content_tsv tsvector
        GENERATED ALWAYS AS (to_tsvector('english', content)) STORED NOT NULL
        """
    )
    op.execute("CREATE INDEX ix_chat_message_content_tsv ON chat_message USING gin (content_tsv)")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_chat_message_content_tsv")
    op.execute("ALTER TABLE chat_message DROP COLUMN content_tsv")

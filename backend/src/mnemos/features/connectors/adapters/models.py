"""`content_source`: a registered connector — where content lives and how to
reach it, not the content itself. `config_encrypted` holds the connector-kind-
specific shape (an S3 bucket/prefix, a filesystem root, an HTTP URL list) as
Fernet-encrypted JSON, the same pattern `sql_datasource.dsn_encrypted` uses.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, LargeBinary, Text, UniqueConstraint
from sqlalchemy import text as sa_text
from sqlalchemy.orm import Mapped, mapped_column

from mnemos.core.types import ConnectorKind, check_in
from mnemos.platform.db import Base, TimestampMixin, org_fk, pk_column


class ContentSource(Base, TimestampMixin):
    __tablename__ = "content_source"
    __table_args__ = (
        CheckConstraint(check_in("kind", ConnectorKind), name="kind_valid"),
        UniqueConstraint("org_id", "slug", name="uq_content_source_org_id_slug"),
    )

    id: Mapped[uuid.UUID] = pk_column()
    org_id: Mapped[uuid.UUID] = org_fk()
    slug: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    config_encrypted: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)
    is_enabled: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=sa_text("true")
    )
    last_listed_at: Mapped[datetime | None] = mapped_column(nullable=True)

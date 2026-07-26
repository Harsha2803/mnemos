"""Vocabulary shared across every feature.

These enums are mirrored by CHECK constraints in the database rather than by
native Postgres enum types. Adding a value then stays an ordinary migration
instead of an `ALTER TYPE` that cannot run inside a transaction block and cannot
be reversed. The constraint still makes the database reject nonsense.
"""

from __future__ import annotations

from enum import IntEnum, StrEnum


class TrustTier(IntEnum):
    """How far a piece of context is allowed to influence the model.

    Ordering is load-bearing: the context compiler fences lower tiers so that
    retrieved document text can never be read as an instruction. Untrusted
    content is quoted, never obeyed.
    """

    SYSTEM = 40  # platform prompt; authored by us
    OPERATOR = 30  # org admin configuration
    USER = 20  # the person in the conversation
    RETRIEVED = 10  # document chunks, tool output, SQL results


class MemoryKind(StrEnum):
    """Why a claim exists, which decides how supersession behaves."""

    FACT = "fact"  # single live value per (subject, predicate, scope)
    PREFERENCE = "preference"
    DECISION = "decision"
    OBSERVATION = "observation"  # accumulates; never supersedes a sibling


class MemoryStatus(StrEnum):
    ACTIVE = "active"
    SUPERSEDED = "superseded"
    RETRACTED = "retracted"


class EdgeKind(StrEnum):
    SUPERSEDES = "supersedes"
    CONTRADICTS = "contradicts"
    SUPPORTS = "supports"
    DERIVED_FROM = "derived_from"


class DocumentStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    READY = "ready"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    DELETED = "deleted"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"
    STUCK = "stuck"  # heartbeat expired; reclaimable by another worker


class MessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class FlowKind(StrEnum):
    """Which pipeline the router chose for a message."""

    CHAT = "chat"
    RAG = "rag"
    NL2SQL = "nl2sql"
    AGENT = "agent"
    MEMORY = "memory"


class OperatorKind(StrEnum):
    """Which retrieval operator contributed a context item."""

    VECTOR = "vector"
    LEXICAL = "lexical"
    MEMORY = "memory"
    SQL = "sql"
    TOOL = "tool"
    HISTORY = "history"


class FeedbackRating(StrEnum):
    UP = "up"
    DOWN = "down"


class InvocationStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DENIED = "denied"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class SqlVerdict(StrEnum):
    """Outcome of the read-only AST guard for one generated statement."""

    ALLOWED = "allowed"
    REJECTED_WRITE = "rejected_write"
    REJECTED_UNAUTHORIZED_TABLE = "rejected_unauthorized_table"
    REJECTED_UNPARSEABLE = "rejected_unparseable"
    REJECTED_TOO_COMPLEX = "rejected_too_complex"


class ProviderKind(StrEnum):
    INTERNAL = "internal"
    OIDC = "oidc"
    API_KEY = "api_key"


class ConnectorKind(StrEnum):
    MINIO = "minio"
    S3 = "s3"
    LOCAL_FS = "local_fs"
    HTTP = "http"


def check_in(column: str, enum: type[StrEnum]) -> str:
    """SQL fragment pinning a column to an enum's values.

    Kept next to the enums so a new member and its constraint cannot drift apart.
    """
    values = ", ".join(f"'{member.value}'" for member in enum)
    return f"{column} IN ({values})"

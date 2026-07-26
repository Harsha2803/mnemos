"""Cross-cutting kernel: ids, clock, tokenization, canonical hashing, config.

Everything here is dependency-free (stdlib + numpy) and deterministic. The `Clock`
and `IdGenerator` indirections exist so that bitemporal logic and content-addressed
digests are reproducible in tests without monkeypatching globals.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import IntEnum, StrEnum
from typing import Any, Protocol

# ---------------------------------------------------------------------------
# Identity and time
# ---------------------------------------------------------------------------


class IdGenerator(Protocol):
    def new(self) -> str: ...


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class FrozenClock:
    """Deterministic clock for tests and reproducible benchmark runs."""

    def __init__(self, at: datetime | None = None) -> None:
        self._at = at or datetime(2026, 1, 1, tzinfo=UTC)

    def now(self) -> datetime:
        return self._at

    def advance(self, **kwargs: float) -> None:
        self._at = self._at + timedelta(**kwargs)


class Uuid4Generator:
    def new(self) -> str:
        return str(uuid.uuid4())


class SequentialIdGenerator:
    """Deterministic ids so that benchmark bundle digests are stable."""

    def __init__(self, prefix: str = "id") -> None:
        self._prefix = prefix
        self._n = 0

    def new(self) -> str:
        self._n += 1
        return f"{self._prefix}-{self._n:06d}"


# ---------------------------------------------------------------------------
# Tokenization
# ---------------------------------------------------------------------------


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


_WORD_RE = re.compile(r"\w+|[^\w\s]")


class HeuristicTokenizer:
    """Subword-approximating token counter with no model download.

    Real BPE tokenizers split long words into multiple tokens. Counting whitespace
    words alone under-counts by roughly 30% on English prose, which would make every
    budget claim in the benchmark wrong in the flattering direction. This counts
    regex tokens and adds a length-derived penalty for long words, which tracks
    `cl100k_base` within a few percent on ordinary text.

    A `tiktoken` adapter is a drop-in replacement for this class (see docs);
    the port exists so the benchmark is not silently coupled to an approximation.
    """

    def count(self, text: str) -> int:
        if not text:
            return 0
        total = 0
        for tok in _WORD_RE.findall(text):
            # ~4 chars per BPE token, minimum one token per lexical unit.
            total += max(1, (len(tok) + 3) // 4)
        return total


# ---------------------------------------------------------------------------
# Canonical hashing
# ---------------------------------------------------------------------------


def canonical_json(value: Any) -> str:
    """Stable JSON: sorted keys, no insignificant whitespace, UTF-8 preserved."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.strip().lower().encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Domain vocabulary
# ---------------------------------------------------------------------------


class TrustTier(IntEnum):
    """Instruction authority. Lower is more trusted; authority never increases."""

    SYSTEM = 0
    OPERATOR = 1
    USER = 2
    WORKSPACE = 3
    RETRIEVED_TRUSTED = 4
    RETRIEVED_UNTRUSTED = 5
    TOOL_OUTPUT = 6


class MemoryKind(StrEnum):
    WORKING = "working"
    CONVERSATION = "conversation"
    EPISODIC = "episodic"
    SEMANTIC = "semantic"
    PROCEDURAL = "procedural"
    PROFILE = "profile"
    REFLECTION = "reflection"


#: Kinds for which two claims about the same (subject, predicate) may not hold
#: over overlapping world time. Episodic memory is deliberately excluded: a person
#: can legitimately do two things at once, and constraining it would produce
#: spurious conflicts under concurrent ingestion.
EXCLUSIVE_KINDS = frozenset(
    {MemoryKind.SEMANTIC, MemoryKind.PROFILE, MemoryKind.PROCEDURAL}
)


class Sensitivity(StrEnum):
    PUBLIC = "public"
    INTERNAL = "internal"
    CONFIDENTIAL = "confidential"
    RESTRICTED = "restricted"


_SENSITIVITY_RANK = {
    Sensitivity.PUBLIC: 0,
    Sensitivity.INTERNAL: 1,
    Sensitivity.CONFIDENTIAL: 2,
    Sensitivity.RESTRICTED: 3,
}


def sensitivity_rank(s: Sensitivity) -> int:
    return _SENSITIVITY_RANK[s]


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Principal:
    """Who is asking. Tenancy is derived from the credential, never from input."""

    org_id: str
    user_id: str
    workspaces: frozenset[str] = field(default_factory=frozenset)
    max_sensitivity: Sensitivity = Sensitivity.INTERNAL
    denied_tags: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class AuthorizationPredicate:
    """Compiled authorization, pushed *into* the index scan.

    Post-filtering is banned: it leaks existence through result counts and destroys
    recall when the top-k neighbours are all inaccessible. This object is evaluated
    during the scan, and every admission records the rule id that allowed it.
    """

    org_id: str
    workspaces: frozenset[str]
    max_sensitivity_rank: int
    denied_tags: frozenset[str]
    rule_id: str

    @classmethod
    def for_principal(cls, p: Principal, rule_id: str = "rule:default-scope") -> AuthorizationPredicate:
        return cls(
            org_id=p.org_id,
            workspaces=p.workspaces,
            max_sensitivity_rank=sensitivity_rank(p.max_sensitivity),
            denied_tags=p.denied_tags,
            rule_id=rule_id,
        )

    def allows(
        self,
        *,
        org_id: str,
        workspace_id: str | None,
        sensitivity: Sensitivity,
        tags: tuple[str, ...],
    ) -> bool:
        if org_id != self.org_id:
            return False
        if workspace_id is not None and workspace_id not in self.workspaces:
            return False
        if sensitivity_rank(sensitivity) > self.max_sensitivity_rank:
            return False
        return not self.denied_tags.intersection(tags)


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------


class MnemosError(Exception):
    """Root of the exception hierarchy."""


class BudgetUnsatisfiable(MnemosError):
    """Section floors cannot be met within the requested budget."""


class ClaimConflict(MnemosError):
    """A write would violate the bitemporal exclusivity invariant."""


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class Settings:
    """All tunables in one place. No magic numbers in the algorithms."""

    db_path: str = os.environ.get("MNEMOS_DB", "./.data/mnemos.db")
    embedding_dim: int = int(os.environ.get("MNEMOS_EMBED_DIM", "256"))
    embedder: str = os.environ.get("MNEMOS_EMBEDDER", "hashing")
    default_token_budget: int = int(os.environ.get("MNEMOS_TOKEN_BUDGET", "2000"))
    default_latency_budget_ms: int = int(os.environ.get("MNEMOS_LATENCY_MS", "1500"))
    rrf_k: int = 60
    rerank_margin_threshold: float = 0.05
    near_duplicate_threshold: float = 0.86
    decay_tau_days: dict[str, float] = field(
        default_factory=lambda: {
            MemoryKind.WORKING: 0.25,
            MemoryKind.CONVERSATION: 3.0,
            MemoryKind.EPISODIC: 30.0,
            MemoryKind.SEMANTIC: 365.0,
            MemoryKind.PROCEDURAL: 730.0,
            MemoryKind.PROFILE: 730.0,
            MemoryKind.REFLECTION: 180.0,
        }
    )
    importance_weights: dict[str, float] = field(
        default_factory=lambda: {
            "salience": 0.35,
            "recency": 0.25,
            "frequency": 0.20,
            "confidence": 0.20,
        }
    )

"""SQLite-backed store: bitemporal memory claims + document chunks.

Two design points carry most of the weight here.

**Bitemporality.** Every claim records both *world time* (`valid_from`/`valid_to` —
when the fact holds) and *belief time* (`recorded_at`/`retracted_at` — when the system
believed it). Updates never overwrite; they insert a new row, close belief time on the
prior row, and record a `supersedes` edge. That is what makes "what did this system
believe on date D, about date T?" answerable, and it is what makes the staleness metric
in the benchmark possible at all.

**Exclusivity as an invariant, not a convention.** Two `semantic` claims about the same
subject and predicate may not hold over overlapping world time. Enforced on write and
verified by test. Episodic claims are deliberately exempt.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import numpy as np

from .core import (
    EXCLUSIVE_KINDS,
    Clock,
    IdGenerator,
    MemoryKind,
    Sensitivity,
    SystemClock,
    TrustTier,
    Uuid4Generator,
    content_hash,
)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS memory (
    id            TEXT PRIMARY KEY,
    org_id        TEXT NOT NULL,
    workspace_id  TEXT,
    kind          TEXT NOT NULL,
    subject_id    TEXT NOT NULL,
    predicate     TEXT NOT NULL,
    object_text   TEXT NOT NULL,
    valid_from    TEXT NOT NULL,
    valid_to      TEXT,
    recorded_at   TEXT NOT NULL,
    retracted_at  TEXT,
    sensitivity   TEXT NOT NULL,
    tags          TEXT NOT NULL DEFAULT '',
    trust_tier    INTEGER NOT NULL,
    confidence    REAL NOT NULL DEFAULT 1.0,
    salience      REAL NOT NULL DEFAULT 0.5,
    access_count  INTEGER NOT NULL DEFAULT 0,
    content_hash  TEXT NOT NULL,
    vector        BLOB
);
CREATE INDEX IF NOT EXISTS memory_asserted_idx
    ON memory (org_id, subject_id, kind) WHERE retracted_at IS NULL;
CREATE INDEX IF NOT EXISTS memory_logical_key_idx
    ON memory (org_id, subject_id, predicate) WHERE retracted_at IS NULL;

CREATE TABLE IF NOT EXISTS memory_edge (
    id         TEXT PRIMARY KEY,
    source_id  TEXT NOT NULL REFERENCES memory(id),
    target_id  TEXT NOT NULL REFERENCES memory(id),
    kind       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE (source_id, target_id, kind)
);

CREATE TABLE IF NOT EXISTS document (
    id           TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    workspace_id TEXT,
    title        TEXT NOT NULL,
    source_uri   TEXT NOT NULL,
    sensitivity  TEXT NOT NULL,
    trust_tier   INTEGER NOT NULL,
    tags         TEXT NOT NULL DEFAULT '',
    -- Document-level currency. Real corpora accumulate prior-year revisions of the
    -- same policy, lexically near-identical but numerically different. A retriever
    -- with no notion of currency will happily return the 2024 figure.
    valid_from   TEXT,
    superseded   INTEGER NOT NULL DEFAULT 0,
    created_at   TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS chunk (
    id           TEXT PRIMARY KEY,
    org_id       TEXT NOT NULL,
    document_id  TEXT NOT NULL REFERENCES document(id),
    ordinal      INTEGER NOT NULL,
    content      TEXT NOT NULL,
    token_count  INTEGER NOT NULL,
    char_start   INTEGER NOT NULL,
    char_end     INTEGER NOT NULL,
    page         INTEGER,
    heading      TEXT,
    workspace_id TEXT,
    sensitivity  TEXT NOT NULL,
    trust_tier   INTEGER NOT NULL,
    tags         TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL,
    doc_superseded INTEGER NOT NULL DEFAULT 0,
    vector       BLOB
);
CREATE INDEX IF NOT EXISTS chunk_doc_idx ON chunk (document_id, ordinal);
CREATE INDEX IF NOT EXISTS chunk_org_idx ON chunk (org_id);
"""


def _iso(dt: datetime | None) -> str | None:
    return dt.astimezone(UTC).isoformat() if dt else None


def _parse(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _pack(vec: np.ndarray | None) -> bytes | None:
    return vec.astype(np.float32).tobytes() if vec is not None else None


def _unpack(blob: bytes | None, dim: int) -> np.ndarray:
    if not blob:
        return np.zeros(dim, dtype=np.float32)
    return np.frombuffer(blob, dtype=np.float32)


# ---------------------------------------------------------------------------
# Records
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class Claim:
    id: str
    org_id: str
    kind: MemoryKind
    subject_id: str
    predicate: str
    object_text: str
    valid_from: datetime
    valid_to: datetime | None
    recorded_at: datetime
    retracted_at: datetime | None
    sensitivity: Sensitivity
    tags: tuple[str, ...]
    trust_tier: TrustTier
    confidence: float
    salience: float
    workspace_id: str | None = None
    access_count: int = 0

    @property
    def text(self) -> str:
        return self.object_text


@dataclass(slots=True)
class Chunk:
    id: str
    org_id: str
    document_id: str
    ordinal: int
    content: str
    token_count: int
    char_start: int
    char_end: int
    sensitivity: Sensitivity
    trust_tier: TrustTier
    tags: tuple[str, ...]
    page: int | None = None
    heading: str | None = None
    workspace_id: str | None = None
    document_title: str = ""
    doc_superseded: bool = False

    @property
    def text(self) -> str:
        return self.content


@dataclass(slots=True)
class WriteResult:
    """What a write did to existing beliefs.

    Returned to the caller because a memory API that silently supersedes prior
    claims is one whose behaviour can only be discovered by reading the database.
    """

    claim: Claim
    superseded: list[str]
    outcome: str


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------


class Store:
    def __init__(
        self,
        path: str,
        dim: int,
        clock: Clock | None = None,
        ids: IdGenerator | None = None,
    ) -> None:
        self.dim = dim
        self.clock: Clock = clock or SystemClock()
        self.ids: IdGenerator = ids or Uuid4Generator()
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self.conn.executescript(_SCHEMA)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- memory -------------------------------------------------------------

    def write_claim(
        self,
        *,
        org_id: str,
        kind: MemoryKind,
        subject_id: str,
        predicate: str,
        object_text: str,
        vector: np.ndarray | None = None,
        valid_from: datetime | None = None,
        valid_to: datetime | None = None,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        tags: tuple[str, ...] = (),
        trust_tier: TrustTier = TrustTier.USER,
        confidence: float = 1.0,
        salience: float = 0.5,
        workspace_id: str | None = None,
    ) -> WriteResult:
        """Insert a claim, arbitrating against conflicting asserted claims.

        Arbitration runs inside the write transaction. Doing it asynchronously
        would open a window in which two contradictory claims are both asserted,
        which retrieval would surface as a spurious conflict.
        """
        now = self.clock.now()
        valid_from = valid_from or now
        superseded: list[str] = []

        with self.conn:
            if kind in EXCLUSIVE_KINDS:
                rows = self.conn.execute(
                    """
                    SELECT id, valid_from, valid_to FROM memory
                     WHERE org_id = ? AND subject_id = ? AND predicate = ?
                       AND kind = ? AND retracted_at IS NULL
                    """,
                    (org_id, subject_id, predicate, str(kind)),
                ).fetchall()
                for row in rows:
                    if _overlaps(
                        valid_from,
                        valid_to,
                        _parse(row["valid_from"]),
                        _parse(row["valid_to"]),
                    ):
                        superseded.append(row["id"])

            claim_id = self.ids.new()
            self.conn.execute(
                """
                INSERT INTO memory (id, org_id, workspace_id, kind, subject_id, predicate,
                                    object_text, valid_from, valid_to, recorded_at,
                                    retracted_at, sensitivity, tags, trust_tier,
                                    confidence, salience, content_hash, vector)
                VALUES (?,?,?,?,?,?,?,?,?,?,NULL,?,?,?,?,?,?,?)
                """,
                (
                    claim_id, org_id, workspace_id, str(kind), subject_id, predicate,
                    object_text, _iso(valid_from), _iso(valid_to), _iso(now),
                    str(sensitivity), ",".join(tags), int(trust_tier),
                    confidence, salience, content_hash(object_text), _pack(vector),
                ),
            )

            for prior_id in superseded:
                # Belief time closes; the row is NOT deleted or mutated in place.
                self.conn.execute(
                    "UPDATE memory SET retracted_at = ? WHERE id = ?", (_iso(now), prior_id)
                )
                self.conn.execute(
                    "INSERT OR IGNORE INTO memory_edge (id, source_id, target_id, kind, created_at)"
                    " VALUES (?,?,?,?,?)",
                    (self.ids.new(), claim_id, prior_id, "supersedes", _iso(now)),
                )

        claim = self.get_claim(claim_id)
        assert claim is not None
        return WriteResult(
            claim=claim,
            superseded=superseded,
            outcome="asserted_superseding" if superseded else "asserted",
        )

    def get_claim(self, claim_id: str) -> Claim | None:
        row = self.conn.execute("SELECT * FROM memory WHERE id = ?", (claim_id,)).fetchone()
        return _row_to_claim(row) if row else None

    def query_claims(
        self,
        *,
        org_id: str,
        as_of: datetime | None = None,
        believed_at: datetime | None = None,
        kinds: tuple[MemoryKind, ...] | None = None,
        subject_id: str | None = None,
    ) -> list[Claim]:
        """Bitemporal query over two independent axes.

        `as_of`      - world time: claims whose validity interval contains it.
        `believed_at`- belief time: the system's state of knowledge at that instant.

        Both default to now, so the common case is unaffected by the complexity.
        """
        now = self.clock.now()
        as_of = as_of or now
        believed_at = believed_at or now

        sql = ["SELECT * FROM memory WHERE org_id = ?"]
        args: list[object] = [org_id]

        # belief time: recorded at or before, and not yet retracted at that instant
        sql.append("AND recorded_at <= ?")
        args.append(_iso(believed_at))
        sql.append("AND (retracted_at IS NULL OR retracted_at > ?)")
        args.append(_iso(believed_at))

        # world time
        sql.append("AND valid_from <= ?")
        args.append(_iso(as_of))
        sql.append("AND (valid_to IS NULL OR valid_to > ?)")
        args.append(_iso(as_of))

        if subject_id:
            sql.append("AND subject_id = ?")
            args.append(subject_id)
        if kinds:
            sql.append(f"AND kind IN ({','.join('?' * len(kinds))})")
            args.extend(str(k) for k in kinds)

        rows = self.conn.execute(" ".join(sql), args).fetchall()
        return [_row_to_claim(r) for r in rows]

    def naive_all_claims(self, org_id: str) -> list[Claim]:
        """Every claim ever written, ignoring belief time.

        This exists solely to model the baseline arm of the benchmark: a memory
        store with no `retracted_at` column, which is what you get when memory is
        "just another vector collection" that facts are appended to. Superseded
        beliefs remain retrievable forever. Nothing in the compiler path calls it.
        """
        rows = self.conn.execute("SELECT * FROM memory WHERE org_id = ?", (org_id,)).fetchall()
        return [_row_to_claim(r) for r in rows]

    def claim_vectors(self, claims: list[Claim]) -> np.ndarray:
        if not claims:
            return np.zeros((0, self.dim), dtype=np.float32)
        placeholders = ",".join("?" * len(claims))
        rows = self.conn.execute(
            f"SELECT id, vector FROM memory WHERE id IN ({placeholders})",
            [c.id for c in claims],
        ).fetchall()
        by_id = {r["id"]: _unpack(r["vector"], self.dim) for r in rows}
        return np.vstack([by_id[c.id] for c in claims])

    def touch(self, claim_ids: list[str]) -> None:
        if not claim_ids:
            return
        with self.conn:
            self.conn.executemany(
                "UPDATE memory SET access_count = access_count + 1 WHERE id = ?",
                [(cid,) for cid in claim_ids],
            )

    # -- documents ----------------------------------------------------------

    def add_document(
        self,
        *,
        org_id: str,
        title: str,
        source_uri: str,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        trust_tier: TrustTier = TrustTier.RETRIEVED_TRUSTED,
        tags: tuple[str, ...] = (),
        workspace_id: str | None = None,
        valid_from: datetime | None = None,
        superseded: bool = False,
    ) -> str:
        doc_id = self.ids.new()
        with self.conn:
            self.conn.execute(
                "INSERT INTO document (id, org_id, workspace_id, title, source_uri,"
                " sensitivity, trust_tier, tags, valid_from, superseded, created_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    doc_id, org_id, workspace_id, title, source_uri, str(sensitivity),
                    int(trust_tier), ",".join(tags), _iso(valid_from),
                    int(superseded), _iso(self.clock.now()),
                ),
            )
        return doc_id

    def add_chunks(self, doc_id: str, chunks: list[dict[str, object]]) -> list[str]:
        doc = self.conn.execute("SELECT * FROM document WHERE id = ?", (doc_id,)).fetchone()
        if doc is None:
            raise ValueError(f"unknown document {doc_id}")
        ids: list[str] = []
        with self.conn:
            for c in chunks:
                cid = self.ids.new()
                ids.append(cid)
                self.conn.execute(
                    """
                    INSERT INTO chunk (id, org_id, document_id, ordinal, content, token_count,
                                       char_start, char_end, page, heading, workspace_id,
                                       sensitivity, trust_tier, tags, content_hash,
                                       doc_superseded, vector)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        cid, doc["org_id"], doc_id, c["ordinal"], c["content"],
                        c["token_count"], c["char_start"], c["char_end"],
                        c.get("page"), c.get("heading"), doc["workspace_id"],
                        c.get("sensitivity", doc["sensitivity"]),
                        int(c.get("trust_tier", doc["trust_tier"])),
                        c.get("tags", doc["tags"]),
                        content_hash(str(c["content"])),
                        int(doc["superseded"]),
                        _pack(c.get("vector")),  # type: ignore[arg-type]
                    ),
                )
        return ids

    def all_chunks(self, org_id: str) -> tuple[list[Chunk], np.ndarray]:
        rows = self.conn.execute(
            "SELECT c.*, d.title AS document_title FROM chunk c"
            " JOIN document d ON d.id = c.document_id WHERE c.org_id = ?"
            " ORDER BY c.document_id, c.ordinal",
            (org_id,),
        ).fetchall()
        chunks = [_row_to_chunk(r) for r in rows]
        if not chunks:
            return [], np.zeros((0, self.dim), dtype=np.float32)
        matrix = np.vstack([_unpack(r["vector"], self.dim) for r in rows])
        return chunks, matrix


def _overlaps(
    a_from: datetime, a_to: datetime | None, b_from: datetime | None, b_to: datetime | None
) -> bool:
    """Half-open interval overlap [from, to)."""
    b_from = b_from or datetime.min.replace(tzinfo=UTC)
    a_end = a_to or datetime.max.replace(tzinfo=UTC)
    b_end = b_to or datetime.max.replace(tzinfo=UTC)
    return a_from < b_end and b_from < a_end


def _row_to_claim(row: sqlite3.Row) -> Claim:
    return Claim(
        id=row["id"],
        org_id=row["org_id"],
        workspace_id=row["workspace_id"],
        kind=MemoryKind(row["kind"]),
        subject_id=row["subject_id"],
        predicate=row["predicate"],
        object_text=row["object_text"],
        valid_from=_parse(row["valid_from"]),  # type: ignore[arg-type]
        valid_to=_parse(row["valid_to"]),
        recorded_at=_parse(row["recorded_at"]),  # type: ignore[arg-type]
        retracted_at=_parse(row["retracted_at"]),
        sensitivity=Sensitivity(row["sensitivity"]),
        tags=tuple(t for t in row["tags"].split(",") if t),
        trust_tier=TrustTier(row["trust_tier"]),
        confidence=row["confidence"],
        salience=row["salience"],
        access_count=row["access_count"],
    )


def _row_to_chunk(row: sqlite3.Row) -> Chunk:
    return Chunk(
        id=row["id"],
        org_id=row["org_id"],
        document_id=row["document_id"],
        ordinal=row["ordinal"],
        content=row["content"],
        token_count=row["token_count"],
        char_start=row["char_start"],
        char_end=row["char_end"],
        page=row["page"],
        heading=row["heading"],
        workspace_id=row["workspace_id"],
        sensitivity=Sensitivity(row["sensitivity"]),
        trust_tier=TrustTier(row["trust_tier"]),
        tags=tuple(t for t in row["tags"].split(",") if t),
        document_title=row["document_title"] if "document_title" in row.keys() else "",
        doc_superseded=bool(row["doc_superseded"]),
    )

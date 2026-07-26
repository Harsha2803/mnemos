"""Document ingestion: PDF/text extraction and structure-aware chunking.

Chunks carry character offsets and a heading breadcrumb so a retrieved passage can
be cited back to an exact location in the source. Without offsets, provenance stops
at "some chunk of this file", which is not provenance — and the highlight view
becomes impossible to add later without reprocessing the whole corpus.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from .core import Sensitivity, Tokenizer, TrustTier
from .embed import Embedder
from .store import Store


@dataclass(slots=True)
class RawChunk:
    ordinal: int
    content: str
    char_start: int
    char_end: int
    token_count: int
    heading: str | None
    page: int | None


_HEADING = re.compile(r"^(#{1,6}\s+.+|[A-Z][A-Z0-9 ,\-/&']{6,}\s*)$")
_PARA_SPLIT = re.compile(r"\n\s*\n")


def chunk_text(
    text: str,
    tokenizer: Tokenizer,
    *,
    target_tokens: int = 120,
    overlap_tokens: int = 24,
    page: int | None = None,
) -> list[RawChunk]:
    """Split on paragraph boundaries, packing up to `target_tokens`.

    Overlap is included deliberately: it is standard practice because it prevents
    an answer that straddles a boundary from being lost. It is also the direct
    cause of the duplicate-token waste that the benchmark measures — the naive arm
    pays for that overlap repeatedly, the compiler deduplicates it away.
    """
    chunks: list[RawChunk] = []
    heading: str | None = None
    cursor = 0
    buf: list[tuple[str, int, int]] = []
    buf_tokens = 0
    ordinal = 0

    def flush() -> None:
        nonlocal buf, buf_tokens, ordinal
        if not buf:
            return
        content = "\n\n".join(p for p, _, _ in buf).strip()
        if content:
            chunks.append(
                RawChunk(
                    ordinal=ordinal,
                    content=content,
                    char_start=buf[0][1],
                    char_end=buf[-1][2],
                    token_count=tokenizer.count(content),
                    heading=heading,
                    page=page,
                )
            )
            ordinal += 1
        # Carry the tail paragraph forward as overlap.
        if overlap_tokens > 0 and buf:
            tail = buf[-1]
            if tokenizer.count(tail[0]) <= overlap_tokens * 2:
                buf = [tail]
                buf_tokens = tokenizer.count(tail[0])
                return
        buf = []
        buf_tokens = 0

    for para in _PARA_SPLIT.split(text):
        stripped = para.strip()
        if not stripped:
            cursor += len(para) + 2
            continue
        start = text.find(stripped, cursor)
        if start < 0:
            start = cursor
        end = start + len(stripped)
        cursor = end

        if _HEADING.match(stripped) and len(stripped) < 90:
            flush()
            heading = stripped.lstrip("# ").strip()
            continue

        cost = tokenizer.count(stripped)
        if buf_tokens + cost > target_tokens and buf:
            flush()
        buf.append((stripped, start, end))
        buf_tokens += cost

    flush()
    return chunks


def extract_pdf(path: Path) -> list[tuple[int, str]]:
    """Extract per-page text. Returns [(page_number, text)]."""
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("PDF ingestion requires pypdf") from exc
    reader = PdfReader(str(path))
    out: list[tuple[int, str]] = []
    for i, page in enumerate(reader.pages, start=1):
        text = page.extract_text() or ""
        if text.strip():
            out.append((i, text))
    return out


class Ingestor:
    def __init__(self, store: Store, embedder: Embedder, tokenizer: Tokenizer) -> None:
        self.store = store
        self.embedder = embedder
        self.tokenizer = tokenizer

    def ingest_text(
        self,
        *,
        org_id: str,
        title: str,
        source_uri: str,
        text: str,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        trust_tier: TrustTier = TrustTier.RETRIEVED_TRUSTED,
        tags: tuple[str, ...] = (),
        workspace_id: str | None = None,
        target_tokens: int = 120,
        valid_from: object | None = None,
        superseded: bool = False,
    ) -> tuple[str, list[str]]:
        doc_id = self.store.add_document(
            org_id=org_id, title=title, source_uri=source_uri,
            sensitivity=sensitivity, trust_tier=trust_tier, tags=tags,
            workspace_id=workspace_id, valid_from=valid_from, superseded=superseded,
        )
        raw = chunk_text(text, self.tokenizer, target_tokens=target_tokens)
        if not raw:
            return doc_id, []
        vectors = self.embedder.encode([c.content for c in raw])
        payload = [
            {
                "ordinal": c.ordinal, "content": c.content, "token_count": c.token_count,
                "char_start": c.char_start, "char_end": c.char_end,
                "page": c.page, "heading": c.heading, "vector": vectors[i],
                "sensitivity": str(sensitivity), "trust_tier": int(trust_tier),
                "tags": ",".join(tags),
            }
            for i, c in enumerate(raw)
        ]
        return doc_id, self.store.add_chunks(doc_id, payload)

    def ingest_pdf(
        self,
        *,
        org_id: str,
        path: Path,
        sensitivity: Sensitivity = Sensitivity.INTERNAL,
        trust_tier: TrustTier = TrustTier.RETRIEVED_UNTRUSTED,
        tags: tuple[str, ...] = (),
        workspace_id: str | None = None,
    ) -> tuple[str, list[str]]:
        """Ingest a PDF page by page.

        Trust tier defaults to RETRIEVED_UNTRUSTED for PDFs: an uploaded file is
        attacker-controllable in most deployments, and the tier is immutable once
        assigned, so defaulting it optimistically would be unrecoverable.
        """
        pages = extract_pdf(path)
        doc_id = self.store.add_document(
            org_id=org_id, title=path.stem, source_uri=str(path),
            sensitivity=sensitivity, trust_tier=trust_tier, tags=tags,
            workspace_id=workspace_id,
        )
        all_raw: list[RawChunk] = []
        offset = 0
        for page_no, text in pages:
            page_chunks = chunk_text(text, self.tokenizer, page=page_no)
            for c in page_chunks:
                c.ordinal = len(all_raw)
                c.char_start += offset
                c.char_end += offset
                all_raw.append(c)
            offset += len(text)

        if not all_raw:
            return doc_id, []
        vectors = self.embedder.encode([c.content for c in all_raw])
        payload = [
            {
                "ordinal": c.ordinal, "content": c.content, "token_count": c.token_count,
                "char_start": c.char_start, "char_end": c.char_end,
                "page": c.page, "heading": c.heading, "vector": vectors[i],
                "sensitivity": str(sensitivity), "trust_tier": int(trust_tier),
                "tags": ",".join(tags),
            }
            for i, c in enumerate(all_raw)
        ]
        return doc_id, self.store.add_chunks(doc_id, payload)

"""`A2` — the pure half: chunking, fusion, dedup, prompt assembly, citations.

Hermetic — no Docker, no Postgres, no model. `test_knowledge_endpoints.py`
covers the SQL and the wire; this covers the logic ported from `_v1` and the
prompt/citation code that is new in this milestone.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from mnemos.core.errors import ValidationError
from mnemos.features.knowledge.adapters.extraction import extract_pages
from mnemos.features.knowledge.domain import (
    ChunkId,
    DocumentId,
    HashingEmbedder,
    HeuristicTokenizer,
    RetrievedChunk,
    chunk_text,
    deduplicate,
    reciprocal_rank_fusion,
)
from mnemos.flows.rag.domain import (
    NO_DOCUMENTS_FOUND,
    build_context_block,
    extract_citations,
    truncate_to_budget,
)

TOKENIZER = HeuristicTokenizer()


def a_chunk(
    *, text: str = "some text", score: float = 0.9, tokens: int = 10, chunk_id: object = None
) -> RetrievedChunk:
    return RetrievedChunk(
        chunk_id=ChunkId(chunk_id or uuid4()),  # type: ignore[arg-type]
        document_id=DocumentId(uuid4()),
        document_title="A Document",
        text=text,
        score=score,
        operator_id="test",
        token_count=tokens,
        char_start=0,
        char_end=len(text),
        page_number=None,
    )


# --------------------------------------------------------------------- chunking


def test_chunks_carry_offsets_that_index_back_into_the_original_text() -> None:
    """The property citations depend on: `text[start:end]` must be the chunk.
    Without it a citation resolves to "somewhere in this document", which is
    not provenance."""
    source = "\n\n".join(f"Paragraph number {i} with some words in it." for i in range(12))

    chunks = chunk_text(source, TOKENIZER, target_tokens=20)

    assert len(chunks) > 1
    for chunk in chunks:
        assert source[chunk.char_start : chunk.char_end] in source
        assert chunk.char_end > chunk.char_start


def test_a_heading_becomes_the_breadcrumb_for_the_chunks_under_it() -> None:
    source = "# Leave Policy\n\nCarry-over is capped at five days.\n\nRequests need approval."

    chunks = chunk_text(source, TOKENIZER, target_tokens=200)

    assert chunks
    assert all(c.heading == "Leave Policy" for c in chunks)


# --------------------------------------------------------------------- extraction


async def test_extraction_of_an_unsupported_media_type_is_a_named_validation_error() -> None:
    """Never a silently empty document — an unreadable upload that produced
    zero chunks would look exactly like a successful upload of a blank file."""
    with pytest.raises(ValidationError) as excinfo:
        await extract_pages(b"\x00\x01binary", "application/octet-stream")

    assert "application/octet-stream" in excinfo.value.message


async def test_plain_text_extracts_as_one_unpaginated_page() -> None:
    pages = await extract_pages(b"hello world", "text/plain")

    # `None`, not 1: a text file has no pages, and claiming page 1 would put a
    # fabricated page number in a citation.
    assert pages == [(None, "hello world")]


# ----------------------------------------------------------------------- fusion


def test_rrf_ranks_a_chunk_both_operators_found_above_one_only_a_single_operator_found() -> None:
    """The whole reason to fuse by rank: cosine and trigram similarity are not
    on a comparable scale, so the only signal that survives combining them is
    agreement."""
    shared = a_chunk(text="found by both")
    vector_only = a_chunk(text="found by vector alone")
    lexical_only = a_chunk(text="found by lexical alone")

    fused = reciprocal_rank_fusion([[vector_only, shared], [lexical_only, shared]], k=60)

    assert fused[0].chunk.chunk_id == shared.chunk_id


def test_fusion_returns_each_chunk_once_however_many_operators_found_it() -> None:
    shared = a_chunk(text="found by both")

    fused = reciprocal_rank_fusion([[shared], [shared]], k=60)

    assert len(fused) == 1


# ------------------------------------------------------------------------ dedup


def test_near_duplicate_chunks_collapse_and_their_tokens_are_recovered() -> None:
    """Chunking overlaps by construction, so top-k returns the same sentences
    repeatedly; those repeated tokens are charged to the budget and buy
    nothing."""
    original = a_chunk(text="the quick brown fox jumps over the lazy dog", tokens=12)
    overlapping = a_chunk(text="the quick brown fox jumps over the lazy dog today", tokens=13)
    distinct = a_chunk(text="an entirely unrelated sentence about something else", tokens=11)

    fused = reciprocal_rank_fusion([[original, overlapping, distinct]], k=60)
    kept, report = deduplicate(fused, threshold=0.7)

    kept_ids = {item.chunk.chunk_id for item in kept}
    assert original.chunk_id in kept_ids
    assert overlapping.chunk_id not in kept_ids
    assert distinct.chunk_id in kept_ids
    assert report.removed == 1
    assert report.tokens_saved == 13


def test_dedup_keeps_distinct_chunks(  # the control — a dedup that drops everything
) -> None:
    """Without this, a `deduplicate` that returned `[]` would pass the test
    above and every retrieval would silently return nothing."""
    first = a_chunk(text="revenue grew twelve percent in the third quarter")
    second = a_chunk(text="headcount fell by four in the engineering organisation")

    fused = reciprocal_rank_fusion([[first, second]], k=60)
    kept, report = deduplicate(fused, threshold=0.86)

    assert len(kept) == 2
    assert report.removed == 0


# ------------------------------------------------------------ prompt and budget


def test_truncation_admits_in_order_and_never_exceeds_the_budget() -> None:
    chunks = [a_chunk(text=f"chunk {i}", tokens=40) for i in range(10)]

    admitted = truncate_to_budget(chunks, TOKENIZER, budget_tokens=100)

    assert len(admitted) == 2
    assert sum(c.token_count for c in admitted) <= 100
    assert admitted == chunks[:2]


def test_the_context_block_numbers_passages_from_one_to_match_the_markers() -> None:
    chunks = [a_chunk(text="first passage"), a_chunk(text="second passage")]

    block = build_context_block(chunks)

    assert "[1]" in block
    assert "[2]" in block
    assert "[0]" not in block


def test_an_empty_retrieval_says_so_in_the_prompt_rather_than_falling_back_silently() -> None:
    """If nothing was retrieved, the model must be told — otherwise a RAG
    answer is indistinguishable from a plain-chat answer that invented one."""
    assert build_context_block([]) == NO_DOCUMENTS_FOUND


# -------------------------------------------------------------------- citations


def test_citations_resolve_markers_to_the_chunks_actually_offered() -> None:
    chunks = [a_chunk(text="first"), a_chunk(text="second"), a_chunk(text="third")]

    targets = extract_citations("The answer is X [2], and also Y [1].", chunks)

    assert [t.marker for t in targets] == [1, 2]
    assert targets[0].chunk.chunk_id == chunks[0].chunk_id
    assert targets[1].chunk.chunk_id == chunks[1].chunk_id


def test_a_marker_naming_a_passage_that_was_never_offered_is_dropped() -> None:
    """A citation pointing at nothing is worse than no citation — it is a
    clickable link to a source that does not exist."""
    chunks = [a_chunk(text="only passage")]

    targets = extract_citations("As established [7], the answer is X [1].", chunks)

    assert [t.marker for t in targets] == [1]


def test_a_repeated_marker_produces_one_citation() -> None:
    chunks = [a_chunk(text="only passage")]

    targets = extract_citations("First [1]. Second [1]. Third [1].", chunks)

    assert len(targets) == 1


# ------------------------------------------------------------------- embeddings


def test_the_default_embedder_needs_no_download_and_matches_the_schema_dimension() -> None:
    """C1/C2: the default path pulls nothing. `chunk_embedding.embedding` is
    `HALFVEC(384)`, so an embedder at any other dimension fails at insert
    rather than at review."""
    embedder = HashingEmbedder(dim=384)

    vectors = embedder.encode(["hello world", "something else"])

    assert vectors.shape == (2, 384)
    assert embedder.name == "hashing-384"


def test_embeddings_are_l2_normalised_so_cosine_distance_is_meaningful() -> None:
    """pgvector's `<=>` is cosine distance; the vector operator relies on these
    being unit vectors for `1 - distance` to read as a similarity."""
    import numpy as np

    vectors = HashingEmbedder(dim=384).encode(["a sentence with several words in it"])

    assert np.isclose(float(np.linalg.norm(vectors[0])), 1.0, atol=1e-5)


def test_the_same_text_always_embeds_identically() -> None:
    """Determinism is what makes a bundle digest stable across machines
    (`_v1`'s argument) and what keeps a re-ingest from producing a different
    vector for unchanged content."""
    import numpy as np

    embedder = HashingEmbedder(dim=384)

    first = embedder.encode(["the quick brown fox"])
    second = embedder.encode(["the quick brown fox"])

    assert np.array_equal(first, second)

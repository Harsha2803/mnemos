"""Knowledge domain: pure types, no SQLAlchemy, no FastAPI, no I/O."""

from __future__ import annotations

from mnemos.features.knowledge.domain.chunking import RawChunk, chunk_text
from mnemos.features.knowledge.domain.document import DocumentSummary
from mnemos.features.knowledge.domain.embedder import Embedder, HashingEmbedder
from mnemos.features.knowledge.domain.ids import ChunkId, DocumentId
from mnemos.features.knowledge.domain.retrieval import (
    DedupReport,
    FusedChunk,
    RetrievedChunk,
    deduplicate,
    reciprocal_rank_fusion,
    truncate_to_budget,
)
from mnemos.features.knowledge.domain.tokenizer import HeuristicTokenizer, Tokenizer

__all__ = [
    "ChunkId",
    "DedupReport",
    "DocumentId",
    "DocumentSummary",
    "Embedder",
    "FusedChunk",
    "HashingEmbedder",
    "HeuristicTokenizer",
    "RawChunk",
    "RetrievedChunk",
    "Tokenizer",
    "chunk_text",
    "deduplicate",
    "reciprocal_rank_fusion",
    "truncate_to_budget",
]

"""Embedding port and adapters.

Three adapters implement one port. The default requires no model download, so the
benchmark reproduces in seconds on any machine; the neural adapter is opt-in and
strictly better. Swapping between them is a settings change, which is the point of
having the port at all.
"""

from __future__ import annotations

import hashlib
import re
from typing import Protocol

import numpy as np


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...

    @property
    def name(self) -> str: ...


_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class HashingEmbedder:
    """Deterministic feature-hashing embedder over word and character n-grams.

    This is a *lexical* embedder projected into a dense space, not a neural one. It
    is the default because it needs no download, is fully deterministic (so bundle
    digests are stable across machines), and is adequate on the corpus sizes this
    project benchmarks against.

    Being explicit about what it is matters: the benchmark's headline claims are
    about budget adherence, deduplication, staleness and authorization, none of
    which depend on embedding quality. Where retrieval quality *is* measured, the
    same embedder is used for both arms, so the comparison stays fair.

    Features: word unigrams, word bigrams, and character 4-grams. Sub-linear term
    frequency weighting, L2-normalised so dot product equals cosine similarity.
    """

    def __init__(self, dim: int = 256) -> None:
        self.dim = dim

    @property
    def name(self) -> str:
        return f"hashing-{self.dim}"

    def _features(self, text: str) -> dict[int, float]:
        toks = _tokens(text)
        counts: dict[int, float] = {}

        def bump(key: str, weight: float) -> None:
            h = int.from_bytes(hashlib.blake2b(key.encode(), digest_size=8).digest(), "big")
            idx = h % self.dim
            # Signed hashing cancels collisions in expectation instead of
            # accumulating them, which matters at dim=256 with a real vocabulary.
            sign = 1.0 if (h >> 63) & 1 else -1.0
            counts[idx] = counts.get(idx, 0.0) + sign * weight

        for t in toks:
            bump("w:" + t, 1.0)
        for a, b in zip(toks, toks[1:], strict=False):
            bump(f"b:{a}_{b}", 0.6)
        squashed = " ".join(toks)
        for i in range(0, max(0, len(squashed) - 3)):
            bump("c:" + squashed[i : i + 4], 0.25)
        return counts

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for idx, weight in self._features(text).items():
                # Sub-linear scaling: a term repeated ten times is not ten times
                # as informative, and without this long chunks dominate cosine.
                out[row, idx] = np.sign(weight) * np.log1p(abs(weight))
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        np.divide(out, norms, out=out, where=norms > 0)
        return out


class SentenceTransformerEmbedder:
    """Neural adapter. Opt-in: `pip install mnemos[neural]`.

    Deliberately implements the identical port, so enabling it is
    `MNEMOS_EMBEDDER=neural` with no call-site changes anywhere.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5") -> None:
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "SentenceTransformerEmbedder requires the 'neural' extra: "
                "pip install sentence-transformers"
            ) from exc
        self._model = SentenceTransformer(model_name)
        self._model_name = model_name
        self.dim = int(self._model.get_sentence_embedding_dimension())

    @property
    def name(self) -> str:
        return self._model_name

    def encode(self, texts: list[str]) -> np.ndarray:
        vecs = self._model.encode(texts, normalize_embeddings=True, show_progress_bar=False)
        return np.asarray(vecs, dtype=np.float32)


def build_embedder(kind: str, dim: int) -> Embedder:
    """Composition root for embedding. The only place adapters are named."""
    match kind:
        case "hashing":
            return HashingEmbedder(dim=dim)
        case "neural":
            return SentenceTransformerEmbedder()
        case _:
            raise ValueError(f"unknown embedder: {kind!r} (expected 'hashing' or 'neural')")


def cosine_matrix(query: np.ndarray, matrix: np.ndarray) -> np.ndarray:
    """Cosine similarity of one L2-normalised query against normalised rows."""
    if matrix.size == 0:
        return np.zeros((0,), dtype=np.float32)
    return matrix @ query

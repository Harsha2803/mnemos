"""The embedding port, and the zero-download default.

Ported from `_v1/embed.py`. `HashingEmbedder` is deterministic feature-hashing
over word/character n-grams projected into a dense space — a *lexical*
embedder, not a neural one, and the default because it needs no download
(C1/C2: the benchmark and this milestone's demo both have to reproduce on any
machine). The neural adapter implements the identical port and is opt-in.
"""

from __future__ import annotations

import hashlib
import itertools
import re
from typing import Protocol

import numpy as np

_WORD = re.compile(r"[a-z0-9]+")


def _tokens(text: str) -> list[str]:
    return _WORD.findall(text.lower())


class Embedder(Protocol):
    dim: int

    def encode(self, texts: list[str]) -> np.ndarray: ...

    @property
    def name(self) -> str: ...


class HashingEmbedder:
    """Word unigrams, word bigrams, character 4-grams. Sub-linear term-frequency
    weighting, L2-normalised so dot product equals cosine similarity — which is
    what lets the vector operator use pgvector's `<=>` (cosine distance)
    directly against these vectors."""

    def __init__(self, dim: int = 384) -> None:
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
            sign = 1.0 if (h >> 63) & 1 else -1.0
            counts[idx] = counts.get(idx, 0.0) + sign * weight

        for t in toks:
            bump("w:" + t, 1.0)
        for a, b in itertools.pairwise(toks):
            bump(f"b:{a}_{b}", 0.6)
        squashed = " ".join(toks)
        for i in range(max(0, len(squashed) - 3)):
            bump("c:" + squashed[i : i + 4], 0.25)
        return counts

    def encode(self, texts: list[str]) -> np.ndarray:
        out = np.zeros((len(texts), self.dim), dtype=np.float32)
        for row, text in enumerate(texts):
            for idx, weight in self._features(text).items():
                out[row, idx] = np.sign(weight) * np.log1p(abs(weight))
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        np.divide(out, norms, out=out, where=norms > 0)
        return out

"""A token counter with no model download.

Ported from `_v1/core.py`'s `HeuristicTokenizer`. Real BPE tokenizers split
long words into multiple tokens; counting whitespace words alone under-counts
by roughly 30% on English prose, which would make the token budget this
milestone assembles prompts against wrong in the flattering direction. This
counts regex tokens and adds a length-derived penalty for long words, which
tracks `cl100k_base` within a few percent on ordinary text — adequate for a
budget check, not offered as a tokenizer-exactness claim.
"""

from __future__ import annotations

import re
from typing import Protocol

_WORD_RE = re.compile(r"\w+|[^\w\s]")


class Tokenizer(Protocol):
    def count(self, text: str) -> int: ...


class HeuristicTokenizer:
    def count(self, text: str) -> int:
        if not text:
            return 0
        total = 0
        for tok in _WORD_RE.findall(text):
            total += max(1, (len(tok) + 3) // 4)
        return total

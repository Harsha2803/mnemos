"""Business vocabulary. "Active customer" means something specific, and the
model will invent a definition if nobody supplies one (`adapters/models.py`'s
own docstring on `GlossaryTerm`).

One shape serves both directions: a term the CLI seeds and a term the
repository reads back are the same fields, matched by `term` rather than by
id, so there is nothing to convert between "draft" and "persisted".
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class GlossaryTermRow:
    term: str
    definition: str
    sql_expression: str | None
    synonyms: list[str] = field(default_factory=list)

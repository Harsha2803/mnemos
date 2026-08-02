"""Tag-based document authorization.

A user carries a set of tag slugs; a document carries a set of tag slugs; the user
may see the document when the two sets intersect. That is the whole model, and its
shape is the point: **set-overlap is expressible in SQL**, so the retrieval scan
can push authorization down into the ``WHERE`` clause (constraint C4) instead of
fetching rows and filtering them afterward. Keep this a set-overlap. The moment
authorization needs anything richer than intersection, the pushdown is gone and
the headline ACL claim with it.

Slugs are normalized to lowercase because the ``tag.slug`` column is ``CITEXT``:
the database compares them case-insensitively, and the in-memory test must agree
with the database or the two authorizations diverge.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


def _normalize(slug: str) -> str:
    return slug.strip().lower()


@dataclass(frozen=True, slots=True)
class TagSet:
    """A set of tag slugs with a single authorization test."""

    slugs: frozenset[str]

    @classmethod
    def of(cls, *slugs: str) -> TagSet:
        return cls.from_iterable(slugs)

    @classmethod
    def from_iterable(cls, slugs: Iterable[str]) -> TagSet:
        return cls(frozenset(_normalize(s) for s in slugs if s.strip()))

    def overlaps(self, other: TagSet) -> bool:
        """True when the two sets share at least one slug.

        Empty on either side grants nothing: a principal with no tags reaches no
        tagged document, and an untagged document is reachable by no one through
        this predicate. Intersection is symmetric, so authorization does not
        depend on which side is the subject and which the resource.
        """
        return not self.slugs.isdisjoint(other.slugs)

    def __bool__(self) -> bool:
        return bool(self.slugs)

    def __len__(self) -> int:
        return len(self.slugs)

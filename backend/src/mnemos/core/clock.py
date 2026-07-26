"""Time as an injected dependency.

Bitemporal memory records both when a fact was true in the world and when the
system came to believe it. Both timestamps must be controllable in tests, so no
module below the composition root may call `datetime.now()` directly.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Protocol


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


SYSTEM_CLOCK = SystemClock()

# Open-ended interval terminator. Postgres `tstzrange` upper bounds are exclusive,
# so a row valid "until further notice" ends at this sentinel rather than NULL —
# NULL upper bounds do not participate in the GiST exclusion constraint that
# enforces "one live belief per (subject, predicate, scope)".
END_OF_TIME = datetime(9999, 12, 31, 23, 59, 59, tzinfo=UTC)

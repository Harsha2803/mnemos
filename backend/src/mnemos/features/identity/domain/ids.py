"""Typed identifiers for the identity domain.

Every id in this system is a UUID. Without newtypes, ``revoke(user_id, org_id)``
type-checks with its two arguments transposed, and in a multi-tenant system a
transposed org boundary is a data leak, not a crash. The newtypes cost nothing at
runtime — a ``NewType`` is the identity function — and turn that class of mistake
into a mypy error at the call site.

These live in ``domain`` and pull in nothing but the standard library, which is
what keeps the domain layer unit-testable in microseconds.
"""

from __future__ import annotations

from typing import NewType
from uuid import UUID

OrgId = NewType("OrgId", UUID)
UserId = NewType("UserId", UUID)
RoleId = NewType("RoleId", UUID)
TagId = NewType("TagId", UUID)
SessionId = NewType("SessionId", UUID)
ApiKeyId = NewType("ApiKeyId", UUID)
ProviderId = NewType("ProviderId", UUID)

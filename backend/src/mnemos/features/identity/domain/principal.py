"""The ``Principal``: who is calling, resolved to an org, permissions and tags.

Every milestone past identity takes a ``Principal``. Retrieval pushes its tag set
into the scan; the RBAC guard checks its permissions; the context compiler fences
by its org. So this is the one object the rest of the system authorizes against,
and it is **frozen**: a mutable principal is a privilege-escalation primitive —
any code holding a reference could widen a permission set after the check that
approved it. Authority is decided once, at authentication, and then only read.

A principal is either a person (``kind == USER``, authenticated by a session) or a
machine (``kind == SERVICE``, authenticated by an API key), because an API key is
not a person and the audit trail must not pretend otherwise. Exactly one of
``session_id`` / ``api_key_id`` is set, and which one must agree with ``kind``;
that invariant is enforced at construction so an inconsistent principal cannot
exist to be reasoned about.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from mnemos.features.identity.domain.ids import ApiKeyId, OrgId, SessionId, UserId
from mnemos.features.identity.domain.permission import Permission, PermissionSet
from mnemos.features.identity.domain.tags import TagSet


class PrincipalKind(StrEnum):
    """A person versus a machine credential.

    Not a database enum: nothing stores a principal — it is assembled per request
    from the rows that authenticate it. It lives here, next to the type it
    describes, rather than in ``core.types`` where the DB-mirrored vocabulary is.
    """

    USER = "user"
    SERVICE = "service"


@dataclass(frozen=True, slots=True)
class Principal:
    """An authenticated caller, scoped to exactly one org."""

    org_id: OrgId
    principal_id: UserId
    kind: PrincipalKind
    permissions: PermissionSet
    tags: TagSet
    session_id: SessionId | None = None
    api_key_id: ApiKeyId | None = None

    def __post_init__(self) -> None:
        if self.kind is PrincipalKind.USER:
            if self.session_id is None or self.api_key_id is not None:
                msg = "a user principal is authenticated by a session, not an API key"
                raise ValueError(msg)
        elif self.api_key_id is None or self.session_id is not None:
            msg = "a service principal is authenticated by an API key, not a session"
            raise ValueError(msg)

    def has_permission(self, required: Permission) -> bool:
        """Deny by default: true only if the held set covers ``required``."""
        return self.permissions.allows(required)

    def can_reach(self, resource_tags: TagSet) -> bool:
        """Whether this principal's tags overlap a resource's tags (constraint C4)."""
        return self.tags.overlaps(resource_tags)

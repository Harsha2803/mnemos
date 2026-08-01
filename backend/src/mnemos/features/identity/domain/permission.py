"""Permissions: the ``resource:action`` authority model.

Roles store their grants as a flat list of ``resource:action`` strings in
``role.permissions`` (JSONB). This module is the typed, deny-by-default reading of
that list.

Two asymmetries are deliberate and load-bearing:

*Grants may be wildcards; requirements may not.* A role is allowed to hold
``*:*`` or ``memory:*`` — that is how an org admin is expressed. A route guard
that *requires* ``memory:*`` is a bug: a wildcard requirement can never be
satisfied by an exact grant and would deny everyone, or, read the other way,
would wave through anything under ``memory``. Neither is what a guard means, so
requiring a wildcard raises rather than silently mis-authorizing.

*Parsing is tolerant; construction is strict.* An unknown or malformed permission
sitting in a role's JSONB is harmless — nothing requires it — so parsing skips it
rather than failing a login. But when code names a permission to require, it goes
through :meth:`Permission.require`, which rejects wildcards and empty parts, so a
guard cannot typo a permission into a check that can never pass.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator
from dataclasses import dataclass

WILDCARD = "*"


@dataclass(frozen=True, slots=True)
class Permission:
    """A single ``resource:action`` authority.

    Frozen and hashable so a set of them is a value, not a mutable collection an
    aliasing caller could edit out from under a decision already made on it.
    """

    resource: str
    action: str

    def __post_init__(self) -> None:
        for label, part in (("resource", self.resource), ("action", self.action)):
            if not part:
                msg = f"permission {label} may not be empty"
                raise ValueError(msg)
            if part != part.strip() or ":" in part or any(c.isspace() for c in part):
                msg = f"permission {label} {part!r} must be a bare token without ':' or whitespace"
                raise ValueError(msg)

    @property
    def is_wildcard(self) -> bool:
        return self.resource == WILDCARD or self.action == WILDCARD

    @classmethod
    def parse(cls, raw: str) -> Permission | None:
        """Read one stored ``resource:action`` string, tolerantly.

        Returns ``None`` for anything that is not exactly one ``resource:action``
        pair, because a bad row in a role's grant list must not be able to break
        authorization for the whole principal. Case is normalized to lower so the
        match is stable regardless of how the grant was authored.
        """
        parts = raw.strip().lower().split(":")
        if len(parts) != 2:
            return None
        resource, action = parts
        if not resource or not action:
            return None
        return cls(resource, action)

    @classmethod
    def require(cls, resource: str, action: str) -> Permission:
        """Construct a permission a guard intends to *require*.

        Rejects wildcards: a required permission must be concrete, or the check it
        guards is meaningless. This is the constructor route guards use, so a
        typo becomes a raised error at construction rather than a silent
        permanent denial at request time.
        """
        permission = cls(resource.strip().lower(), action.strip().lower())
        if permission.is_wildcard:
            msg = f"a required permission must be concrete, not a wildcard: {permission}"
            raise ValueError(msg)
        return permission

    def __str__(self) -> str:
        return f"{self.resource}:{self.action}"


@dataclass(frozen=True, slots=True)
class PermissionSet:
    """The permissions a principal holds. Deny by default.

    ``granted`` may contain wildcards; :meth:`allows` interprets them. Membership
    is the only authority test — nothing is implied, nothing is inherited, and a
    permission that is not covered is refused.
    """

    granted: frozenset[Permission]

    @classmethod
    def parse(cls, raws: Iterable[str]) -> PermissionSet:
        """Build from stored strings, dropping any that do not parse."""
        parsed = (Permission.parse(raw) for raw in raws)
        return cls(frozenset(p for p in parsed if p is not None))

    @classmethod
    def of(cls, *permissions: Permission) -> PermissionSet:
        return cls(frozenset(permissions))

    def allows(self, required: Permission) -> bool:
        """Whether the held set covers ``required``.

        A grant covers a requirement when it matches on both axes, with a
        wildcard on either axis of the *grant* matching anything. Raises if the
        requirement itself is a wildcard — see the module docstring.
        """
        if required.is_wildcard:
            msg = f"cannot check a wildcard requirement: {required}"
            raise ValueError(msg)
        return any(
            (g.resource in (required.resource, WILDCARD))
            and (g.action in (required.action, WILDCARD))
            for g in self.granted
        )

    def __iter__(self) -> Iterator[Permission]:
        return iter(self.granted)

    def __len__(self) -> int:
        return len(self.granted)

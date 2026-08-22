"""The system roles: the grants an org has before anybody has configured anything.

These live in ``domain`` rather than next to the bootstrap that writes them
because they are pure policy — a name and a :class:`PermissionSet` — and because
the RBAC guard (M3.6) has to name the same roles the bootstrap seeded. A constant
duplicated between the writer and the reader is a constant that drifts.

**The vocabulary is deliberate on both axes.** A *resource* is one of the feature
packages in ADAPTATION §5 (``chat``, ``memory``, ``document``, ``context``,
``datasource``, ``tool``, ``prompt``, ``cost``, ``audit``, and identity's own
``org`` / ``user`` / ``role`` / ``api_key``), so a permission can always be
traced to the code that will enforce it. ``audit`` was added in ``C3``
deliverable 5 — deliberately not granted to ``analyst`` or ``user`` below, only
``admin``'s wildcard covers it, because an audit trail of "who did what" is
exactly the kind of surface that should default to admin-only. An *action* is one of exactly four — ``read``,
``write``, ``invoke``, ``manage`` — because an action set that grows per resource
stops being checkable by set membership. Running a generated SQL statement is
``datasource:read``, not a fifth action: the NL2SQL AST guard rejects DML by
construction (C4's sibling rule in `docs/ThreatModel.md`), so *querying* a
datasource is reading it.

**Only ``admin`` holds a wildcard.** ``*:*`` is how ``permission.py`` says an org
administrator is expressed, and it is the reason the bootstrap admin can reach a
capability that does not exist yet. Every other role enumerates its grants, so a
new feature is denied to them by default until somebody decides otherwise — which
is the direction a permission model should fail in.

Grants that no guard requires yet are inert rather than wrong: :meth:`PermissionSet.allows`
is asked about a requirement, never enumerated, so a permission nothing checks
grants nothing.

**The slugs are the Keycloak realm's roles minus their prefix.**
`deploy/keycloak/mnemos-realm.json` defines ``mnemos-admin``, ``mnemos-analyst``
and ``mnemos-user``; these are ``admin``, ``analyst`` and ``user``. Keycloak realm
roles are global to the realm and therefore have to carry a namespace in their
name, while a ``role`` row is already scoped by ``org_id`` and does not — so the
prefix is noise here and its absence is not an oversight. Mapping a realm role to
a local role at just-in-time provisioning (M3.4) is then a prefix strip rather
than a translation table nobody maintains.
"""

from __future__ import annotations

from dataclasses import dataclass

from mnemos.features.identity.domain.permission import Permission, PermissionSet

#: Slug of the role the bootstrap binds to the first admin. Named here because
#: the bootstrap must bind *this* role and M3.6's tests must require against it.
ADMIN_ROLE_SLUG = "admin"


@dataclass(frozen=True, slots=True)
class SystemRole:
    """A role the platform owns, as opposed to one an org author created.

    ``is_system`` on the ``role`` table marks these so a later "delete role"
    endpoint can refuse: an org that deletes its own ``admin`` role has locked
    itself out, and there is no second admin to undo it with.
    """

    slug: str
    name: str
    permissions: PermissionSet

    @property
    def grants(self) -> tuple[str, ...]:
        """The grants as the ``role.permissions`` JSONB column stores them.

        Sorted, so that two runs of the bootstrap write byte-identical JSON and a
        diff of the column means a policy actually changed.
        """
        return tuple(sorted(str(permission) for permission in self.permissions))


def _grants(*raw: str) -> PermissionSet:
    """Build a role's grants from literals, strictly.

    ``PermissionSet.parse`` is deliberately tolerant — a malformed grant already
    sitting in the database must not break a login — but a typo in *this* file
    would silently ship a role with one fewer permission than it reads as having.
    So these are constructed rather than parsed, and a bad literal fails at import.
    """
    return PermissionSet(
        frozenset(Permission(*_split(literal)) for literal in raw),
    )


def _split(literal: str) -> tuple[str, str]:
    resource, separator, action = literal.partition(":")
    if not separator:
        msg = f"a system-role grant must be 'resource:action', got {literal!r}"
        raise ValueError(msg)
    return resource, action


#: Every role the bootstrap seeds, in descending authority. The order is the order
#: they are reported in, so an operator reads the most privileged first.
SYSTEM_ROLES: tuple[SystemRole, ...] = (
    SystemRole(
        slug=ADMIN_ROLE_SLUG,
        name="Administrator",
        # One grant, on purpose. Enumerating an admin's permissions means every
        # new feature ships with its admin locked out until someone remembers to
        # widen a list here, and "remembers to" is not a mechanism.
        permissions=_grants("*:*"),
    ),
    SystemRole(
        slug="analyst",
        name="Analyst",
        permissions=_grants(
            "chat:read",
            "chat:write",
            "context:read",
            "cost:read",
            "datasource:read",
            "document:read",
            "document:write",
            "memory:read",
            "memory:write",
            "prompt:read",
            "tool:invoke",
        ),
    ),
    SystemRole(
        slug="user",
        name="User",
        # No `tool:invoke`: an MCP call has side effects outside this system, and
        # M11 gates it behind an approval anyway. Deny by default is cheaper to
        # widen later than a standing grant is to discover.
        permissions=_grants(
            "chat:read",
            "chat:write",
            "context:read",
            "document:read",
            "memory:read",
        ),
    ),
)

"""Unit tests for the identity domain types (M3.1).

Pure and hermetic: no Docker, no database, microseconds per test. Each test pins a
property the rest of identity relies on — deny-by-default authorization, wildcard
semantics, symmetric tag overlap, the frozen-principal invariant — plus a
subprocess proof that the domain layer imports no SQLAlchemy, which is the
layering rule that keeps it this cheap to test.
"""

from __future__ import annotations

import subprocess
import sys
from uuid import uuid4

import pytest

from mnemos.features.identity.domain import (
    ApiKeyId,
    OrgId,
    Permission,
    PermissionSet,
    Principal,
    PrincipalKind,
    SessionId,
    TagSet,
    UserId,
)

# --------------------------------------------------------------------- permissions


def test_permission_denies_by_default() -> None:
    held = PermissionSet.of(Permission("memory", "read"))
    assert held.allows(Permission("memory", "read")) is True
    # Absent on the action axis, absent on the resource axis, absent entirely.
    assert held.allows(Permission("memory", "write")) is False
    assert held.allows(Permission("document", "read")) is False
    assert PermissionSet.of().allows(Permission("memory", "read")) is False


def test_wildcard_grant_allows_specific_permission() -> None:
    superuser = PermissionSet.of(Permission("*", "*"))
    resource_admin = PermissionSet.of(Permission("memory", "*"))
    action_admin = PermissionSet.of(Permission("*", "read"))

    assert superuser.allows(Permission("memory", "read")) is True
    assert resource_admin.allows(Permission("memory", "read")) is True
    assert resource_admin.allows(Permission("memory", "write")) is True
    # A resource wildcard does not spill over to a different resource.
    assert resource_admin.allows(Permission("document", "read")) is False
    assert action_admin.allows(Permission("memory", "read")) is True
    assert action_admin.allows(Permission("memory", "write")) is False


def test_wildcard_in_a_requirement_is_rejected() -> None:
    held = PermissionSet.of(Permission("*", "*"))
    for bad in (Permission("memory", "*"), Permission("*", "read"), Permission("*", "*")):
        with pytest.raises(ValueError, match="wildcard requirement"):
            held.allows(bad)
    # And the typed constructor a guard uses refuses to build one in the first place.
    with pytest.raises(ValueError, match="must be concrete"):
        Permission.require("memory", "*")


def test_permission_parse_is_tolerant_but_construction_is_strict() -> None:
    # A garbage grant in a role's JSONB is dropped, not fatal.
    parsed = PermissionSet.parse(["memory:read", "nonsense", "", "a:b:c", "  DOC:Read  "])
    assert parsed.allows(Permission("memory", "read")) is True
    assert parsed.allows(Permission("doc", "read")) is True  # normalized to lowercase
    assert len(parsed) == 2
    # Direct construction of a malformed permission raises — guards cannot typo one.
    for bad_resource, bad_action in (("", "read"), ("mem:ory", "read"), ("memory", "re ad")):
        with pytest.raises(ValueError, match="permission"):
            Permission(bad_resource, bad_action)


# --------------------------------------------------------------------------- tags


def test_tag_overlap_is_symmetric_and_empty_set_grants_nothing() -> None:
    a = TagSet.of("finance", "hr")
    b = TagSet.of("hr", "legal")
    disjoint = TagSet.of("engineering")
    empty = TagSet.of()

    assert a.overlaps(b) is True
    assert b.overlaps(a) is True  # symmetric
    assert a.overlaps(disjoint) is False
    # Empty on either side grants nothing, in both directions.
    assert empty.overlaps(a) is False
    assert a.overlaps(empty) is False
    assert empty.overlaps(empty) is False


def test_tag_slugs_normalize_case_insensitively() -> None:
    # tag.slug is CITEXT; the in-memory test must match the database.
    assert TagSet.of("Finance").overlaps(TagSet.of("finance")) is True
    assert len(TagSet.of("HR", "hr", " hr ")) == 1


# ---------------------------------------------------------------------- principal


def _user_principal(**overrides: object) -> Principal:
    base: dict[str, object] = {
        "org_id": OrgId(uuid4()),
        "principal_id": UserId(uuid4()),
        "kind": PrincipalKind.USER,
        "permissions": PermissionSet.of(Permission("memory", "read")),
        "tags": TagSet.of("finance"),
        "session_id": SessionId(uuid4()),
    }
    base.update(overrides)
    return Principal(**base)  # type: ignore[arg-type]


def test_principal_is_frozen() -> None:
    principal = _user_principal()
    with pytest.raises((AttributeError, TypeError)):
        principal.org_id = OrgId(uuid4())  # type: ignore[misc]


def test_principal_delegates_authorization_to_its_types() -> None:
    principal = _user_principal()
    assert principal.has_permission(Permission("memory", "read")) is True
    assert principal.has_permission(Permission("memory", "write")) is False
    assert principal.can_reach(TagSet.of("finance", "legal")) is True
    assert principal.can_reach(TagSet.of("engineering")) is False


def test_user_principal_requires_a_session_not_an_api_key() -> None:
    with pytest.raises(ValueError, match="session"):
        _user_principal(session_id=None)
    with pytest.raises(ValueError, match="session"):
        _user_principal(api_key_id=ApiKeyId(uuid4()))


def test_service_principal_requires_an_api_key_not_a_session() -> None:
    org, pid = OrgId(uuid4()), UserId(uuid4())
    perms, tags = PermissionSet.of(), TagSet.of()
    good = Principal(
        org_id=org,
        principal_id=pid,
        kind=PrincipalKind.SERVICE,
        permissions=perms,
        tags=tags,
        api_key_id=ApiKeyId(uuid4()),
    )
    assert good.kind is PrincipalKind.SERVICE
    with pytest.raises(ValueError, match="API key"):
        Principal(
            org_id=org,
            principal_id=pid,
            kind=PrincipalKind.SERVICE,
            permissions=perms,
            tags=tags,
            session_id=SessionId(uuid4()),
        )


# -------------------------------------------------------------------- layering


def test_domain_imports_no_sqlalchemy() -> None:
    """The domain layer must pull in no SQLAlchemy (ADAPTATION §5 layering rule).

    Run in a fresh interpreter: in the pytest process SQLAlchemy is already
    imported by other test modules, so an in-process ``sys.modules`` check would
    pass vacuously and prove nothing.
    """
    proof = (
        "import sys; import mnemos.features.identity.domain as d; "
        "assert 'sqlalchemy' not in sys.modules, "
        "'identity.domain must not import sqlalchemy'; "
        "assert d.Principal is not None"
    )
    result = subprocess.run(
        [sys.executable, "-c", proof],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr

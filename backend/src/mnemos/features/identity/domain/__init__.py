"""Identity domain: pure types, no SQLAlchemy, no FastAPI, no I/O.

These are the vocabulary the rest of identity — providers, the RBAC guard, the
composition root — is written in. The layering rule (ADAPTATION §5) is that this
package imports nothing from ``adapters`` or ``platform``; that is what lets it be
unit-tested in microseconds and is asserted by ``test_domain_imports_no_sqlalchemy``.
"""

from __future__ import annotations

from mnemos.features.identity.domain.ids import (
    ApiKeyId,
    OrgId,
    ProviderId,
    RoleId,
    SessionId,
    TagId,
    UserId,
)
from mnemos.features.identity.domain.permission import Permission, PermissionSet
from mnemos.features.identity.domain.principal import Principal, PrincipalKind
from mnemos.features.identity.domain.roles import ADMIN_ROLE_SLUG, SYSTEM_ROLES, SystemRole
from mnemos.features.identity.domain.tags import TagSet

__all__ = [
    "ADMIN_ROLE_SLUG",
    "SYSTEM_ROLES",
    "ApiKeyId",
    "OrgId",
    "Permission",
    "PermissionSet",
    "Principal",
    "PrincipalKind",
    "ProviderId",
    "RoleId",
    "SessionId",
    "SystemRole",
    "TagId",
    "TagSet",
    "UserId",
]

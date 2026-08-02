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
from mnemos.features.identity.domain.tags import TagSet
from mnemos.features.identity.domain.token import (
    ACCESS_TOKEN_CLAIMS,
    FORBIDDEN_CLAIMS,
    REFRESH_SECRET_BYTES,
    REFRESH_TOKEN_SEPARATOR,
    AccessTokenClaims,
    RefreshCredential,
    TokenPair,
)

__all__ = [
    "ACCESS_TOKEN_CLAIMS",
    "FORBIDDEN_CLAIMS",
    "REFRESH_SECRET_BYTES",
    "REFRESH_TOKEN_SEPARATOR",
    "AccessTokenClaims",
    "ApiKeyId",
    "OrgId",
    "Permission",
    "PermissionSet",
    "Principal",
    "PrincipalKind",
    "ProviderId",
    "RefreshCredential",
    "RoleId",
    "SessionId",
    "TagId",
    "TagSet",
    "TokenPair",
    "UserId",
]

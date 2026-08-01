"""Authentication strategies: Strategy + Factory, plus the composition root.

The seam that turns a presented credential into a verified
:class:`~.base.AuthenticatedSubject`. Two strategies behind two protocols —
internal password auth and OIDC — chosen by an ``identity_provider`` row rather
than by a branch in the login endpoint, so the endpoint never learns which one it
got and SAML later is a row plus an adapter.

This package imports **neither SQLAlchemy nor FastAPI**: persistence arrives
through the ports in :mod:`.ports` (implemented in
``features/identity/adapters/directory.py``) and HTTP is M3.3's problem. Both
exclusions are asserted by a subprocess test rather than assumed.
"""

from __future__ import annotations

from mnemos.features.identity.providers.base import (
    AUTHENTICATION_FAILED,
    AuthenticatedSubject,
    AuthProvider,
    CredentialAuthProvider,
    TokenAuthProvider,
    denied,
)
from mnemos.features.identity.providers.factory import ProviderFactory
from mnemos.features.identity.providers.internal import InternalProvider
from mnemos.features.identity.providers.oidc import (
    ALLOWED_ALGORITHMS,
    HttpJwksCache,
    JwksSource,
    OidcConfig,
    OidcProvider,
)
from mnemos.features.identity.providers.ports import (
    OrgDirectory,
    OrgRecord,
    ProviderRecord,
    UserCredentialRecord,
    UserDirectory,
)

__all__ = [
    "ALLOWED_ALGORITHMS",
    "AUTHENTICATION_FAILED",
    "AuthProvider",
    "AuthenticatedSubject",
    "CredentialAuthProvider",
    "HttpJwksCache",
    "InternalProvider",
    "JwksSource",
    "OidcConfig",
    "OidcProvider",
    "OrgDirectory",
    "OrgRecord",
    "ProviderFactory",
    "ProviderRecord",
    "TokenAuthProvider",
    "UserCredentialRecord",
    "UserDirectory",
    "denied",
]

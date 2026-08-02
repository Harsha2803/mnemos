"""Shared OIDC test material: a signing key, a JWKS, minted tokens, a fake IdP.

Used by both `test_identity_providers.py` (M3.2, the validator) and
`test_oidc_login_flow.py` (M3.3, the round trip). Kept as plain functions rather
than fixtures so either module can compose them however it needs.

The defaults here describe a *genuine* Keycloak token and a *complete* discovery
document. That matters: every rejection test in both modules works by changing one
argument, so what a test is actually probing is visible at the call site, and a
document trimmed to whatever the code currently reads would let a missing endpoint
pass unnoticed.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import jwt
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

ISSUER_INTERNAL = "http://keycloak:8080/realms/mnemos"
ISSUER_PUBLIC = "http://localhost:8080/realms/mnemos"
CLIENT_ID = "mnemos-web"
KID = "test-signing-key"
SUBJECT = "9f1c0b2e-keycloak-subject"


def generate_key() -> rsa.RSAPrivateKey:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


def jwk_for(key: rsa.RSAPrivateKey, kid: str = KID) -> dict[str, Any]:
    jwk = RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    assert isinstance(jwk, dict)
    return {**jwk, "kid": kid, "alg": "RS256", "use": "sig"}


def public_key_pem(key: rsa.RSAPrivateKey) -> bytes:
    return key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )


def discovery_document(issuer: str = ISSUER_INTERNAL, **overrides: Any) -> dict[str, Any]:
    """The subset of `/.well-known/openid-configuration` this system reads."""
    return {
        "issuer": issuer,
        "authorization_endpoint": f"{issuer}/protocol/openid-connect/auth",
        "token_endpoint": f"{issuer}/protocol/openid-connect/token",
        "jwks_uri": f"{issuer}/protocol/openid-connect/certs",
        **overrides,
    }


def mint(
    key: rsa.RSAPrivateKey,
    *,
    issuer: str = ISSUER_PUBLIC,
    azp: str | None = CLIENT_ID,
    audience: Any = "account",
    expires_in_s: int = 300,
    algorithm: str = "RS256",
    kid: str = KID,
    **extra: Any,
) -> str:
    """A Keycloak-shaped token. Defaults are the genuine article."""
    now = datetime.now(UTC)
    claims: dict[str, Any] = {
        "iss": issuer,
        "sub": SUBJECT,
        "aud": audience,
        "exp": now + timedelta(seconds=expires_in_s),
        "iat": now,
        "email": "ada@example.test",
        "preferred_username": "ada",
        "name": "Ada Lovelace",
        **extra,
    }
    if azp is not None:
        claims["azp"] = azp
    return jwt.encode(claims, key, algorithm=algorithm, headers={"kid": kid})


def b64(value: dict[str, Any]) -> str:
    """base64url without padding — the JWS segment encoding."""
    raw = json.dumps(value, separators=(",", ":")).encode()
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def forge_hmac_token(claims: dict[str, Any], secret: bytes, kid: str = KID) -> str:
    """Hand-build an HS256 token — the RS256→HS256 confusion forgery.

    By hand because PyJWT refuses to *mint* an HMAC token from a PEM public key.
    That is a defence on the signing side and no help on the verifying side; an
    attacker is not using PyJWT to build the forgery.
    """
    header = b64({"alg": "HS256", "typ": "JWT", "kid": kid})
    payload = b64(claims)
    signing_input = f"{header}.{payload}".encode()
    signature = (
        base64.urlsafe_b64encode(hmac.new(secret, signing_input, hashlib.sha256).digest())
        .rstrip(b"=")
        .decode()
    )
    return f"{header}.{payload}.{signature}"


class FakeIdp:
    """An `httpx.MockTransport` standing in for Keycloak.

    Serves discovery, JWKS and the token endpoint, and records what it was asked
    so a test can assert on the *request* — which is where PKCE and split-horizon
    correctness actually live. `token_response` is swappable so failure paths can
    be exercised without a second transport.
    """

    def __init__(
        self,
        key: rsa.RSAPrivateKey,
        *,
        issuer: str = ISSUER_INTERNAL,
        token_response: httpx.Response | None = None,
    ) -> None:
        self._key = key
        self._issuer = issuer
        self._token_response = token_response
        self.token_requests: list[dict[str, str]] = []
        self.requested_urls: list[str] = []

    def handle(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        self.requested_urls.append(url)
        if url.endswith("/.well-known/openid-configuration"):
            return httpx.Response(200, json=discovery_document(self._issuer))
        if url.endswith("/protocol/openid-connect/certs"):
            return httpx.Response(200, json={"keys": [jwk_for(self._key)]})
        if url.endswith("/protocol/openid-connect/token"):
            self.token_requests.append(dict(httpx.QueryParams(request.content.decode())))
            if self._token_response is not None:
                return self._token_response
            return httpx.Response(
                200,
                json={
                    "access_token": mint(self._key),
                    "id_token": mint(self._key, audience=CLIENT_ID),
                    "token_type": "Bearer",
                    "expires_in": 300,
                },
            )
        return httpx.Response(404, json={"error": "not_found", "url": url})

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

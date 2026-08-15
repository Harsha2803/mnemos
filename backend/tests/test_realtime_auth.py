"""`B1` deliverable 3 — the realtime gateway's WebSocket handshake, on the wire.

Same shape as `test_route_guard.py`: the real `create_app()`, the real
handshake, a **fake** `PrincipalRepository` (identity is hermetic here, same
reasoning — the claim under test is "the gateway calls the resolver and obeys
its answer", not "the SQL is correct", which `test_principal_repository.py`
already owns) over a **real** Redis (the `redis_url` fixture), because the
claim that actually matters — a token for org A cannot reach org B's
channel — is a claim about which Redis topic gets subscribed to, and a fake
pub/sub would only prove the fake isolates.

The attack shape this file exists to close, verbatim from `TRACKER.md` §5: "a
token for org A cannot subscribe to org B's ingestion channel even by typing
the channel name directly into the WS URL". `test_a_channel_kind_that_embeds_
another_orgs_id_is_refused` is that attack, run against the real route rather
than against a call site that merely looks like it enforces it
(`ThreatModel.md` §3⑤ / the "never ship a second defence as if it were the
first" rule).
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

import pytest
import redis
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import Uuid7Generator
from mnemos.entrypoints.realtime.main import BEARER_SUBPROTOCOL, create_app
from mnemos.features.identity.application.principals import PrincipalResolver, UserAuthority
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.platform.cache import Cache

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)

ORG_A = OrgId(uuid4())
USER_A = UserId(uuid4())
SESSION_A = SessionId(uuid4())

ORG_B = OrgId(uuid4())
USER_B = UserId(uuid4())
SESSION_B = SessionId(uuid4())


class FakeRepository:
    """`PrincipalRepository` in memory, seeded with two orgs.

    Two orgs rather than one is the point: `test_route_guard.py` proves the
    guard denies a bad credential, but nothing there proves a *good* credential
    for one tenant is scoped to that tenant. That is only a claim this file's
    two-org setup can make.
    """

    def __init__(self) -> None:
        self.authorities: dict[tuple[OrgId, UserId], UserAuthority] = {
            (ORG_A, USER_A): UserAuthority(
                user_id=USER_A,
                org_id=ORG_A,
                org_slug="realtime-org-a",
                email="ada@realtime.test",
                display_name="Ada",
                is_active=True,
                permissions=(),
                tags=(),
            ),
            (ORG_B, USER_B): UserAuthority(
                user_id=USER_B,
                org_id=ORG_B,
                org_slug="realtime-org-b",
                email="bob@realtime.test",
                display_name="Bob",
                is_active=True,
                permissions=(),
                tags=(),
            ),
        }
        self.live_sessions: set[SessionId] = {SESSION_A, SESSION_B}

    async def load_authority(self, org_id: OrgId, user_id: UserId) -> UserAuthority | None:
        return self.authorities.get((org_id, user_id))

    async def session_is_live(self, org_id: OrgId, session_id: SessionId, at: datetime) -> bool:
        return session_id in self.live_sessions


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER),
        clock=clock,
        ids=Uuid7Generator(),
    )


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def redis_client(redis_url: str) -> Iterator[redis.Redis]:
    client: redis.Redis = redis.Redis.from_url(redis_url, decode_responses=True)
    try:
        yield client
    finally:
        client.close()


@pytest.fixture
def client(
    codec: PlatformTokenCodec,
    clock: FrozenClock,
    repository: FakeRepository,
    redis_url: str,
) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(codec=codec, repository=repository, clock=clock)
        app.state.cache = Cache(Settings(redis_url=redis_url))
        yield test_client


def _subprotocols(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> list[str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return [BEARER_SUBPROTOCOL, token]


def _org_a_subprotocols(codec: PlatformTokenCodec) -> list[str]:
    return _subprotocols(codec, user=USER_A, org=ORG_A, session=SESSION_A)


# ------------------------------------------------------- the two acceptance tests


def test_a_genuine_token_reaches_the_channel_and_receives_what_is_published(
    client: TestClient, codec: PlatformTokenCodec, redis_client: redis.Redis
) -> None:
    """The control. Every denial below is one mutation away from this."""
    with client.websocket_connect("/ws/ingestion", subprotocols=_org_a_subprotocols(codec)) as ws:
        assert ws.accepted_subprotocol == BEARER_SUBPROTOCOL
        assert ws.receive_json() == {"type": "subscribed", "channel": "ingestion"}

        redis_client.publish(f"mnemos:org:{ORG_A}:ingestion", json.dumps({"job_id": "a-real"}))

        assert ws.receive_json() == {"job_id": "a-real"}


def test_a_token_for_org_a_never_receives_what_is_published_on_org_bs_channel(
    client: TestClient, codec: PlatformTokenCodec, redis_client: redis.Redis
) -> None:
    """The claim `TRACKER.md` §5 states for deliverable 3: cross-org leakage is
    impossible, checked over a real Redis rather than a call site that merely
    looks like it enforces it.

    Org B's message is published first. Redis pub/sub only ever delivers a
    message to a client subscribed to that exact topic — there is no wildcard,
    no backlog and no race to arbitrate — so if the gateway had derived org A's
    topic from anything other than org A's own verified token (a query
    parameter, a header the client controls, the URL), this test is where that
    bug would surface as org B's payload arriving first.
    """
    with client.websocket_connect("/ws/ingestion", subprotocols=_org_a_subprotocols(codec)) as ws:
        assert ws.receive_json() == {"type": "subscribed", "channel": "ingestion"}

        redis_client.publish(f"mnemos:org:{ORG_B}:ingestion", json.dumps({"job_id": "b-leaked"}))
        redis_client.publish(f"mnemos:org:{ORG_A}:ingestion", json.dumps({"job_id": "a-real"}))

        assert ws.receive_json() == {"job_id": "a-real"}


def test_a_channel_kind_that_embeds_another_orgs_id_is_refused(
    client: TestClient, codec: PlatformTokenCodec
) -> None:
    """The literal attack `TRACKER.md` §5 names: hand-typing org B's id into
    the WS URL with org A's own token. Refused before `accept()` because the
    channel *kind* — the only thing the URL is allowed to name — is not
    `"ingestion"`; the org segment is not something the URL has ever been
    allowed to carry, genuine or forged."""
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            f"/ws/org:{ORG_B}:ingestion", subprotocols=_org_a_subprotocols(codec)
        ),
    ):
        pass

    assert exc_info.value.code == 1008


def test_an_unknown_channel_kind_is_refused_even_with_a_genuine_token(
    client: TestClient, codec: PlatformTokenCodec
) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect(
            "/ws/not-a-real-channel-kind", subprotocols=_org_a_subprotocols(codec)
        ),
    ):
        pass

    assert exc_info.value.code == 1008


# ------------------------------------------------------------ what the handshake refuses


@pytest.mark.parametrize(
    ("subprotocols", "why"),
    [
        (None, "no subprotocol offered at all"),
        ([BEARER_SUBPROTOCOL], "the token half missing"),
        (["not-bearer", "whatever"], "the wrong first subprotocol"),
        ([BEARER_SUBPROTOCOL, "not.a.jwt"], "a token that is not a JWT"),
    ],
)
def test_every_malformed_handshake_is_refused_before_accept(
    client: TestClient, subprotocols: list[str] | None, why: str
) -> None:
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/ingestion", subprotocols=subprotocols),
    ):
        pass

    assert exc_info.value.code == 1008, why


def test_a_token_signed_with_a_different_secret_is_refused(client: TestClient) -> None:
    """The forgery the whole scheme exists to stop, at the boundary rather than
    at the codec — same control `test_route_guard.py` runs for the HTTP guard."""
    forged = PlatformTokenCodec(
        config=PlatformTokenConfig(
            secret="another-thirty-two-byte-or-longer-secret", issuer=ISSUER
        ),
        clock=FrozenClock(NOW),
        ids=Uuid7Generator(),
    )

    subprotocols = _subprotocols(forged, user=USER_A, org=ORG_A, session=SESSION_A)
    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/ingestion", subprotocols=subprotocols),
    ):
        pass

    assert exc_info.value.code == 1008


def test_an_expired_token_is_refused(
    client: TestClient, codec: PlatformTokenCodec, clock: FrozenClock
) -> None:
    subprotocols = _org_a_subprotocols(codec)
    clock.advance(seconds=900)

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/ingestion", subprotocols=subprotocols),
    ):
        pass

    assert exc_info.value.code == 1008


def test_a_revoked_session_is_refused(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    """Why `sid` is in the token at all — the same property
    `test_route_guard.py`'s `test_a_revoked_session_kills_the_access_token_it_minted`
    pins for the HTTP guard, pinned here for the WS one too, since the two
    guards share `PrincipalResolver` but not a call site."""
    subprotocols = _org_a_subprotocols(codec)
    repository.live_sessions.discard(SESSION_A)

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/ingestion", subprotocols=subprotocols),
    ):
        pass

    assert exc_info.value.code == 1008


def test_a_deactivated_users_token_is_refused(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository
) -> None:
    repository.authorities[(ORG_A, USER_A)] = replace(
        repository.authorities[(ORG_A, USER_A)], is_active=False
    )

    with (
        pytest.raises(WebSocketDisconnect) as exc_info,
        client.websocket_connect("/ws/ingestion", subprotocols=_org_a_subprotocols(codec)),
    ):
        pass

    assert exc_info.value.code == 1008

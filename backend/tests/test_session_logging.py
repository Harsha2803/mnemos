"""Per-session log files — a developer convenience, not a product feature.

Two levels, same shape as `test_platform_tokens.py`/`test_route_guard.py`: the
processor itself, hermetic and fast (`core/logging.py`'s `_session_log_writer`
via `configure_logging`), then the same claim proved on the wire — a genuine
authenticated request through the real `enforce_authentication` guard writes
its session's log lines to the right file, and nothing else does.

**Every test here points `session_log_dir` at `tmp_path`.** The feature is off
by default precisely so `pytest` never writes into the real `logs/sessions/` in
the working tree (`core/logging.py`'s own docstring states this); a test that
turned it on without redirecting the directory would defeat the property it is
testing.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from mnemos.core.clock import FrozenClock
from mnemos.core.ids import Uuid7Generator
from mnemos.core.logging import (
    configure_logging,
    get_logger,
    org_id_var,
    session_id_var,
    user_id_var,
)
from mnemos.entrypoints.api.main import create_app
from mnemos.features.identity.application.principals import PrincipalResolver, UserAuthority
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 16, 12, 0, tzinfo=UTC)

ORG = OrgId(uuid4())
USER = UserId(uuid4())
SESSION = SessionId(uuid4())

UNGUARDED_PATH = "/_probe/session_logging"


# ------------------------------------------------------- the processor, hermetic


def test_a_bound_session_id_is_written_to_its_own_file(tmp_path: Path) -> None:
    configure_logging(session_log_enabled=True, session_log_dir=tmp_path)
    token = session_id_var.set("session-one")
    try:
        get_logger("test").info("something.happened", detail="x")
    finally:
        session_id_var.reset(token)

    lines = (tmp_path / "session-one.log").read_text().splitlines()
    assert len(lines) == 1
    payload = json.loads(lines[0])
    assert payload["event"] == "something.happened"
    assert payload["detail"] == "x"
    assert payload["session_id"] == "session-one"


def test_org_and_user_ids_ride_along_when_bound(tmp_path: Path) -> None:
    configure_logging(session_log_enabled=True, session_log_dir=tmp_path)
    session_token = session_id_var.set("session-two")
    org_token = org_id_var.set("org-x")
    user_token = user_id_var.set("user-x")
    try:
        get_logger("test").info("with.identity")
    finally:
        session_id_var.reset(session_token)
        org_id_var.reset(org_token)
        user_id_var.reset(user_token)

    payload = json.loads((tmp_path / "session-two.log").read_text())
    assert payload["org_id"] == "org-x"
    assert payload["user_id"] == "user-x"


def test_a_log_line_with_no_bound_session_writes_no_file(tmp_path: Path) -> None:
    configure_logging(session_log_enabled=True, session_log_dir=tmp_path)

    get_logger("test").info("nobody.is.logged.in")

    assert list(tmp_path.iterdir()) == []


def test_two_sessions_never_share_a_file(tmp_path: Path) -> None:
    configure_logging(session_log_enabled=True, session_log_dir=tmp_path)
    for session in ("session-a", "session-b", "session-a"):
        token = session_id_var.set(session)
        try:
            get_logger("test").info("event", session=session)
        finally:
            session_id_var.reset(token)

    assert sorted(p.name for p in tmp_path.iterdir()) == ["session-a.log", "session-b.log"]
    assert len((tmp_path / "session-a.log").read_text().splitlines()) == 2
    assert len((tmp_path / "session-b.log").read_text().splitlines()) == 1


def test_the_feature_disabled_writes_nothing_even_with_a_bound_session(tmp_path: Path) -> None:
    """The default. `pytest` authenticates hundreds of sessions across the suite;
    this is the property that keeps every one of them off disk."""
    configure_logging(session_log_enabled=False, session_log_dir=tmp_path)
    token = session_id_var.set("should-never-appear")
    try:
        get_logger("test").info("event")
    finally:
        session_id_var.reset(token)

    assert not tmp_path.exists() or list(tmp_path.iterdir()) == []


# --------------------------------------------------------- wired through the real guard


class FakeRepository:
    def __init__(self) -> None:
        self.authority = UserAuthority(
            user_id=USER,
            org_id=ORG,
            org_slug="session-log-org",
            email="ada@session-log.test",
            display_name="Ada",
            is_active=True,
            permissions=(),
            tags=(),
        )
        self.live_sessions: set[SessionId] = {SESSION}

    async def load_authority(self, org_id: OrgId, user_id: UserId) -> UserAuthority | None:
        if org_id != self.authority.org_id or user_id != self.authority.user_id:
            return None
        return self.authority

    async def session_is_live(self, org_id: OrgId, session_id: SessionId, at: datetime) -> bool:
        return session_id in self.live_sessions


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER), clock=clock, ids=Uuid7Generator()
    )


@pytest.fixture
def repository() -> FakeRepository:
    return FakeRepository()


@pytest.fixture
def client(
    codec: PlatformTokenCodec,
    repository: FakeRepository,
    clock: FrozenClock,
    tmp_path: Path,
) -> Iterator[TestClient]:
    app = create_app()

    async def unguarded() -> dict[str, bool]:
        return {"reached": True}

    app.add_api_route(UNGUARDED_PATH, unguarded, methods=["GET"])

    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(codec=codec, repository=repository, clock=clock)
        # The app's own lifespan already called `configure_logging` from real
        # `Settings` (feature off, real `logs/sessions/`); this second call
        # replaces that global config with one pointed at `tmp_path`, the same
        # way every other fixture in this suite overrides `app.state` after
        # `TestClient.__enter__` rather than threading a fake through `Settings`.
        configure_logging(session_log_enabled=True, session_log_dir=tmp_path)
        yield test_client


def _bearer(codec: PlatformTokenCodec) -> dict[str, str]:
    token, _ = codec.mint(subject=USER, org_id=ORG, session_id=SESSION)
    return {"Authorization": f"Bearer {token}"}


def test_a_genuine_authenticated_request_writes_that_sessions_log_file(
    client: TestClient, codec: PlatformTokenCodec, tmp_path: Path
) -> None:
    response = client.get(UNGUARDED_PATH, headers=_bearer(codec))
    assert response.status_code == 200

    log_file = tmp_path / f"{SESSION}.log"
    assert log_file.exists()
    lines = [json.loads(line) for line in log_file.read_text().splitlines()]
    assert any(entry.get("event") == "http.request" for entry in lines)
    assert all(entry["session_id"] == str(SESSION) for entry in lines)
    assert all(entry["org_id"] == str(ORG) for entry in lines)
    assert all(entry["user_id"] == str(USER) for entry in lines)


def test_an_unauthenticated_request_writes_no_session_file_at_all(
    client: TestClient, tmp_path: Path
) -> None:
    response = client.get(UNGUARDED_PATH)
    assert response.status_code == 401

    assert list(tmp_path.iterdir()) == []


def test_the_bound_session_does_not_leak_into_a_request_that_follows_it(
    client: TestClient, codec: PlatformTokenCodec, tmp_path: Path
) -> None:
    """Why `enforce_authentication` resets the contextvars in a `finally` rather
    than leaving them set for the rest of the process: without the reset, an
    unauthenticated request arriving right after an authenticated one would
    still carry the previous caller's session id into its own log lines."""
    client.get(UNGUARDED_PATH, headers=_bearer(codec))
    client.get("/healthz")

    log_file = tmp_path / f"{SESSION}.log"
    entries = [json.loads(line) for line in log_file.read_text().splitlines()]
    assert not any(entry.get("path") == "/healthz" for entry in entries)


def test_two_different_sessions_land_in_two_different_files(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository, tmp_path: Path
) -> None:
    other_session = SessionId(uuid4())
    repository.live_sessions.add(other_session)
    other_token, _ = codec.mint(subject=USER, org_id=ORG, session_id=other_session)

    client.get(UNGUARDED_PATH, headers=_bearer(codec))
    client.get(UNGUARDED_PATH, headers={"Authorization": f"Bearer {other_token}"})

    assert (tmp_path / f"{SESSION}.log").exists()
    assert (tmp_path / f"{other_session}.log").exists()


def test_a_denied_request_still_writes_nothing_for_the_forged_token(
    client: TestClient, tmp_path: Path
) -> None:
    """A forged token never resolves a caller, so there is no session id to bind
    — the same "identity comes from the verified token, not the attempt" property
    the guard itself enforces, now also true of what lands on disk."""
    forged = PlatformTokenCodec(
        config=PlatformTokenConfig(
            secret="another-thirty-two-byte-or-longer-secret", issuer=ISSUER
        ),
        clock=FrozenClock(NOW),
        ids=Uuid7Generator(),
    )
    token, _ = forged.mint(subject=USER, org_id=ORG, session_id=SESSION)

    response = client.get(UNGUARDED_PATH, headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []


def test_a_deactivated_users_request_writes_nothing_either(
    client: TestClient, codec: PlatformTokenCodec, repository: FakeRepository, tmp_path: Path
) -> None:
    repository.authority = replace(repository.authority, is_active=False)

    response = client.get(UNGUARDED_PATH, headers=_bearer(codec))

    assert response.status_code == 401
    assert list(tmp_path.iterdir()) == []

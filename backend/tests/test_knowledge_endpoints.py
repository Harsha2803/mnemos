"""`A2` — upload, retrieval and the RAG flow, against a real Postgres.

The claims here are claims about the *database* — that RLS confines a document
to its org, that the ACL predicate runs inside the scan rather than after it,
that a superseded revision never appears in a candidate set — and a fake would
only prove the fake. Same argument `test_principal_repository.py` and
`test_chat_endpoints.py` make.

Only the model and the object store are faked: nothing here needs a running
Ollama or MinIO, and `test_llm_gateway.py` already covers the one adapter that
talks to a model.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Iterator, Sequence
from datetime import UTC, datetime, timedelta
from uuid import UUID

import asyncpg
import pytest
import pytest_asyncio
from fastapi.testclient import TestClient

from mnemos.core.clock import FrozenClock
from mnemos.core.config import Settings
from mnemos.core.ids import Uuid7Generator, uuid7
from mnemos.entrypoints.api.main import create_app
from mnemos.entrypoints.api.security import public_route_paths
from mnemos.features.chat.adapters.repository import SqlChatRepository
from mnemos.features.chat.application.service import ChatService
from mnemos.features.identity.adapters.principals import SqlPrincipalRepository
from mnemos.features.identity.application.principals import PrincipalResolver
from mnemos.features.identity.domain import OrgId, SessionId, UserId
from mnemos.features.identity.providers import PlatformTokenCodec, PlatformTokenConfig
from mnemos.features.knowledge.adapters.repository import KnowledgeRepository
from mnemos.features.knowledge.adapters.retrieval import SqlRetriever
from mnemos.features.knowledge.application.service import KnowledgeService
from mnemos.features.knowledge.domain import DocumentId, HashingEmbedder, HeuristicTokenizer
from mnemos.features.llm.domain.model import ChatCompletion, ChatDone, ChatStreamEvent, ChatTurn
from mnemos.features.observability.adapters.repository import SqlAuditRepository
from mnemos.flows.rag.application import RagFlow
from mnemos.platform.db import Database

from .conftest import APP_PASSWORD, Postgres

SECRET = "a-thirty-two-byte-or-longer-signing-secret"
ISSUER = "mnemos"
NOW = datetime(2026, 8, 8, 12, 0, tzinfo=UTC)

EMBEDDING_DIM = 384


class Seed:
    def __init__(
        self,
        org_a: OrgId,
        user_a: UserId,
        session_a: SessionId,
        finance_tag: UUID,
        org_b: OrgId,
        user_b: UserId,
        session_b: SessionId,
    ) -> None:
        self.org_a = org_a
        self.user_a = user_a
        self.session_a = session_a
        self.finance_tag = finance_tag
        self.org_b = org_b
        self.user_b = user_b
        self.session_b = session_b


@pytest_asyncio.fixture
async def seeded(postgres: Postgres) -> AsyncIterator[Seed]:
    ids = Seed(
        org_a=OrgId(uuid7()),
        user_a=UserId(uuid7()),
        session_a=SessionId(uuid7()),
        finance_tag=uuid7(),
        org_b=OrgId(uuid7()),
        user_b=UserId(uuid7()),
        session_b=SessionId(uuid7()),
    )
    conn = await asyncpg.connect(postgres.owner_dsn)
    try:
        for org_id, slug, user_id, session_id, email in (
            (ids.org_a, "kn-org-a", ids.user_a, ids.session_a, "ada@kn.test"),
            (ids.org_b, "kn-org-b", ids.user_b, ids.session_b, "bob@kn.test"),
        ):
            await conn.execute(
                "INSERT INTO org (id, slug, name) VALUES ($1, $2, $3)", org_id, slug, slug
            )
            await conn.execute(
                "INSERT INTO app_user (id, org_id, email, display_name) VALUES ($1, $2, $3, $4)",
                user_id,
                org_id,
                email,
                email,
            )
            await conn.execute(
                "INSERT INTO session (id, org_id, user_id, refresh_token_hash, expires_at) "
                "VALUES ($1, $2, $3, $4, $5)",
                session_id,
                org_id,
                user_id,
                f"hash-for-{slug}",
                NOW + timedelta(days=14),
            )
        await conn.execute(
            "INSERT INTO tag (id, org_id, slug, name) VALUES ($1, $2, $3, $4)",
            ids.finance_tag,
            ids.org_a,
            "finance",
            "Finance",
        )
        yield ids
        await conn.execute("DELETE FROM org WHERE id = ANY($1::uuid[])", [ids.org_a, ids.org_b])
    finally:
        await conn.close()


@pytest_asyncio.fixture
async def db(postgres: Postgres) -> AsyncIterator[Database]:
    database = Database(
        Settings(
            env="test",  # type: ignore[arg-type]
            database_url=postgres.app_url,
            app_database_password=APP_PASSWORD,  # type: ignore[arg-type]
        )
    )
    try:
        yield database
    finally:
        await database.dispose()


@pytest.fixture
def clock() -> FrozenClock:
    return FrozenClock(NOW)


@pytest.fixture
def codec(clock: FrozenClock) -> PlatformTokenCodec:
    return PlatformTokenCodec(
        config=PlatformTokenConfig(secret=SECRET, issuer=ISSUER), clock=clock, ids=Uuid7Generator()
    )


class InMemoryObjectStore:
    """`ObjectStore` in a dict. The S3 adapter is boto3 over MinIO and needs a
    running MinIO to prove anything; what these tests care about is that the
    *service* stores and removes bytes at all, which is the same either way."""

    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    async def put(self, key: str, data: bytes, *, content_type: str) -> None:
        self.objects[key] = data

    async def get(self, key: str) -> bytes:
        return self.objects[key]

    async def delete(self, key: str) -> None:
        self.objects.pop(key, None)


class ScriptedChatModel:
    """A model whose answer is fixed, so a RAG test asserts on retrieval and
    citation wiring rather than on what a 3B model happened to say."""

    def __init__(self, answer: str = "The answer is here [1].") -> None:
        self._answer = answer
        self.turns_seen: list[list[ChatTurn]] = []

    @property
    def model_name(self) -> str:
        return "scripted-model"

    async def stream(self, messages: Sequence[ChatTurn]) -> AsyncIterator[ChatStreamEvent]:
        from mnemos.features.llm.domain.model import ChatToken

        self.turns_seen.append(list(messages))
        yield ChatToken(text=self._answer)
        yield ChatDone(finish_reason="stop", prompt_tokens=10, completion_tokens=5)

    async def complete(self, messages: Sequence[ChatTurn]) -> ChatCompletion:
        return ChatCompletion(
            content=self._answer, finish_reason="stop", prompt_tokens=10, completion_tokens=5
        )

    async def health(self) -> None:
        return None


def build_knowledge(
    db: Database, objects: InMemoryObjectStore, *, audit: SqlAuditRepository | None = None
) -> KnowledgeService:
    return KnowledgeService(
        repository=KnowledgeRepository(db, Uuid7Generator()),
        retriever=SqlRetriever(db),
        objects=objects,
        embedder=HashingEmbedder(dim=EMBEDDING_DIM),
        tokenizer=HeuristicTokenizer(),
        rrf_k=60,
        near_duplicate_threshold=0.86,
        audit=audit,
    )


@pytest.fixture
def objects() -> InMemoryObjectStore:
    return InMemoryObjectStore()


@pytest.fixture
def audit_repository(db: Database) -> SqlAuditRepository:
    return SqlAuditRepository(db, Uuid7Generator())


@pytest.fixture
def model() -> ScriptedChatModel:
    return ScriptedChatModel()


@pytest.fixture
def client(
    codec: PlatformTokenCodec,
    clock: FrozenClock,
    db: Database,
    objects: InMemoryObjectStore,
    model: ScriptedChatModel,
    audit_repository: SqlAuditRepository,
) -> Iterator[TestClient]:
    app = create_app()
    with TestClient(app, base_url="http://testserver") as test_client:
        app.state.principals = PrincipalResolver(
            codec=codec, repository=SqlPrincipalRepository(db), clock=clock
        )
        knowledge = build_knowledge(db, objects, audit=audit_repository)
        app.state.knowledge_service = knowledge
        app.state.chat_service = ChatService(
            repository=SqlChatRepository(db, Uuid7Generator()), model=model, history_turns=12
        )
        app.state.rag_flow = RagFlow(
            chat_repository=SqlChatRepository(db, Uuid7Generator()),
            knowledge=knowledge,
            model=model,
            token_budget=3000,
            retrieval_k=8,
        )
        yield test_client


def bearer(
    codec: PlatformTokenCodec, *, user: UserId, org: OrgId, session: SessionId
) -> dict[str, str]:
    token, _ = codec.mint(subject=user, org_id=org, session_id=session)
    return {"Authorization": f"Bearer {token}"}


def _headers(codec: PlatformTokenCodec, seeded: Seed) -> dict[str, str]:
    return bearer(codec, user=seeded.user_a, org=seeded.org_a, session=seeded.session_a)


def upload(client: TestClient, headers: dict[str, str], name: str, body: str) -> dict[str, object]:
    response = client.post(
        "/api/v1/knowledge/documents",
        headers=headers,
        files={"file": (name, body.encode(), "text/plain")},
    )
    assert response.status_code == 201, response.text
    return dict(response.json())


def _parse_sse(raw: bytes) -> list[tuple[str, dict[str, object]]]:
    frames: list[tuple[str, dict[str, object]]] = []
    for block in raw.decode().split("\n\n"):
        if not block.strip():
            continue
        event_line, data_line = block.split("\n", 1)
        frames.append(
            (event_line.removeprefix("event: "), json.loads(data_line.removeprefix("data: ")))
        )
    return frames


# ------------------------------------------------------------------- upload


def test_uploading_the_same_bytes_twice_is_a_no_op(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    """Through the endpoint, not asserted against the migration — a
    content-hash constraint that exists and is never reached is not
    deduplication."""
    headers = _headers(codec, seeded)
    body = "Carry-over of unused leave is capped at five working days."

    first = upload(client, headers, "policy.txt", body)
    second = upload(client, headers, "policy-copy.txt", body)

    assert first["id"] == second["id"]
    listed = client.get("/api/v1/knowledge/documents", headers=headers).json()
    assert len(listed) == 1


def test_an_uploaded_document_is_chunked_and_embedded(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    body = "\n\n".join(f"Paragraph {i} about quarterly revenue figures." for i in range(8))

    document = upload(client, headers, "revenue.txt", body)

    assert document["status"] == "ready"
    assert int(document["chunk_count"]) > 0  # type: ignore[call-overload]


def test_the_knowledge_routes_are_authenticated_by_default(client: TestClient) -> None:
    paths = public_route_paths("/api/v1")
    assert not any(p.startswith("/api/v1/knowledge") for p in paths)

    assert client.get("/api/v1/knowledge/documents").status_code == 401


def test_a_document_from_another_org_is_not_readable(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    document = upload(client, _headers(codec, seeded), "secret.txt", "org A internal figures")

    org_b = bearer(codec, user=seeded.user_b, org=seeded.org_b, session=seeded.session_b)
    response = client.get(f"/api/v1/knowledge/documents/{document['id']}", headers=org_b)

    assert response.status_code == 404


def test_deleting_a_document_removes_its_chunks_and_its_bytes(
    client: TestClient,
    codec: PlatformTokenCodec,
    seeded: Seed,
    objects: InMemoryObjectStore,
    postgres: Postgres,
) -> None:
    headers = _headers(codec, seeded)
    document = upload(client, headers, "temp.txt", "some content to be deleted later on")
    assert objects.objects

    assert (
        client.delete(f"/api/v1/knowledge/documents/{document['id']}", headers=headers).status_code
        == 204
    )

    assert (
        client.get(f"/api/v1/knowledge/documents/{document['id']}", headers=headers).status_code
        == 404
    )
    assert not objects.objects

    # `C3` deliverable 5: the delete is also a durable audit row. A raw
    # connection, not `SqlAuditRepository` against the shared `db` fixture —
    # `TestClient` above already drove that engine through its own event
    # loop, and a second `asyncio.run` reusing it collides over loop affinity.
    async def fetch_audit_row() -> asyncpg.Record | None:
        conn = await asyncpg.connect(postgres.owner_dsn)
        try:
            return await conn.fetchrow(
                "SELECT actor_id, action, resource_id, outcome FROM audit_log WHERE org_id = $1",
                seeded.org_a,
            )
        finally:
            await conn.close()

    event = asyncio.run(fetch_audit_row())
    assert event is not None
    assert event["action"] == "document.delete"
    assert event["outcome"] == "allow"
    assert event["resource_id"] == document["id"]
    assert str(event["actor_id"]) == str(seeded.user_a)


# ---------------------------------------------------------------- retrieval


def test_a_document_from_another_org_is_not_retrievable(
    db: Database, objects: InMemoryObjectStore, seeded: Seed
) -> None:
    """RLS, at the retrieval scan rather than at a single-row read."""

    async def scenario() -> list[str]:
        knowledge = build_knowledge(db, objects)
        await knowledge.upload_document(
            org_id=seeded.org_a,
            user_id=seeded.user_a,
            title="org a figures",
            media_type="text/plain",
            data=b"Quarterly revenue for org A was twelve million euros.",
        )
        results = await knowledge.retrieve(
            org_id=seeded.org_b, caller_tags=(), query="quarterly revenue"
        )
        return [r.text for r in results]

    assert asyncio.run(scenario()) == []


def test_acl_pushdown_beats_post_filtering_on_yield(
    db: Database, objects: InMemoryObjectStore, seeded: Seed, postgres: Postgres
) -> None:
    """CodingStandards §9's mandatory case 3, and the regression test C4 names.

    With most of the corpus tagged inaccessible, the predicate *inside* the
    scan returns the accessible top-k. A post-filter — take the database's
    top-k, then drop the inaccessible ones in Python — returns strictly fewer,
    because the inaccessible rows consumed the k budget before the filter ran.
    Asserted as an inequality so an "optimisation" that reintroduces
    post-filtering regresses visibly rather than quietly.
    """
    k = 3

    async def scenario() -> tuple[int, int]:
        knowledge = build_knowledge(db, objects)
        # Ten documents on one topic; the first eight are restricted to a tag
        # the caller does not hold, the last two are public within the org.
        for i in range(10):
            await knowledge.upload_document(
                org_id=seeded.org_a,
                user_id=seeded.user_a,
                title=f"revenue report {i}",
                media_type="text/plain",
                data=f"Quarterly revenue analysis number {i} for the finance team.".encode(),
            )

        conn = await asyncpg.connect(postgres.owner_dsn)
        try:
            restricted = await conn.fetch(
                "SELECT id FROM document WHERE org_id = $1 ORDER BY created_at LIMIT 8",
                seeded.org_a,
            )
            await conn.execute(
                "UPDATE chunk_embedding SET acl_tag_ids = ARRAY[$2::uuid] "
                "WHERE org_id = $1 AND document_id = ANY($3::uuid[])",
                seeded.org_a,
                seeded.finance_tag,
                [r["id"] for r in restricted],
            )
        finally:
            await conn.close()

        retriever = SqlRetriever(db)
        embedder = HashingEmbedder(dim=EMBEDDING_DIM)
        vector = embedder.encode(["quarterly revenue analysis"])[0]

        # Pushdown: the predicate is in the scan, so k accessible rows come back.
        pushed_down = await retriever.vector_search(
            org_id=seeded.org_a, caller_tag_ids=[], query_vector=vector, k=k
        )

        # Post-filtering, the banned approach, reproduced here *only* to
        # measure it: ask for the same k with no predicate, then filter.
        conn = await asyncpg.connect(postgres.app_dsn)
        try:
            await conn.execute("SELECT set_config('app.current_org', $1, false)", str(seeded.org_a))
            unfiltered = await conn.fetch(
                "SELECT ce.acl_tag_ids FROM chunk c "
                "JOIN chunk_embedding ce ON ce.chunk_id = c.id "
                "WHERE c.org_id = $1 AND ce.is_current "
                "ORDER BY ce.embedding <=> $2::halfvec LIMIT $3",
                seeded.org_a,
                "[" + ",".join(str(float(x)) for x in vector) + "]",
                k,
            )
        finally:
            await conn.close()
        post_filtered = [r for r in unfiltered if not r["acl_tag_ids"]]

        return len(pushed_down), len(post_filtered)

    pushdown_yield, post_filter_yield = asyncio.run(scenario())

    assert pushdown_yield > post_filter_yield
    assert pushdown_yield == 2  # both public documents, which is all there are


def test_a_superseded_document_revision_is_excluded_from_the_scan_not_down_ranked(
    db: Database, objects: InMemoryObjectStore, seeded: Seed
) -> None:
    """C6, and the headline claim in the README: obsolete text is often the
    *better* lexical match, so down-ranking is not enough. Asserted by the
    superseded chunk being absent, not by it ranking lower."""

    async def scenario() -> tuple[list[str], list[str]]:
        knowledge = build_knowledge(db, objects)
        old = await knowledge.upload_document(
            org_id=seeded.org_a,
            user_id=seeded.user_a,
            title="Employee Handbook 2024",
            media_type="text/plain",
            data=b"Carry-over of unused discretionary leave is capped at ten working days.",
        )
        new = await knowledge.upload_document(
            org_id=seeded.org_a,
            user_id=seeded.user_a,
            title="Employee Handbook 2026",
            media_type="text/plain",
            data=b"Carry-over of unused discretionary leave is capped at five working days.",
        )

        before = await knowledge.retrieve(
            org_id=seeded.org_a, caller_tags=(), query="carry over unused leave"
        )
        await knowledge.mark_superseded(
            org_id=seeded.org_a,
            old_document_id=DocumentId(old.id),
            new_document_id=DocumentId(new.id),
        )
        after = await knowledge.retrieve(
            org_id=seeded.org_a, caller_tags=(), query="carry over unused leave"
        )
        return [c.text for c in before], [c.text for c in after]

    before, after = asyncio.run(scenario())

    assert any("ten working days" in t for t in before)
    assert not any("ten working days" in t for t in after)
    assert any("five working days" in t for t in after)


# ----------------------------------------------------------------- the RAG flow


def test_a_rag_answer_streams_and_persists_its_citations(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed
) -> None:
    headers = _headers(codec, seeded)
    upload(
        client,
        headers,
        "leave.txt",
        "Carry-over of unused discretionary leave is capped at five working days.",
    )
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "According to the handbook, how much leave can I carry over?"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        raw = b"".join(response.iter_bytes())

    frames = _parse_sse(raw)
    assert [name for name, _ in frames] == ["route", "token", "done"]
    assert frames[0][1] == {
        "flow": "rag",
        "reason": "Asks about documents or cited knowledge.",
    }
    done_message = frames[-1][1]["message"]
    assert done_message["flow"] == "rag"  # type: ignore[index,call-overload]
    assert done_message["router_rationale"] == frames[0][1]["reason"]  # type: ignore[index,call-overload]

    detail = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()
    assert len(detail["citations"]) == 1
    citation = detail["citations"][0]
    assert citation["marker"] == 1
    assert citation["chunk_id"] is not None
    assert "five working days" in citation["quoted_text"]


def test_a_question_with_no_matching_chunks_answers_honestly_rather_than_hallucinating(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, model: ScriptedChatModel
) -> None:
    """Whatever the flow does with an empty retrieval must be *visible in the
    prompt* — otherwise a RAG answer with no sources is indistinguishable from
    a plain-chat answer that made one up."""
    headers = _headers(codec, seeded)
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "What is our leave policy?"},
        headers=headers,
    ) as response:
        assert response.status_code == 200
        b"".join(response.iter_bytes())

    system_turns = [t.content for t in model.turns_seen[-1] if t.role.value == "system"]
    assert any("No relevant documents were found" in t for t in system_turns)

    # And nothing was cited, because there was nothing to cite.
    detail = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()
    assert detail["citations"] == []


def test_a_plain_chat_message_does_not_go_through_retrieval(
    client: TestClient, codec: PlatformTokenCodec, seeded: Seed, model: ScriptedChatModel
) -> None:
    """The classifier's conservative default. A RAG flow that ran on every
    message would pass every retrieval test above and quietly change what
    plain chat does."""
    headers = _headers(codec, seeded)
    upload(client, headers, "leave.txt", "Carry-over is capped at five working days.")
    session_id = client.post("/api/v1/chat/sessions", json={}, headers=headers).json()["id"]

    with client.stream(
        "POST",
        f"/api/v1/chat/sessions/{session_id}/messages",
        json={"content": "Hello there"},
        headers=headers,
    ) as response:
        b"".join(response.iter_bytes())

    system_turns = [t.content for t in model.turns_seen[-1] if t.role.value == "system"]
    assert not any("source passages" in t for t in system_turns)

    detail = client.get(f"/api/v1/chat/sessions/{session_id}", headers=headers).json()
    assistant = [m for m in detail["messages"] if m["role"] == "assistant"]
    assert assistant[0]["flow"] == "chat"

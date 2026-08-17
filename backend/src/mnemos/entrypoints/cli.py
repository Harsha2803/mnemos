"""`mnemosctl` — operational commands.

`db doctor` is the one that earns its place: it prints what the database
actually looks like right now — extensions, tables and row counts, which tables
have FORCE row-level security, the bitemporal exclusion constraint, and the
partition set. Reading it beats trusting a migration log, because it reports the
schema rather than the intent.

`bootstrap` creates the first org, its administrator, the system roles and the
two `identity_provider` rows. It is a CLI and not a screen on purpose: it is the
command that runs *before* anybody can sign in, so an authenticated UI for it
would be a UI nobody can reach. **This is the M3.7 UI slice, and it is
deliberately none** — see TRACKER §5 and constraint C12.

This module stays thin. The decisions — what the system roles grant, how much of
the work runs elevated, what a second run does — live in
`features/identity/application/bootstrap.py`; everything here is argument
parsing and printing.
"""

from __future__ import annotations

import argparse
import asyncio
import getpass
import os
import sys

import httpx
from sqlalchemy import select, text

# Every model module, imported for its side effect on `Base.metadata` before
# any ORM operation runs — the same reason `entrypoints/api/main.py` imports
# this (see its own comment). `datasource generate` is the first CLI command
# to write a row with a foreign key crossing a feature boundary
# (`sql_run.message_id -> chat_message.id`), and nothing about importing
# `datasources`' own adapter module implies that `chat`'s will also have run.
import mnemos.platform.models  # noqa: F401
from mnemos.core.config import Settings, get_settings
from mnemos.core.crypto import DsnCipher
from mnemos.core.errors import MnemosError, NotFoundError, ValidationError
from mnemos.core.ids import DEFAULT_ID_GENERATOR
from mnemos.core.security import PasswordHasher
from mnemos.features.connectors.adapters.crypto import SourceConfigCipher
from mnemos.features.connectors.adapters.repository import ContentSourceRepository
from mnemos.features.connectors.application.factory import ConnectorFactory
from mnemos.features.connectors.application.service import ConnectorService
from mnemos.features.datasources.adapters.executor import PostgresExecutor
from mnemos.features.datasources.adapters.introspection import PostgresIntrospector
from mnemos.features.datasources.adapters.repository import (
    DatasourceRepository,
    GlossaryRepository,
    SchemaObjectRepository,
    SqlRunRepository,
)
from mnemos.features.datasources.application.generation import SqlGenerationService
from mnemos.features.datasources.application.service import DatasourceService
from mnemos.features.datasources.domain import DEFAULT_DATASOURCE_SLUG, GlossaryTermRow
from mnemos.features.identity.adapters.bootstrap_store import SqlBootstrapStore
from mnemos.features.identity.adapters.models import Org
from mnemos.features.identity.application.bootstrap import (
    INTERNAL_PROVIDER_SLUG,
    OIDC_PROVIDER_SLUG,
    Bootstrap,
    BootstrapReport,
    BootstrapRequest,
    OidcSettings,
)
from mnemos.features.identity.domain import OrgId
from mnemos.features.knowledge.adapters.jobs_repository import IngestJobRepository
from mnemos.features.knowledge.domain import CONNECTOR_INGEST_KIND
from mnemos.features.llm.adapters.ollama import OllamaChatModel
from mnemos.platform.db import Database

#: The one warehouse this build ships. A datasource registry UI is out of
#: scope for `A3` (TRACKER §5) — registration is this CLI command, same shape
#: as `bootstrap` creating the one org an operator needs to get started.
#: Shared with `entrypoints/api/main.py`'s `Nl2SqlFlow` via `features.
#: datasources.domain.DEFAULT_DATASOURCE_SLUG` — one definition, not two
#: string literals that can drift.
DEMO_DATASOURCE_SLUG = DEFAULT_DATASOURCE_SLUG
DEMO_DATASOURCE_NAME = "Sales Warehouse (demo)"
DEMO_DATASOURCE_DESCRIPTION = (
    "The seeded analytics.* schema (deploy/postgres/init/02-analytics-seed.sql): "
    "region, product, customer, sales_order."
)
DEMO_DATASOURCE_SCHEMAS = ["analytics"]

#: The demo warehouse's business vocabulary (TRACKER §5 deliverable 2). Curated
#: by hand, the way a real deployment's glossary would be — these are facts
#: about what "revenue" means *here*, not something introspection could ever
#: infer from `information_schema`.
DEMO_GLOSSARY_TERMS = [
    GlossaryTermRow(
        term="revenue",
        definition="The net amount collected across completed sales orders.",
        sql_expression="SUM(analytics.sales_order.net_amount) WHERE status = 'completed'",
        synonyms=["sales", "total sales", "income"],
    ),
    GlossaryTermRow(
        term="active customer",
        definition="A customer with at least one sales order placed in the last 90 days.",
        sql_expression=(
            "EXISTS (SELECT 1 FROM analytics.sales_order so WHERE so.customer_id = "
            "analytics.customer.customer_id AND so.ordered_on >= CURRENT_DATE - INTERVAL '90 days')"
        ),
        synonyms=["engaged customer"],
    ),
    GlossaryTermRow(
        term="order volume",
        definition="The count of sales orders placed, regardless of status.",
        sql_expression="COUNT(*) FROM analytics.sales_order",
        synonyms=["order count", "number of orders"],
    ),
    GlossaryTermRow(
        term="segment",
        definition="A customer's commercial tier: enterprise, mid-market, or smb.",
        sql_expression="analytics.customer.segment",
        synonyms=["customer tier", "tier"],
    ),
]

#: Where the admin password may be read from. It is an environment variable or an
#: interactive prompt and **never a command-line argument**: `argv` is readable by
#: any process on the machine through `/proc/<pid>/cmdline`, it is written
#: verbatim into shell history, and it shows up in `ps` for the lifetime of the
#: command. An environment variable is not perfect either — it is inherited by
#: children and visible in `/proc/<pid>/environ` to the same user — but it is not
#: world-readable and it does not persist in a history file.
ADMIN_PASSWORD_ENV = "MNEMOS_BOOTSTRAP_ADMIN_PASSWORD"

EXTENSIONS_SQL = "SELECT extname FROM pg_extension ORDER BY extname"

TABLES_SQL = """
SELECT c.relname AS table_name,
       c.relrowsecurity AS rls_enabled,
       c.relforcerowsecurity AS rls_forced,
       COALESCE(s.n_live_tup, 0) AS row_estimate
  FROM pg_class c
  JOIN pg_namespace n ON n.oid = c.relnamespace
  LEFT JOIN pg_stat_user_tables s ON s.relid = c.oid
 WHERE n.nspname = 'public'
   AND c.relkind IN ('r', 'p')
   AND c.relname <> 'alembic_version'
   AND c.relispartition = false
 ORDER BY c.relname
"""

CONSTRAINTS_SQL = """
SELECT conname, pg_get_constraintdef(oid) AS definition
  FROM pg_constraint
 WHERE contype = 'x'
 ORDER BY conname
"""

PARTITIONS_SQL = """
SELECT count(*) AS n FROM pg_class c
  JOIN pg_inherits i ON i.inhrelid = c.oid
  JOIN pg_class p ON p.oid = i.inhparent
 WHERE p.relname = 'inference_call'
"""

VERSION_SQL = "SELECT version_num FROM alembic_version"


async def _doctor() -> int:
    db = Database(get_settings())
    try:
        async with db.session() as session:
            version = (await session.execute(text(VERSION_SQL))).scalar_one_or_none()
            extensions = [r[0] for r in (await session.execute(text(EXTENSIONS_SQL))).all()]
            tables = (await session.execute(text(TABLES_SQL))).all()
            exclusions = (await session.execute(text(CONSTRAINTS_SQL))).all()
            partitions = (await session.execute(text(PARTITIONS_SQL))).scalar_one()
    finally:
        await db.dispose()

    print(f"alembic revision : {version or '(none applied)'}")
    print(f"extensions       : {' '.join(extensions)}")
    print(f"partitions       : {partitions} on inference_call")
    print()

    forced = sum(1 for t in tables if t.rls_forced)
    print(f"{len(tables)} tables, {forced} with FORCE row-level security\n")
    print(f"  {'table':<24} {'rows':>8}  rls")
    print(f"  {'-' * 24} {'-' * 8}  {'-' * 9}")
    for t in tables:
        if t.rls_forced:
            rls = "FORCE"
        elif t.rls_enabled:
            rls = "enabled"
        else:
            rls = "-"
        print(f"  {t.table_name:<24} {t.row_estimate:>8}  {rls}")

    if exclusions:
        print("\nexclusion constraints")
        for c in exclusions:
            print(f"  {c.conname}\n    {c.definition}")

    return 0


def _read_admin_password() -> str:
    """Take the admin password from the environment, or prompt for it.

    See :data:`ADMIN_PASSWORD_ENV` for why it is never an argument. The prompt
    asks twice because there is no "change password" screen yet: a typo in a
    password nobody can see produces an org whose only administrator cannot log
    in, and the only fix is a hand-written `UPDATE`.
    """
    from_env = os.environ.get(ADMIN_PASSWORD_ENV)
    if from_env:
        return from_env

    if not sys.stdin.isatty():
        raise ValidationError(
            f"no admin password: set {ADMIN_PASSWORD_ENV} or run this on a terminal",
            field="admin_password",
        )

    # `getpass` reads from /dev/tty with echo off, so the password does not
    # appear on screen and is not captured by a shell redirect of stdin.
    first = getpass.getpass("admin password        : ")
    second = getpass.getpass("admin password (again): ")
    if first != second:
        raise ValidationError("the two passwords did not match", field="admin_password")
    return first


def _build_request(args: argparse.Namespace, settings: Settings, password: str) -> BootstrapRequest:
    """Turn parsed arguments into the use case's input.

    The OIDC columns default from `Settings` rather than from literals here, so a
    seeded `identity_provider` row matches the Keycloak the same process would
    talk to. Passing them explicitly is still supported, because the CLI is
    usually run from the host while the API runs inside the compose network and
    the two disagree about `issuer_internal` — that disagreement is split horizon
    and it is the whole reason the column exists.
    """
    default_provider = args.default_provider
    if default_provider is None:
        default_provider = OIDC_PROVIDER_SLUG if settings.oidc_enabled else INTERNAL_PROVIDER_SLUG

    return BootstrapRequest(
        org_slug=args.org_slug.strip(),
        org_name=args.org_name.strip(),
        admin_email=args.admin_email.strip(),
        # The local part of the address is a better default than the address
        # itself: `display_name` is what a UI renders next to a message.
        admin_display_name=(args.admin_name or args.admin_email.split("@")[0]).strip(),
        admin_password=password,
        oidc=OidcSettings(
            issuer_public=args.oidc_issuer_public or settings.oidc_issuer_public,
            issuer_internal=args.oidc_issuer_internal or settings.oidc_issuer_internal,
            client_id=args.oidc_client_id or settings.oidc_client_id,
            is_enabled=settings.oidc_enabled,
        ),
        default_provider_slug=default_provider,
    )


def _print_report(report: BootstrapReport) -> None:
    """Print what the run did, in `db doctor`'s shape.

    Never the password and never the hash — the operator supplied the one and
    has no use for the other, and a terminal is a place output gets pasted from.
    """
    status = "created" if report.org_created else "already present"
    print(f"org              : {report.org_slug}  ({report.org_name}) — {status}")
    print(f"org id           : {report.org_id}")
    print(
        f"admin            : {report.admin_email} — "
        f"{'created' if report.admin_created else 'already present'}"
    )
    print(
        f"admin role       : {report.admin_role_slug} — "
        f"{'bound' if report.role_binding_created else 'already bound'}"
    )
    print()

    print(f"  {'role':<12} {'grants':<12} status")
    print(f"  {'-' * 12} {'-' * 12} {'-' * 15}")
    for row in report.roles:
        print(
            f"  {row.label:<12} {row.detail:<12} {'created' if row.created else 'already present'}"
        )

    print()
    print(f"  {'provider':<12} {'kind':<12} status")
    print(f"  {'-' * 12} {'-' * 12} {'-' * 15}")
    for row in report.providers:
        print(
            f"  {row.label:<12} {row.detail:<12} {'created' if row.created else 'already present'}"
        )

    print()
    default_status = "set" if report.default_provider_set else "already set"
    print(f"default provider : {report.default_provider_slug} — {default_status}")
    print()
    print(f"sign in with     : org {report.org_slug!r}, email {report.admin_email!r}")
    print(f"browser login    : /api/v1/auth/oidc/authorize?org={report.org_slug}")


async def _bootstrap(args: argparse.Namespace, password: str) -> int:
    settings = get_settings()
    request = _build_request(args, settings, password)

    db = Database(settings)
    try:
        report = await Bootstrap(store=SqlBootstrapStore(db), hasher=PasswordHasher()).execute(
            request
        )
    finally:
        await db.dispose()

    _print_report(report)
    return 0


async def _resolve_org_id(db: Database, org_slug: str) -> OrgId:
    """`org` carries no RLS policy (migration 0004's own docstring explains
    why), so this is a plain lookup — no GUC to set, nothing to scope."""
    async with db.session() as session:
        org = await session.scalar(select(Org).where(Org.slug == org_slug))
    if org is None:
        raise NotFoundError(f"no org with slug {org_slug!r}")
    return OrgId(org.id)


def _datasource_service(db: Database, settings: Settings) -> DatasourceService:
    return DatasourceService(
        datasources=DatasourceRepository(db, DEFAULT_ID_GENERATOR),
        schema_objects=SchemaObjectRepository(db, DEFAULT_ID_GENERATOR),
        introspector=PostgresIntrospector(),
        cipher=DsnCipher(settings.dsn_encryption_key.get_secret_value()),
        glossary=GlossaryRepository(db, DEFAULT_ID_GENERATOR),
        executor=PostgresExecutor(),
    )


async def _datasource_introspect(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        service = _datasource_service(db, settings)
        datasource = await service.register(
            org_id=org_id,
            slug=args.slug,
            name=DEMO_DATASOURCE_NAME,
            description=DEMO_DATASOURCE_DESCRIPTION,
            dsn=settings.analytics_database_url,
            read_only_role="mnemos_ro",
            allowed_schemas=DEMO_DATASOURCE_SCHEMAS,
        )
        rows_written = await service.refresh_schema(org_id=org_id, slug=args.slug)
    finally:
        await db.dispose()

    print(f"datasource       : {datasource.slug}  ({datasource.name})")
    print(f"allowed schemas  : {', '.join(datasource.allowed_schemas)}")
    print(f"schema objects   : {rows_written} rows cached in sql_schema_object")
    return 0


async def _datasource_seed_glossary(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        service = _datasource_service(db, settings)
        written = await service.seed_glossary(
            org_id=org_id, slug=args.slug, terms=DEMO_GLOSSARY_TERMS
        )
    finally:
        await db.dispose()

    print(f"glossary terms   : {written} newly written, {len(DEMO_GLOSSARY_TERMS)} total seeded")
    return 0


async def _datasource_show_context(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        service = _datasource_service(db, settings)
        context = await service.render_context(org_id=org_id, slug=args.slug)
    finally:
        await db.dispose()

    print(context if context else "(no cached schema or glossary yet)")
    return 0


async def _datasource_generate(args: argparse.Namespace) -> int:
    """Generate, guard and record one attempt. Never executes the statement —
    that is deliverable 4. This is deliverable 3's real, demonstrable
    consumer of `guard_sql`/`SqlGenerationService`, the same reasoning
    `show-context` was for `render_schema_context` in deliverable 2."""
    settings = get_settings()
    db = Database(settings)
    # A separate client from the one the API process reuses per-request
    # (`entrypoints/api/main.py`'s `app.state.ollama_http`) — this is a
    # one-shot CLI invocation, not a long-lived server, so it opens and
    # closes its own.
    http_client = httpx.AsyncClient()
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        model = OllamaChatModel(
            client=http_client,
            base_url=settings.ollama_base_url,
            model=settings.ollama_model,
            timeout_s=float(settings.ollama_timeout_s),
        )
        generation = SqlGenerationService(
            datasources=_datasource_service(db, settings),
            model=model,
            sql_runs=SqlRunRepository(db, DEFAULT_ID_GENERATOR),
        )
        run = await generation.generate(org_id=org_id, slug=args.slug, question=args.question)
    finally:
        await http_client.aclose()
        await db.dispose()

    print(f"datasource       : {args.slug}")
    print(f"question         : {run.question}")
    print(f"verdict          : {run.verdict.value}")
    if run.verdict_detail:
        print(f"detail           : {run.verdict_detail}")
    print("sql              :")
    for line in run.generated_sql.splitlines() or [""]:
        print(f"  {line}")
    if run.authorized_tables:
        print(f"tables read      : {', '.join(run.authorized_tables)}")
    if run.denied_tables:
        print(f"tables refused   : {', '.join(run.denied_tables)}")
    return 0


def _connector_service(
    db: Database, settings: Settings, http_client: httpx.AsyncClient
) -> ConnectorService:
    cipher = SourceConfigCipher(settings.source_encryption_key.get_secret_value())
    return ConnectorService(
        repository=ContentSourceRepository(db, DEFAULT_ID_GENERATOR),
        cipher=cipher,
        factory=ConnectorFactory(settings=settings, cipher=cipher, http_client=http_client),
        local_fs_allowed_roots=settings.local_fs_allowed_roots,
    )


def _connector_config(args: argparse.Namespace) -> dict[str, object]:
    if args.kind in ("s3", "minio"):
        if not args.bucket:
            raise ValidationError("--bucket is required for an s3 connector", field="bucket")
        return {"bucket": args.bucket, "prefix": args.prefix or ""}
    if args.kind == "local_fs":
        if not args.root:
            raise ValidationError("--root is required for a local_fs connector", field="root")
        return {"root": args.root}
    if args.kind == "http":
        if not args.url:
            raise ValidationError(
                "--url (repeatable) is required for an http connector", field="url"
            )
        return {"urls": args.url}
    raise ValidationError(f"unknown connector kind {args.kind!r}", field="kind")


async def _connector_register(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    http_client = httpx.AsyncClient()
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        service = _connector_service(db, settings, http_client)
        config = _connector_config(args)
        source = await service.register(
            org_id=org_id, slug=args.slug, name=args.name, kind=args.kind, config=config
        )
    finally:
        await http_client.aclose()
        await db.dispose()

    print(f"content source   : {source.slug}  ({source.name})")
    print(f"kind             : {source.kind}")
    print(f"id               : {source.id}")
    return 0


async def _connector_list_items(args: argparse.Namespace) -> int:
    settings = get_settings()
    db = Database(settings)
    http_client = httpx.AsyncClient()
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        service = _connector_service(db, settings, http_client)
        items = await service.list_items(org_id=org_id, slug=args.slug)
    finally:
        await http_client.aclose()
        await db.dispose()

    print(f"content source   : {args.slug}  ({len(items)} items)")
    for item in items:
        size = f"{item.size_bytes:>10} bytes" if item.size_bytes else f"{'?':>10}      "
        print(f"  {item.uri:<50} {size}  {item.content_type}")
    return 0


async def _connector_ingest(args: argparse.Namespace) -> int:
    """Enqueue a `queued` `ingest_job` for one browsed item — `B1` deliverable
    4's real, demonstrable producer, the same "operator/inspection tool, not
    a product screen" shape `datasource generate` was for deliverable 3.
    `entrypoints/worker/main.py` is the consumer; nothing else creates a job
    yet (deliverable 5's sources UI is the future second producer)."""
    settings = get_settings()
    db = Database(settings)
    http_client = httpx.AsyncClient()
    try:
        org_id = await _resolve_org_id(db, args.org_slug)
        service = _connector_service(db, settings, http_client)
        items = await service.list_items(org_id=org_id, slug=args.slug)
        match = next((i for i in items if i.uri == args.uri), None)
        if match is None:
            raise NotFoundError(f"{args.uri!r} is not a currently listed item of {args.slug!r}")

        jobs = IngestJobRepository(db, DEFAULT_ID_GENERATOR)
        job_id = await jobs.enqueue(
            org_id=org_id,
            kind=CONNECTOR_INGEST_KIND,
            payload={
                "source_slug": args.slug,
                "item_uri": match.uri,
                "item_name": match.name,
                "content_type": match.content_type,
            },
            idempotency_key=f"{args.slug}:{match.uri}",
        )
    finally:
        await http_client.aclose()
        await db.dispose()

    print(f"ingest job       : {job_id}")
    print("status           : queued")
    print(f"item             : {match.uri}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(prog="mnemosctl", description="Mnemos operations")
    sub = parser.add_subparsers(dest="group", required=True)

    db_parser = sub.add_parser("db", help="database operations")
    db_sub = db_parser.add_subparsers(dest="command", required=True)
    db_sub.add_parser("doctor", help="report the live schema: tables, RLS, constraints")

    boot = sub.add_parser(
        "bootstrap",
        help="create the first org, its admin, the system roles and the provider rows",
        description=(
            "Idempotent: a second run creates whatever is missing and changes nothing "
            f"that exists. The admin password comes from ${ADMIN_PASSWORD_ENV} or an "
            "interactive prompt, never from an argument."
        ),
    )
    boot.add_argument("--org-slug", required=True, help="URL-safe org identifier, e.g. 'acme'")
    boot.add_argument("--org-name", required=True, help="Human-readable org name")
    boot.add_argument("--admin-email", required=True, help="Administrator's email address")
    boot.add_argument("--admin-name", default=None, help="Display name; defaults to the local part")
    boot.add_argument(
        "--default-provider",
        default=None,
        choices=[INTERNAL_PROVIDER_SLUG, OIDC_PROVIDER_SLUG],
        help="org.settings.default_provider; defaults to OIDC when OIDC is enabled",
    )
    boot.add_argument("--oidc-issuer-public", default=None, help="Issuer the browser is sent to")
    boot.add_argument("--oidc-issuer-internal", default=None, help="Issuer the API validates over")
    boot.add_argument("--oidc-client-id", default=None, help="OIDC client id, e.g. 'mnemos-web'")

    ds_parser = sub.add_parser(
        "datasource", help="NL2SQL warehouse registration, introspection, and glossary"
    )
    ds_sub = ds_parser.add_subparsers(dest="command", required=True)
    introspect = ds_sub.add_parser(
        "introspect",
        help="register the demo warehouse (idempotent) and refresh its cached schema",
        description=(
            "Registers the seeded analytics.* warehouse for one org if it is not already "
            "registered, then reads information_schema through the mnemos_ro role and "
            "replaces the org's cached sql_schema_object rows. Explicit and on-demand — "
            "never run implicitly on the query path."
        ),
    )
    introspect.add_argument(
        "--org-slug", required=True, help="Org to register the datasource under"
    )
    introspect.add_argument(
        "--slug",
        default=DEMO_DATASOURCE_SLUG,
        help=f"Datasource slug (default: {DEMO_DATASOURCE_SLUG})",
    )

    seed_glossary = ds_sub.add_parser(
        "seed-glossary",
        help="seed the demo warehouse's business glossary (idempotent)",
        description=(
            "Writes the curated glossary terms in entrypoints/cli.py's "
            "DEMO_GLOSSARY_TERMS for one org's datasource. A term already present, "
            "matched by its term text, is left untouched — re-running never overwrites "
            "an edit made since. Requires the datasource to already be registered "
            "('datasource introspect' first)."
        ),
    )
    seed_glossary.add_argument(
        "--org-slug", required=True, help="Org whose datasource gets the glossary"
    )
    seed_glossary.add_argument(
        "--slug",
        default=DEMO_DATASOURCE_SLUG,
        help=f"Datasource slug (default: {DEMO_DATASOURCE_SLUG})",
    )

    show_context = ds_sub.add_parser(
        "show-context",
        help="print the schema + glossary text block the NL2SQL prompt will use",
        description=(
            "Renders the datasource's cached sql_schema_object rows and glossary_term "
            "rows into the same text block deliverable 3's prompt assembles from — a "
            "read-only view for inspecting what the model will see, useful once "
            "'introspect' and 'seed-glossary' have both been run."
        ),
    )
    show_context.add_argument("--org-slug", required=True, help="Org whose datasource to render")
    show_context.add_argument(
        "--slug",
        default=DEMO_DATASOURCE_SLUG,
        help=f"Datasource slug (default: {DEMO_DATASOURCE_SLUG})",
    )

    generate = ds_sub.add_parser(
        "generate",
        help="generate SQL for a question, guard it, and record the attempt (never executes)",
        description=(
            "Renders the datasource's schema and glossary (the same block 'show-context' "
            "prints), asks the configured Ollama model for one read-only SELECT, parses it "
            "with sqlglot and rejects anything that is not a single read wherever it "
            "appears in the statement, and writes a sql_run row with the verdict either "
            "way. Never executes the statement — that is deliverable 4."
        ),
    )
    generate.add_argument("--org-slug", required=True, help="Org whose datasource to query")
    generate.add_argument(
        "--slug",
        default=DEMO_DATASOURCE_SLUG,
        help=f"Datasource slug (default: {DEMO_DATASOURCE_SLUG})",
    )
    generate.add_argument("question", help="The question to translate into SQL")

    conn_parser = sub.add_parser("connector", help="register and browse content sources (B1)")
    conn_sub = conn_parser.add_subparsers(dest="command", required=True)

    conn_register = conn_sub.add_parser(
        "register",
        help="register a content source (idempotent per slug)",
        description=(
            "Registers a SourceConnector — an S3/MinIO bucket+prefix, a local-filesystem "
            "root, or a curated list of HTTP URLs — for one org. Config is validated "
            "(non-empty bucket/root/urls, an operator-approved root for local_fs, the SSRF "
            "deny-list for every http URL) and stored encrypted."
        ),
    )
    conn_register.add_argument("--org-slug", required=True, help="Org to register the source under")
    conn_register.add_argument("--slug", required=True, help="URL-safe source identifier")
    conn_register.add_argument("--name", required=True, help="Human-readable source name")
    conn_register.add_argument("--kind", required=True, choices=["s3", "minio", "local_fs", "http"])
    conn_register.add_argument("--bucket", default=None, help="s3/minio: bucket name")
    conn_register.add_argument("--prefix", default="", help="s3/minio: key prefix (default: '')")
    conn_register.add_argument("--root", default=None, help="local_fs: allowlisted root directory")
    conn_register.add_argument(
        "--url", action="append", default=None, help="http: a URL to allow (repeatable)"
    )

    conn_list_items = conn_sub.add_parser(
        "list-items", help="browse what a registered source currently contains"
    )
    conn_list_items.add_argument("--org-slug", required=True, help="Org that owns the source")
    conn_list_items.add_argument("--slug", required=True, help="Source slug")

    conn_ingest = conn_sub.add_parser(
        "ingest",
        help="enqueue a queued ingest_job for one item currently listed by the source",
        description=(
            "Enqueues one ingest_job for a worker to claim (entrypoints/worker/main.py). "
            "The item must be one `list-items` currently returns for this source."
        ),
    )
    conn_ingest.add_argument("--org-slug", required=True, help="Org that owns the source")
    conn_ingest.add_argument("--slug", required=True, help="Source slug")
    conn_ingest.add_argument("--uri", required=True, help="Item uri, as shown by list-items")

    args = parser.parse_args()

    if args.group == "bootstrap":
        try:
            # Read before the event loop starts: `getpass` blocks on a terminal,
            # and blocking inside an async entrypoint is the habit this codebase
            # is most careful about (CodingStandards §3).
            password = _read_admin_password()
            return asyncio.run(_bootstrap(args, password))
        except MnemosError as exc:
            # The reason goes to stderr rather than the log's JSON, because the
            # audience of a CLI is the person who just typed it.
            print(f"bootstrap failed: {exc.message}", file=sys.stderr)
            return 2

    if args.group == "db" and args.command == "doctor":
        return asyncio.run(_doctor())

    if args.group == "datasource" and args.command == "introspect":
        try:
            return asyncio.run(_datasource_introspect(args))
        except MnemosError as exc:
            print(f"datasource introspect failed: {exc.message}", file=sys.stderr)
            return 2

    if args.group == "datasource" and args.command == "seed-glossary":
        try:
            return asyncio.run(_datasource_seed_glossary(args))
        except (MnemosError, LookupError) as exc:
            print(f"datasource seed-glossary failed: {exc}", file=sys.stderr)
            return 2

    if args.group == "datasource" and args.command == "show-context":
        try:
            return asyncio.run(_datasource_show_context(args))
        except (MnemosError, LookupError) as exc:
            print(f"datasource show-context failed: {exc}", file=sys.stderr)
            return 2

    if args.group == "datasource" and args.command == "generate":
        try:
            return asyncio.run(_datasource_generate(args))
        except (MnemosError, LookupError) as exc:
            print(f"datasource generate failed: {exc}", file=sys.stderr)
            return 2

    if args.group == "connector" and args.command == "register":
        try:
            return asyncio.run(_connector_register(args))
        except (MnemosError, ValueError) as exc:
            message = exc.message if isinstance(exc, MnemosError) else str(exc)
            print(f"connector register failed: {message}", file=sys.stderr)
            return 2

    if args.group == "connector" and args.command == "list-items":
        try:
            return asyncio.run(_connector_list_items(args))
        except (MnemosError, LookupError) as exc:
            message = exc.message if isinstance(exc, MnemosError) else str(exc)
            print(f"connector list-items failed: {message}", file=sys.stderr)
            return 2

    if args.group == "connector" and args.command == "ingest":
        try:
            return asyncio.run(_connector_ingest(args))
        except (MnemosError, LookupError) as exc:
            message = exc.message if isinstance(exc, MnemosError) else str(exc)
            print(f"connector ingest failed: {message}", file=sys.stderr)
            return 2

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

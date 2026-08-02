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

from sqlalchemy import text

from mnemos.core.config import Settings, get_settings
from mnemos.core.errors import MnemosError, ValidationError
from mnemos.core.security import PasswordHasher
from mnemos.features.identity.adapters.bootstrap_store import SqlBootstrapStore
from mnemos.features.identity.application.bootstrap import (
    INTERNAL_PROVIDER_SLUG,
    OIDC_PROVIDER_SLUG,
    Bootstrap,
    BootstrapReport,
    BootstrapRequest,
    OidcSettings,
)
from mnemos.platform.db import Database

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

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

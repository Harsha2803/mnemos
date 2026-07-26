"""`mnemosctl` — operational commands.

`db doctor` is the one that earns its place: it prints what the database
actually looks like right now — extensions, tables and row counts, which tables
have FORCE row-level security, the bitemporal exclusion constraint, and the
partition set. Reading it beats trusting a migration log, because it reports the
schema rather than the intent.
"""

from __future__ import annotations

import argparse
import asyncio
import sys

from sqlalchemy import text

from mnemos.core.config import get_settings
from mnemos.platform.db import Database

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


def main() -> int:
    parser = argparse.ArgumentParser(prog="mnemosctl", description="Mnemos operations")
    sub = parser.add_subparsers(dest="group", required=True)

    db_parser = sub.add_parser("db", help="database operations")
    db_sub = db_parser.add_subparsers(dest="command", required=True)
    db_sub.add_parser("doctor", help="report the live schema: tables, RLS, constraints")

    args = parser.parse_args()
    if args.group == "db" and args.command == "doctor":
        return asyncio.run(_doctor())

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())

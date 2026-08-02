"""an unprivileged application role, so row-level security actually applies

Migration `0004` put `FORCE ROW LEVEL SECURITY` and an org-isolation policy on 40
tables. That was necessary and not sufficient: **RLS never applies to a superuser
or to any role holding `BYPASSRLS`**, and the application was connecting as
`mnemos`, which the Postgres image creates as a superuser. Every policy was
present in the catalogue and inert in the running system.

Observed before this revision, as the owning role, with `app.current_org` set to
org A and two orgs' rows present::

    SELECT count(*) FROM tag;   -- 2, both orgs

The fix is a role split, because the two jobs need opposite privileges:

* ``mnemos`` — owner and superuser. Runs Alembic. Must be able to create,
  alter and drop; RLS must not obstruct it.
* ``mnemos_app`` — ``LOGIN NOSUPERUSER NOBYPASSRLS``. Runs the API, the worker
  and the realtime gateway. Holds DML and nothing else, so the policies bind.
* ``mnemos_admin`` — ``NOLOGIN BYPASSRLS``, created in `0004`. Granted *to*
  ``mnemos_app`` here so `mnemosctl bootstrap` can ``SET LOCAL ROLE`` for the one
  transaction that has no org to scope to yet.

**Role attributes are not inherited through membership.** `mnemos_app` inherits
`mnemos_admin`'s table privileges, but `BYPASSRLS` is an attribute of the role
being acted as, not a privilege — so it takes an explicit `SET ROLE` to escape
tenant isolation. The escape hatch exists, it is auditable, and it is never
entered by accident.

`ALTER DEFAULT PRIVILEGES` is set for the owning role so tables created by later
revisions are granted automatically. Without it, every future migration would
have to remember a `GRANT`, and the one that forgot would fail at runtime as a
permission error in whichever feature happened to touch the new table first.

Revision ID: 0005
Revises: 0004
Created: 2026-07-27
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

from mnemos.core.config import get_settings

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DML = "SELECT, INSERT, UPDATE, DELETE"


def upgrade() -> None:
    settings = get_settings()
    app_role = settings.app_database_role
    admin_role = settings.admin_database_role
    app_password = settings.app_database_password.get_secret_value()

    # Identifiers and the literal are interpolated by `format()` inside the
    # server, not by Python string building, so a role name or password
    # containing a quote cannot terminate the statement.
    op.execute(
        f"""
        DO $$
        DECLARE
            app_role   text := {_lit(app_role)};
            admin_role text := {_lit(admin_role)};
            app_pw     text := {_lit(app_password)};
            owner_role text := current_user;
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = app_role) THEN
                EXECUTE format(
                    'CREATE ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS NOCREATEDB '
                    'NOCREATEROLE INHERIT PASSWORD %L', app_role, app_pw);
            ELSE
                -- Idempotent: re-running must converge on the intended attributes
                -- rather than fail, because a re-created database volume and an
                -- existing cluster both have to end up here.
                EXECUTE format(
                    'ALTER ROLE %I LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD %L',
                    app_role, app_pw);
            END IF;

            EXECUTE format('GRANT USAGE ON SCHEMA public TO %I, %I',
                           app_role, admin_role);
            EXECUTE format('GRANT {DML} ON ALL TABLES IN SCHEMA public TO %I, %I',
                           app_role, admin_role);
            EXECUTE format('GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public '
                           'TO %I, %I', app_role, admin_role);

            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                           'GRANT {DML} ON TABLES TO %I, %I',
                           owner_role, app_role, admin_role);
            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                           'GRANT USAGE, SELECT ON SEQUENCES TO %I, %I',
                           owner_role, app_role, admin_role);

            -- Membership, not attribute inheritance. See the module docstring.
            EXECUTE format('GRANT %I TO %I', admin_role, app_role);
        END $$;
        """
    )


def downgrade() -> None:
    settings = get_settings()
    app_role = settings.app_database_role
    admin_role = settings.admin_database_role

    op.execute(
        f"""
        DO $$
        DECLARE
            app_role   text := {_lit(app_role)};
            admin_role text := {_lit(admin_role)};
            owner_role text := current_user;
        BEGIN
            IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = app_role) THEN
                RETURN;
            END IF;

            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                           'REVOKE {DML} ON TABLES FROM %I, %I',
                           owner_role, app_role, admin_role);
            EXECUTE format('ALTER DEFAULT PRIVILEGES FOR ROLE %I IN SCHEMA public '
                           'REVOKE USAGE, SELECT ON SEQUENCES FROM %I, %I',
                           owner_role, app_role, admin_role);
            EXECUTE format('REVOKE %I FROM %I', admin_role, app_role);

            -- Privileges held by a role are dependencies of it; DROP ROLE fails
            -- while any remain, and DROP OWNED is the only thing that clears
            -- them all without enumerating every object.
            EXECUTE format('DROP OWNED BY %I', app_role);
            EXECUTE format('DROP ROLE %I', app_role);
        END $$;
        """
    )


def _lit(value: str) -> str:
    """Render a Python string as a SQL literal for embedding in a DO block."""
    escaped = value.replace("'", "''")
    return f"'{escaped}'"

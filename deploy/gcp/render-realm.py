#!/usr/bin/env python3
"""Render the production Keycloak realm from the committed development realm.

Deriving it, rather than keeping a second hand-written copy, means the two can
never drift: the roles, the client, its protocol mappers and — load-bearing —
the pinned user `id`s (TRACKER D1 bug 1) all come from deploy/keycloak. Only
what must differ in public is changed: TLS required for external clients, the
public URLs as the only redirect targets, brute-force protection on, and the
seeded users' passwords taken from deploy/gcp/.env.prod instead of the ones
published in this repository.

Writes deploy/gcp/keycloak/mnemos-realm.json (gitignored). It holds plaintext
passwords, so it is readable only by its owner and Keycloak's container user.

    python3 deploy/gcp/render-realm.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE = HERE.parent / "keycloak" / "mnemos-realm.json"
TARGET = HERE / "keycloak" / "mnemos-realm.json"
KEYCLOAK_UID = 1000  # the `keycloak` user in quay.io/keycloak/keycloak

PASSWORD_ENV = {
    "admin@mnemos.local": "MNEMOS_DEMO_ADMIN_PASSWORD",
    "analyst@mnemos.local": "MNEMOS_DEMO_ANALYST_PASSWORD",
    "user@mnemos.local": "MNEMOS_DEMO_USER_PASSWORD",
}


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            values[key.strip()] = value.strip()
    return values


def main() -> int:
    env = {**load_env(HERE / ".env.prod"), **os.environ}
    missing = [k for k in ("MNEMOS_WEB_HOST", "MNEMOS_API_HOST", *PASSWORD_ENV.values())
               if not env.get(k)]
    if missing:
        print(f"missing in .env.prod: {', '.join(missing)}", file=sys.stderr)
        return 1

    web = f"https://{env['MNEMOS_WEB_HOST']}"
    api = f"https://{env['MNEMOS_API_HOST']}"
    realm = json.loads(SOURCE.read_text())
    realm["sslRequired"] = "external"
    realm["bruteForceProtected"] = True

    (client,) = [c for c in realm["clients"] if c["clientId"] == "mnemos-web"]
    client["redirectUris"] = [f"{web}/*", f"{api}/api/v1/auth/oidc/callback"]
    client["webOrigins"] = [web]
    client["attributes"]["post.logout.redirect.uris"] = f"{web}/*"
    # The app only uses the authorization-code flow; the password grant exists
    # for local tests and would be a credential-stuffing endpoint in public.
    client["directAccessGrantsEnabled"] = False

    for user in realm["users"]:
        if not user.get("id"):
            print(f"{user['username']} has no pinned id; refusing", file=sys.stderr)
            return 1
        user["credentials"] = [
            {"type": "password", "value": env[PASSWORD_ENV[user["username"]]],
             "temporary": False}
        ]

    TARGET.parent.mkdir(mode=0o755, exist_ok=True)
    TARGET.write_text(json.dumps(realm, indent=2) + "\n")
    TARGET.chmod(0o600)
    if os.geteuid() == 0:
        os.chown(TARGET, KEYCLOAK_UID, KEYCLOAK_UID)
    else:
        # Not root, so it cannot be handed to the container's uid: grant the
        # "other" read bit instead. Other host users are still kept out by the
        # home directory's own mode (see docs/Deploy.md).
        TARGET.chmod(0o604)
    print(f"wrote {TARGET}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

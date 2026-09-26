#!/usr/bin/env bash
# Writes deploy/gcp/.env.prod with fresh random secrets (mode 600). Refuses to
# overwrite an existing file: most of these values are baked into data volumes
# on first start, and regenerating them silently would lock the stack out of
# its own database and object store. See .env.prod.example for what each is.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
out="$here/.env.prod"
if [[ -e "$out" ]]; then
  echo "$out already exists; not overwriting" >&2
  exit 1
fi
hex() { openssl rand -hex "$1"; }
fernet() { python3 -c "import base64,os;print(base64.urlsafe_b64encode(os.urandom(32)).decode())"; }
umask 077
cat > "$out" <<ENV
# Generated $(date -u +%Y-%m-%dT%H:%M:%SZ) by gen-env.sh. Never commit this file.
MNEMOS_WEB_HOST=${MNEMOS_WEB_HOST:-mnemos.harsha2803.dev}
MNEMOS_API_HOST=${MNEMOS_API_HOST:-mnemos-api.harsha2803.dev}
MNEMOS_WS_HOST=${MNEMOS_WS_HOST:-mnemos-ws.harsha2803.dev}
MNEMOS_AUTH_HOST=${MNEMOS_AUTH_HOST:-mnemos-auth.harsha2803.dev}

POSTGRES_PASSWORD=$(hex 24)
MNEMOS_APP_DATABASE_PASSWORD=$(hex 24)
MNEMOS_RO_DATABASE_PASSWORD=$(hex 24)
KEYCLOAK_DB_PASSWORD=$(hex 24)
OBJECT_STORE_ACCESS_KEY=mnemos-$(hex 4)
OBJECT_STORE_SECRET_KEY=$(hex 24)

MNEMOS_JWT_SECRET=$(hex 48)
MNEMOS_DSN_ENCRYPTION_KEY=$(fernet)
MNEMOS_SOURCE_ENCRYPTION_KEY=$(fernet)
MNEMOS_TOOL_ENCRYPTION_KEY=$(fernet)

KEYCLOAK_ADMIN_PASSWORD=$(hex 16)
MNEMOS_BOOTSTRAP_ADMIN_PASSWORD=$(hex 16)
MNEMOS_DEMO_ADMIN_PASSWORD=$(hex 8)
MNEMOS_DEMO_ANALYST_PASSWORD=$(hex 8)
MNEMOS_DEMO_USER_PASSWORD=$(hex 8)
ENV
echo "wrote $out"

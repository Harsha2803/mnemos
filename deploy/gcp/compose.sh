#!/usr/bin/env bash
# The only way to run the production stack: fixed project name, both compose
# files, the production env file. Any `docker compose` arguments pass through.
#
#   deploy/gcp/compose.sh up -d
#   deploy/gcp/compose.sh logs -f api
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
root="$(cd "$here/../.." && pwd)"
env_file="$here/.env.prod"
if [[ ! -f "$env_file" ]]; then
  echo "missing $env_file — run deploy/gcp/gen-env.sh first" >&2
  exit 1
fi
exec docker compose -p mnemos --project-directory "$root" \
  -f "$root/docker-compose.yml" -f "$here/docker-compose.prod.yml" \
  --env-file "$env_file" "$@"

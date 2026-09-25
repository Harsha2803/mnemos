# Deploying the public demo

Mnemos runs as a public demo on one Google Compute Engine VM, **on demand**: the VM
is started before an interview and stopped after, so the rest of the time it costs
only its disk. Everything here lives in [`deploy/gcp/`](../deploy/gcp/). The local
development stack (`docker compose up -d`, [`docker-compose.yml`](../docker-compose.yml))
is unchanged by any of it.

| URL | Serves | Container port |
|---|---|---|
| https://mnemos.harsha2803.dev | web app | 3000 |
| https://mnemos-api.harsha2803.dev | API, SSE chat streaming | 8000 |
| https://mnemos-ws.harsha2803.dev | realtime WebSocket gateway | 8001 |
| https://mnemos-auth.harsha2803.dev | Keycloak OIDC | 8080 |

Four hostnames because the browser talks to all four directly (split-horizon OIDC —
see the comments in `docker-compose.yml`), which keeps the application code identical
to local development.

## Architecture

```
Browser ──HTTPS──► nginx on the VM (:443, Let's Encrypt; :80 → 301)
                     ├─ mnemos.…       → 127.0.0.1:3000  web
                     ├─ mnemos-api.…   → 127.0.0.1:8000  api (SSE, buffering off)
                     ├─ mnemos-ws.…    → 127.0.0.1:8001  realtime (WebSocket)
                     └─ mnemos-auth.…  → 127.0.0.1:8080  keycloak (/admin/ → 403)
                   compose network only: postgres, redis, minio, ollama, worker,
                   demo-mcp, and the migrate / init jobs
```

- **VM:** `mnemos-demo`, `asia-south2-a`, e2-standard-4, Ubuntu 24.04, 30 GB disk, no
  service account, SSH only through IAP. Firewall opens 80/443 and nothing else.
- **IP is ephemeral.** It changes on every start; the laptop's `up` command repoints
  the four DNS A records (Cloud DNS zone `harsha2803-dev`, TTL 60).
- **Boot:** the instance startup script ([`vm-startup-script.sh`](../deploy/gcp/vm-startup-script.sh))
  arms a power-off 4 hours after boot (cost safety net; `sudo shutdown -c` cancels),
  installs Docker on first boot, and runs `certbot renew` 10 minutes after boot. Then
  [`mnemos.service`](../deploy/gcp/mnemos.service) brings the stack up.

## What the production override changes

[`docker-compose.prod.yml`](../deploy/gcp/docker-compose.prod.yml) is an override, always
run through [`compose.sh`](../deploy/gcp/compose.sh), which fixes the project name
(`-p mnemos`), both files and the env file:

- **Ports:** only the four above are published, on `127.0.0.1`. Postgres, Redis,
  MinIO, Ollama and demo-mcp publish nothing.
- **Secrets:** every development credential in the base file is replaced from
  `deploy/gcp/.env.prod` (gitignored, mode 600, written by
  [`gen-env.sh`](../deploy/gcp/gen-env.sh); names in
  [`.env.prod.example`](../deploy/gcp/.env.prod.example)). `MNEMOS_ENV=production`
  makes `core/config.py` refuse to start with any development secret.
- **`mnemos_ro`:** its development password is public in
  `deploy/postgres/init/02-analytics-seed.sql`; the `db-prod-init` job resets it from
  `.env.prod` on every start, and creates Keycloak's database and role.
- **Keycloak** runs `start` (production mode) with its state in that Postgres database.
  The hostname stays dynamic (`hostname-strict=false`), exactly as in development: the
  API fetches OIDC discovery over `http://keycloak:8080` and requires every discovered
  endpoint to sit under that issuer (`features/identity/providers/oidc.py`), which a
  pinned public `KC_HOSTNAME` would break. The browser still only sees the public
  HTTPS URL, because nginx forwards `Host`/`X-Forwarded-Proto` and Keycloak trusts them
  (`proxy-headers=xforwarded`; its port is loopback-only).
- **Realm:** [`render-realm.py`](../deploy/gcp/render-realm.py) derives the production
  realm from the committed development one, so the pinned user ids (TRACKER D1 bug 1),
  roles, client and mappers cannot drift. It changes only: `sslRequired: external`,
  public redirect/web origins, brute-force protection on, the password grant off, and
  the three seeded users' passwords from `.env.prod`. Output is
  `deploy/gcp/keycloak/mnemos-realm.json`, gitignored. Keycloak imports it only while
  the realm does not exist; later changes go through the admin console.
- **Proxy headers:** `FORWARDED_ALLOW_IPS=*` on api and realtime, because nginx reaches
  them over the Docker bridge rather than from 127.0.0.1. Safe because the ports are
  loopback-only and nginx *overwrites* `X-Forwarded-For` rather than appending to a
  client-supplied one.
- **Session log files are off** (`MNEMOS_SESSION_LOG_ENABLED=false`): they hold
  visitors' chat content and grow without bound.
- **Web build args** carry the public URLs, since `NEXT_PUBLIC_*` is inlined at
  `next build`.

## First deploy on a fresh VM

```bash
git clone https://github.com/Harsha2803/mnemos.git ~/mnemos && cd ~/mnemos
deploy/gcp/gen-env.sh                  # refuses to overwrite an existing .env.prod
python3 deploy/gcp/render-realm.py
deploy/gcp/compose.sh build && docker builder prune -f
deploy/gcp/compose.sh up -d            # first start pulls the ~2 GB Ollama model
until curl -s http://127.0.0.1:8000/readyz | grep -q '"status":"ready"'; do sleep 5; done

# The first org and its internal admin. The password travels in the environment,
# never in argv.
set -a; . deploy/gcp/.env.prod; set +a
deploy/gcp/compose.sh exec -e MNEMOS_BOOTSTRAP_ADMIN_PASSWORD api mnemosctl bootstrap \
  --org-slug mnemos --org-name Mnemos --admin-email admin@mnemos.local
# Demo state, as `make demo-seed` does it.
deploy/gcp/compose.sh exec api mnemosctl datasource introspect --org-slug mnemos
deploy/gcp/compose.sh exec api mnemosctl datasource seed-glossary --org-slug mnemos
deploy/gcp/compose.sh exec api mnemosctl connector register --org-slug mnemos \
  --slug demo-fixtures --name "Demo fixtures" --kind local_fs --root /fixtures/sources

# Sign in once at https://mnemos.harsha2803.dev as analyst@mnemos.local (that
# provisions the user row), then grant the demo user its roles:
deploy/gcp/compose.sh exec -T postgres psql -U mnemos -d mnemos -v ON_ERROR_STOP=1 \
  < deploy/gcp/demo-access.sql

# nginx + TLS (once)
sudo apt-get install -y nginx certbot python3-certbot-nginx
sudo cp deploy/gcp/nginx/mnemos.conf /etc/nginx/sites-available/mnemos
sudo cp deploy/gcp/nginx/mnemos-proxy.conf /etc/nginx/snippets/mnemos-proxy.conf
sudo ln -s /etc/nginx/sites-available/mnemos /etc/nginx/sites-enabled/mnemos
sudo certbot --nginx --cert-name mnemos -d mnemos.harsha2803.dev \
  -d mnemos-api.harsha2803.dev -d mnemos-ws.harsha2803.dev -d mnemos-auth.harsha2803.dev

# Start on boot
sudo cp deploy/gcp/mnemos.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable mnemos
```

certbot rewrites the installed site file (it adds the `listen 443 ssl` lines and the
HTTP→HTTPS redirects). The committed copy is the pre-certbot source; after editing
it, apply the same edit to the installed file rather than overwriting it.

## Operating it

- **Sign-in:** workspace `mnemos`, `analyst@mnemos.local`, password
  `MNEMOS_DEMO_ANALYST_PASSWORD` from `.env.prod` — never the public development one.
  That user holds the `analyst` role plus a `demo` role (analyst + `tool:manage`) from
  [`demo-access.sql`](../deploy/gcp/demo-access.sql), which is what lets it run the
  whole of [`Demo.md`](Demo.md), MCP registration included. `admin@mnemos.local`
  cannot sign in through Keycloak while `mnemosctl bootstrap` uses the same email
  (TRACKER §4 item 40).
- **Checking it end to end:** the Playwright suite runs against the public URLs from a
  container on the compose network (demo-mcp is not published, hence the network):

  ```bash
  set -a; . deploy/gcp/.env.prod; set +a
  docker run --rm --ipc=host --network mnemos_default -v "$PWD/frontend:/src:ro" \
    -e MNEMOS_E2E_WEB_URL=https://$MNEMOS_WEB_HOST -e MNEMOS_E2E_API_URL=https://$MNEMOS_API_HOST \
    -e MNEMOS_E2E_KEYCLOAK_URL=https://$MNEMOS_AUTH_HOST -e MNEMOS_E2E_DEMO_MCP_URL=http://demo-mcp:8100 \
    -e MNEMOS_E2E_PASSWORD="$MNEMOS_DEMO_ANALYST_PASSWORD" -e CI=1 \
    mcr.microsoft.com/playwright:v1.62.1-noble \
    bash -c 'cp -r /src /work && cd /work && rm -rf node_modules && npm ci && npx playwright test'
  ```

  It leaves its test conversations, documents and MCP servers in the analyst's
  workspace.
- **Keycloak admin console:** blocked publicly. From the laptop:
  `gcloud compute ssh mnemos-demo --tunnel-through-iap -- -L 8080:127.0.0.1:8080`, then
  http://localhost:8080/admin as `admin` / `KEYCLOAK_ADMIN_PASSWORD`.
- **Logs / state:** `deploy/gcp/compose.sh ps`, `deploy/gcp/compose.sh logs -f api`.
- **Update the code:** `git pull && deploy/gcp/compose.sh up -d --build && docker builder prune -f`.
- **Work session longer than 4 hours:** `sudo shutdown -c`, then re-arm with
  `sudo shutdown -h +240`.
- **Disk:** 30 GB, of which the Ollama image and model take ~11 GB. Prune the build
  cache after each build. Growing to 40 GB costs about ₹100/month more.

## Laptop controls

`init`, `up`, `down`, `status`, `extend`, `ssh`, `logs` (and the shared `lib.sh`) live
on the owner's laptop and pin every gcloud call to the personal account and project.
`up` treats the app as ready when `https://mnemos-api.harsha2803.dev/readyz` reports
`"status":"ready"`, so that endpoint stays public. They belong in
`deploy/gcp/laptop/`; see TRACKER §6 for their status.

## Known limitations

See TRACKER §6 — the MinIO images are no longer downloadable, DNS goes stale after the
automatic power-off, and the link is dead while the VM is off.

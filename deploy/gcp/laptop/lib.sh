# Shared settings and helpers for the mnemos-demo commands. Sourced, not run.
# Every gcloud call is pinned to the personal account and project, so no other
# gcloud account or project can ever be used by accident.

ACCOUNT="cheellasreeharsha2803@gmail.com"
PROJECT="gmail-mcp-466813"
ZONE="asia-south2-a"
VM="mnemos-demo"
DNS_ZONE="harsha2803-dev"
DOMAIN="harsha2803.dev"
HOSTS=(mnemos mnemos-api mnemos-ws mnemos-auth)
TTL=60

g() { gcloud --account="$ACCOUNT" --project="$PROJECT" --verbosity=error "$@"; }

bold()  { printf '\033[1m%s\033[0m\n' "$*"; }
ok()    { printf '  \033[32m✓\033[0m %s\n' "$*"; }
warn()  { printf '  \033[33m!\033[0m %s\n' "$*"; }
fail()  { printf '  \033[31m✗\033[0m %s\n' "$*" >&2; }

require_login() {
  if ! command -v gcloud >/dev/null 2>&1; then
    fail "gcloud is not installed or not on PATH."; exit 1
  fi
  if ! gcloud auth print-access-token --account="$ACCOUNT" >/dev/null 2>&1; then
    fail "Not logged in to Google Cloud as $ACCOUNT. Run ./init (it will log you in)."; exit 1
  fi
}

vm_status() { g compute instances describe "$VM" --zone="$ZONE" --format='value(status)'; }
vm_ip()     { g compute instances describe "$VM" --zone="$ZONE" --format='value(networkInterfaces[0].accessConfigs[0].natIP)'; }

vm_ssh() {  # run a command on the VM through IAP (no public SSH)
  g compute ssh "$VM" --zone="$ZONE" --tunnel-through-iap --quiet -- -T "$@" 2> >(grep -v -E 'NumPy|numpy|bandwidth|^WARNING: *$|^$' >&2)
}

dns_upsert() {  # $1 = ip. The VM's startup script writes the same records, so either may go first.
  for h in "${HOSTS[@]}"; do
    local name="$h.$DOMAIN." cur
    cur=$(g dns record-sets describe "$name" --zone="$DNS_ZONE" --type=A --format='value(rrdatas[0])' 2>/dev/null || true)
    if [[ "$cur" == "$1" ]]; then
      :  # already right (the VM got there first)
    elif [[ -n "$cur" ]]; then
      g dns record-sets update "$name" --zone="$DNS_ZONE" --type=A --ttl="$TTL" --rrdatas="$1" >/dev/null
    else
      g dns record-sets create "$name" --zone="$DNS_ZONE" --type=A --ttl="$TTL" --rrdatas="$1" >/dev/null 2>&1 \
        || g dns record-sets update "$name" --zone="$DNS_ZONE" --type=A --ttl="$TTL" --rrdatas="$1" >/dev/null
    fi
    ok "$h.$DOMAIN -> $1"
  done
}

dns_delete() {
  for h in "${HOSTS[@]}"; do
    local name="$h.$DOMAIN."
    if g dns record-sets describe "$name" --zone="$DNS_ZONE" --type=A >/dev/null 2>&1; then
      g dns record-sets delete "$name" --zone="$DNS_ZONE" --type=A >/dev/null
      ok "removed $h.$DOMAIN"
    fi
  done
}

api_ready() {  # $1 = ip; true when /readyz reports ready
  curl -sf --max-time 5 --resolve "mnemos-api.$DOMAIN:443:$1" "https://mnemos-api.$DOMAIN/readyz" 2>/dev/null | grep -q '"status":"ready"'
}

# Remote snippet: print the scheduled power-off time in IST (or say none is set).
SHOW_POWEROFF='t=$(sudo shutdown --show 2>&1 | sed -n "s/^Shutdown scheduled for \(.*\), use.*/\1/p"); if [ -n "$t" ]; then TZ=Asia/Kolkata date -d "$t" "+Powers off at %a %d %b, %H:%M IST"; else echo "No auto power-off scheduled."; fi'

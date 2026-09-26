#!/bin/bash
# Runs on every boot of mnemos-demo.
# 1. Cost safety net: power off 4 hours after boot. Cancel with `sudo shutdown -c`.
shutdown -h +240 "mnemos-demo: auto-shutdown 4h after boot (cancel: sudo shutdown -c)" || true
# 2. First boot only: install Docker Engine + Compose plugin from Docker's apt repo.
if ! command -v docker >/dev/null 2>&1; then
  set -e
  apt-get update
  apt-get install -y ca-certificates curl git jq
  install -m 0755 -d /etc/apt/keyrings
  curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
  chmod a+r /etc/apt/keyrings/docker.asc
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable" > /etc/apt/sources.list.d/docker.list
  apt-get update
  apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
  systemctl enable --now docker
  touch /var/lib/mnemos-docker-installed
fi
# 3. Point the four demo hostnames at this boot's ephemeral IP, so Start in the
#    Cloud console (or the phone app) is all it takes to bring the demo up. Uses the
#    attached service account mnemos-dns, which can edit records in this one DNS
#    zone and nothing else (deploy/gcp/setup-vm-dns.sh). vm-shutdown-script.sh
#    deletes the records again. The laptop's `up` writes the same records; harmless.
dns_sync() {
  local md=http://metadata.google.internal/computeMetadata/v1
  local api=https://dns.googleapis.com/dns/v1/projects/gmail-mcp-466813/managedZones/harsha2803-dev
  local names='["mnemos.harsha2803.dev.","mnemos-api.harsha2803.dev.","mnemos-ws.harsha2803.dev.","mnemos-auth.harsha2803.dev."]'
  local ip token current body
  ip=$(curl -sf --max-time 5 -H 'Metadata-Flavor: Google' "$md/instance/network-interfaces/0/access-configs/0/external-ip") || return 1
  token=$(curl -sf --max-time 5 -H 'Metadata-Flavor: Google' "$md/instance/service-accounts/default/token" | jq -er .access_token) || return 1
  current=$(curl -sf --max-time 10 -H "Authorization: Bearer $token" "$api/rrsets?maxResults=1000") || return 1
  # One atomic change: delete whatever A records the four names have, add the new ones.
  body=$(jq -c --argjson names "$names" --arg ip "$ip" '
    [.rrsets[]? | select(.type == "A" and (.name | IN($names[])))] as $old
    | [$names[] | {name: ., type: "A", ttl: 60, rrdatas: [$ip]}] as $new
    | if ($old | map({name, ttl, rrdatas}) | sort_by(.name)) == ($new | map({name, ttl, rrdatas}) | sort_by(.name))
      then empty else {deletions: $old, additions: $new} end' <<<"$current") || return 1
  if [ -z "$body" ]; then echo "mnemos-dns: records already point at $ip"; return 0; fi
  curl -sf --max-time 10 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
    -d "$body" "$api/changes" >/dev/null || return 1
  echo "mnemos-dns: 4 A records -> $ip"
}
for _ in $(seq 1 18); do dns_sync && break; sleep 10; done || true
# 4. Let's Encrypt renewal. The VM is usually off when certbot.timer fires, so
#    also try 10 minutes after every boot, once step 3 has pointed DNS at this
#    boot's IP. A no-op unless within 30 days of expiry.
if command -v certbot >/dev/null 2>&1; then
  systemd-run --on-active=10min --unit=mnemos-cert-renew-$(date +%s) certbot renew --quiet --no-random-sleep-on-renew || true
fi

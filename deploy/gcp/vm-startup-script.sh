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
# 3. Let's Encrypt renewal. The VM is usually off when certbot.timer fires, so
#    also try 10 minutes after every boot, once the laptop's `mnemos-demo up`
#    has pointed DNS at this boot's IP. A no-op unless within 30 days of expiry.
if command -v certbot >/dev/null 2>&1; then
  systemd-run --on-active=10min --unit=mnemos-cert-renew-$(date +%s) certbot renew --quiet --no-random-sleep-on-renew || true
fi

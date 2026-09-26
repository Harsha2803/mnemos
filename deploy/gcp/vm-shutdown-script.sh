#!/bin/bash
# Runs when mnemos-demo shuts down: Stop in the Cloud console or phone app, the
# laptop's `down`, and the 4-hour auto power-off alike. Deletes the four demo A
# records so they never point at an ephemeral IP Google may give to someone else.
# Same service account and zone as step 3 of vm-startup-script.sh.
md=http://metadata.google.internal/computeMetadata/v1
api=https://dns.googleapis.com/dns/v1/projects/gmail-mcp-466813/managedZones/harsha2803-dev
names='["mnemos.harsha2803.dev.","mnemos-api.harsha2803.dev.","mnemos-ws.harsha2803.dev.","mnemos-auth.harsha2803.dev."]'
# A console Stop gives the guest about 90 seconds, so keep the retries short.
for _ in 1 2 3 4 5; do
  token=$(curl -sf --max-time 5 -H 'Metadata-Flavor: Google' "$md/instance/service-accounts/default/token" | jq -er .access_token) \
    && current=$(curl -sf --max-time 10 -H "Authorization: Bearer $token" "$api/rrsets?maxResults=1000") \
    && body=$(jq -c --argjson names "$names" '
         [.rrsets[]? | select(.type == "A" and (.name | IN($names[])))]
         | if length == 0 then empty else {deletions: .} end' <<<"$current") \
    || { sleep 3; continue; }
  if [ -z "$body" ]; then echo "mnemos-dns: no records to delete"; exit 0; fi
  if curl -sf --max-time 10 -H "Authorization: Bearer $token" -H 'Content-Type: application/json' \
       -d "$body" "$api/changes" >/dev/null; then
    echo "mnemos-dns: A records deleted"; exit 0
  fi
  sleep 3
done
echo "mnemos-dns: could not delete the A records; the next start or ./down fixes them" >&2
exit 1

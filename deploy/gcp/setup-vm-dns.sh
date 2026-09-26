#!/usr/bin/env bash
# One-time setup, run from the laptop, that lets mnemos-demo manage its own DNS:
# Start in the Cloud console then brings the demo up, Stop takes it down.
#   1. custom role mnemosDnsRecordEditor: record edits only (no zone create/delete)
#   2. service account mnemos-dns with NO project roles
#   3. that role bound to the account on the harsha2803-dev zone only
#   4. the account attached to the (stopped) VM with only the Cloud DNS scope
#   5. vm-startup-script.sh / vm-shutdown-script.sh installed as instance metadata
# Safe to re-run; step 5 alone is how script changes reach the VM.
set -euo pipefail
cd "$(dirname "$0")"

PROJECT=gmail-mcp-466813
ZONE=asia-south2-a
VM=mnemos-demo
DNS_ZONE=harsha2803-dev
ROLE=projects/$PROJECT/roles/mnemosDnsRecordEditor
SA=mnemos-dns@$PROJECT.iam.gserviceaccount.com
g() { gcloud --account=cheellasreeharsha2803@gmail.com --project=$PROJECT --quiet --verbosity=error "$@"; }

echo "1. role"
if ! g iam roles describe mnemosDnsRecordEditor --project=$PROJECT >/dev/null 2>&1; then
  g iam roles create mnemosDnsRecordEditor --project=$PROJECT --stage=GA \
    --title="Mnemos DNS record editor" \
    --description="Edit records in Cloud DNS zone harsha2803-dev. Bound on that zone only, never the project." \
    --permissions=dns.changes.create,dns.changes.get,dns.managedZones.get,dns.resourceRecordSets.create,dns.resourceRecordSets.delete,dns.resourceRecordSets.get,dns.resourceRecordSets.list,dns.resourceRecordSets.update \
    >/dev/null
fi

echo "2. service account"
if ! g iam service-accounts describe "$SA" >/dev/null 2>&1; then
  g iam service-accounts create mnemos-dns --display-name="mnemos-demo VM: DNS records only" \
    --description="Attached to VM mnemos-demo. No project roles; edits records in zone harsha2803-dev only." >/dev/null
fi

echo "3. zone-level binding"
policy=$(mktemp); trap 'rm -f "$policy"' EXIT
for i in 1 2 3 4 5 6; do  # a brand-new service account can take a moment to be bindable
  g dns managed-zones get-iam-policy "$DNS_ZONE" --format=json \
    | jq --arg role "$ROLE" --arg m "serviceAccount:$SA" '
        .bindings = ((.bindings // []) | map(select(.role != $role)) + [{role: $role, members: [$m]}])' >"$policy"
  g dns managed-zones set-iam-policy "$DNS_ZONE" --policy-file="$policy" >/dev/null && break
  [[ $i == 6 ]] && { echo "could not set the zone policy" >&2; exit 1; }
  sleep 10
done

echo "4. attach to $VM"
current=$(g compute instances describe $VM --zone=$ZONE --format='value(serviceAccounts[0].email)')
if [[ "$current" != "$SA" ]]; then
  status=$(g compute instances describe $VM --zone=$ZONE --format='value(status)')
  [[ "$status" == "TERMINATED" ]] || { echo "Stop $VM first (it is $status); a service account can only be attached to a stopped VM." >&2; exit 1; }
  g compute instances set-service-account $VM --zone=$ZONE \
    --service-account="$SA" --scopes=https://www.googleapis.com/auth/ndev.clouddns.readwrite >/dev/null
fi

echo "5. startup + shutdown scripts"
g compute instances add-metadata $VM --zone=$ZONE \
  --metadata-from-file=startup-script=vm-startup-script.sh,shutdown-script=vm-shutdown-script.sh >/dev/null

echo "Done. Check:"
g compute instances describe $VM --zone=$ZONE \
  --format='table[box](status,serviceAccounts[0].email:label=SERVICE_ACCOUNT,serviceAccounts[0].scopes[0]:label=SCOPE)'
g dns managed-zones get-iam-policy "$DNS_ZONE" --format='value(bindings)'
g projects get-iam-policy $PROJECT --flatten=bindings[].members \
  --filter="bindings.members:$SA" --format='value(bindings.role)' \
  | grep -q . && echo "WARNING: $SA has project-level roles; remove them." >&2 || echo "No project-level roles for $SA (as intended)."

#!/usr/bin/env bash
# Delete Cloudflare DNS records for retired hostnames in kewar.org.
# Token comes from the environment only:  export CF_API_TOKEN=...   (needs Zone:DNS:Edit)
# Dry run by default. To actually delete:  APPLY=1 ./tools/cf-dns-cleanup.sh
set -euo pipefail
: "${CF_API_TOKEN:?export CF_API_TOKEN first}"
ZONE_NAME="kewar.org"
HOSTS="tda tta toa tna"
API="https://api.cloudflare.com/client/v4"
auth=(-H "Authorization: Bearer ${CF_API_TOKEN}" -H "Content-Type: application/json")
json() { python3 -c "import sys,json; d=json.load(sys.stdin); $1"; }

zone_id=$(curl -fsS "${auth[@]}" "$API/zones?name=$ZONE_NAME" | json 'print(d["result"][0]["id"])')
echo "zone $ZONE_NAME = $zone_id"
for h in $HOSTS; do
  fqdn="$h.$ZONE_NAME"
  recs=$(curl -fsS "${auth[@]}" "$API/zones/$zone_id/dns_records?name=$fqdn" \
         | json 'print("\n".join(f"{r[\"id\"]} {r[\"type\"]} {r[\"name\"]} {r[\"content\"]}" for r in d["result"]))')
  if [ -z "$recs" ]; then echo "$fqdn: no records (may be covered by a wildcard)"; continue; fi
  while read -r id type name content; do
    if [ "${APPLY:-0}" = "1" ]; then
      curl -fsS -X DELETE "${auth[@]}" "$API/zones/$zone_id/dns_records/$id" >/dev/null && echo "DELETED $type $name -> $content"
    else
      echo "WOULD DELETE $type $name -> $content"
    fi
  done <<< "$recs"
done
# ACME leaves _acme-challenge TXT records only transiently; nothing else to clean.

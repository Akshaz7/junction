#!/usr/bin/env bash
# LEAD: poll every 10 min for anything that unblocks a row; print what changed and exit. Never prints keys.
cd "$(dirname "$0")/.."
base_missing=$(python3 scripts/check_keys.py | grep -c MISSING)
while true; do
  set -a; . ./.env >/dev/null 2>&1; set +a
  m=$(python3 scripts/check_keys.py | grep -c MISSING)
  [ "$m" -lt "$base_missing" ] && { echo "$(date +%H:%M) keys: MISSING $base_missing -> $m"; python3 scripts/check_keys.py | grep -v MISSING; exit 0; }
  ORG=$(avn organization list --json 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin)[0]['organization_id'])" 2>/dev/null)
  v=$(curl -s -m 30 -H "Authorization: aivenv1 $AIVEN_TOKEN" "https://api.aiven.io/v1/organization/$ORG/application/vcs-integrations" | python3 -c "import sys,json;print(len(json.load(sys.stdin).get('vcs_integrations',[])))" 2>/dev/null)
  [ "${v:-0}" -gt 0 ] && { echo "$(date +%H:%M) aiven: VCS integration present ($v)"; exit 0; }
  timeout 180 modal run scripts/modal_ping.py >/tmp/modal_chk.txt 2>&1; grep -q "result pong" /tmp/modal_chk.txt && { echo "$(date +%H:%M) modal: workspace usable"; exit 0; }
  grep -qi paused /tmp/modal_chk.txt || { echo "$(date +%H:%M) modal: state changed: $(head -c 200 /tmp/modal_chk.txt)"; exit 0; }
  echo "$(date +%H:%M) still blocked (keys missing $m, vcs ${v:-?}, modal paused)" >> logs/lead_wait.log
  sleep 600
done

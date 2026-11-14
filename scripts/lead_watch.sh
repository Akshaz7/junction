#!/usr/bin/env bash
# LEAD heartbeat: pulse every 60 s into logs/pulse.log. Exit (waking the lead) when a
# pulse line is flagged '!!' or after MAX_MIN minutes (10-minute key check).
cd "$(dirname "$0")/.."
MAX_MIN="${1:-10}"
for i in $(seq 1 "$MAX_MIN"); do
  out=$(python3 scripts/pulse.py 2>&1)
  echo "$out" >> logs/pulse.log
  if echo "$out" | grep -q '^\s*!!'; then echo "FLAG after $i min"; echo "$out" | grep '!!'; exit 0; fi
  sleep 60
done
echo "TIMER $MAX_MIN min: run check_keys"

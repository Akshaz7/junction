#!/usr/bin/env bash
# Run a heavy command with at most 2 heavy jobs at once across all workers.
# Usage: scripts/heavy.sh <command> [args...]
# Heavy = xcodebuild, IFC/batch conversion, bulk inference, bench, Playwright, Docker builds.
set -u
SLOTS="${HEAVY_SLOTS:-2}"
LOCKDIR="${TMPDIR:-/tmp}/junction-heavy"
mkdir -p "$LOCKDIR"
[ $# -eq 0 ] && { echo "usage: $0 <command> [args...]" >&2; exit 2; }

slot=""
waited=0
while [ -z "$slot" ]; do
  for i in $(seq 1 "$SLOTS"); do
    d="$LOCKDIR/slot$i"
    if mkdir "$d" 2>/dev/null; then
      slot="$d"; echo "$$ $(date +%s) $*" > "$d/owner"; break
    fi
    # Reclaim a slot whose owner process is gone.
    pid=$(awk '{print $1}' "$d/owner" 2>/dev/null || true)
    if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then rm -rf "$d"; fi
  done
  if [ -z "$slot" ]; then
    [ $((waited % 60)) -eq 0 ] && echo "heavy.sh: waiting for a slot ($SLOTS busy)" >&2
    sleep 5; waited=$((waited + 5))
  fi
done
trap 'rm -rf "$slot"' EXIT INT TERM
"$@"

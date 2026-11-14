#!/usr/bin/env bash
# LEAD test harness: run web e2e tests against a stable snapshot = last commit (HEAD)
# + only the given worker paths from the working tree, built and served on its own port.
# Workers editing other web files can then never break the test.
# Usage: scripts/test_snapshot.sh <port> "<path> <path> ..." -- <playwright args...>
# Example: scripts/test_snapshot.sh 4180 "web/src/viewer3d web/e2e/viewer3d-live.spec.ts" -- e2e/viewer3d-live.spec.ts
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PORT="$1"; PATHS="$2"; shift 2; [ "${1:-}" = "--" ] && shift
SNAP="${TMPDIR:-/tmp}/junction-snap-$PORT"
cd "$ROOT"
if [ -d "$SNAP/.git" ] || [ -f "$SNAP/.git" ]; then
  git -C "$SNAP" checkout -q --detach -f HEAD 2>/dev/null || true
  git -C "$SNAP" reset -q --hard "$(git rev-parse HEAD)"
  git -C "$SNAP" clean -qfd -e node_modules
else
  rm -rf "$SNAP"; git worktree add -f --detach "$SNAP" HEAD -q
fi
for p in $PATHS; do
  if [ -e "$ROOT/$p" ]; then mkdir -p "$SNAP/$(dirname "$p")"; rm -rf "$SNAP/$p"; cp -R "$ROOT/$p" "$SNAP/$p"; fi
done
ln -sfn "$ROOT/web/node_modules" "$SNAP/web/node_modules"
cd "$SNAP/web"
sed -i '' "s#http://localhost:5173#http://localhost:$PORT#g" playwright.config.ts
# Serve the built snapshot with the same /api and /ws proxies (vite preview reuses server.proxy).
npx vite build >/tmp/snap-build-$PORT.log 2>&1 || { echo "SNAPSHOT BUILD FAILED"; tail -20 /tmp/snap-build-$PORT.log; exit 1; }
pkill -f "vite preview --port $PORT" 2>/dev/null || true
nohup npx vite preview --port "$PORT" --strictPort >/tmp/snap-preview-$PORT.log 2>&1 &
PREV=$!
for i in $(seq 1 30); do curl -sf "http://localhost:$PORT/" >/dev/null && break; sleep 0.5; done
set +e
npx playwright test "$@"
RC=$?
kill $PREV 2>/dev/null
exit $RC

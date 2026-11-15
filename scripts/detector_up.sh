#!/usr/bin/env bash
# Put the door-detector weights on OUR Modal workspace, deploy the app, run one test call.
# usage: scripts/detector_up.sh <path/to/best.pt> [path/to/result.json] [path/to/test.pdf]
#   result.json (optional): {"conf": {"door": 0.4, "window": 0.3, "fixture": 0.3}} per-class thresholds picked on VAL.
# Needs: `modal` CLI with profile akshatsunita07 (our workspace) in ~/.modal.toml. Keys are never printed.
set -euo pipefail
cd "$(dirname "$0")/.."
W="${1:?usage: detector_up.sh <best.pt> [result.json] [test.pdf]}"
RJ="${2:-}"; PDF="${3:-}"
[ -f "$W" ] || { echo "no such file: $W" >&2; exit 1; }
# Use the modal profile, NOT .env: .env's MODAL_TOKEN_* are Awais's workspace, which already has his own "junction-det" app
# (H100, his volumes). Deploying there would overwrite it.
unset MODAL_TOKEN_ID MODAL_TOKEN_SECRET
PROF="${MODAL_PROFILE:-akshatsunita07}"; export MODAL_PROFILE="$PROF"
CUR=$(modal profile current)
echo "modal workspace: $CUR"
[ "$CUR" = "$PROF" ] || { echo "active profile is $CUR, expected $PROF (set MODAL_PROFILE)" >&2; exit 1; }
VOL=junction-det-weights
modal volume create "$VOL" >/dev/null 2>&1 || true
modal volume put --force "$VOL" "$W" /best.pt
[ -n "$RJ" ] && modal volume put --force "$VOL" "$RJ" /result.json
modal volume ls "$VOL" /
modal deploy experiments/detector/modal/detect.py
if [ -z "$PDF" ]; then   # a small vector PDF: first uploaded one that has a text layer
  PDF=$(ls -S -r artifacts/uploads/*.pdf data/junction-dataset-preview/data/*/*.pdf 2>/dev/null | head -1 || true)
fi
[ -f "$PDF" ] || { echo "deployed, but no test PDF found; pass one as 3rd arg" >&2; exit 0; }
echo "test pdf: $PDF"
PY="${PDF_DETECT_PY:-$(head -1 "$(command -v modal)" | sed "s/^#!//")}"  # python of the modal install
"$PY" - "$PDF" <<'PYEOF'
import sys, time, modal, collections
t = time.time()
r = modal.Cls.from_name("junction-det", "Detector")().detect.remote(open(sys.argv[1], "rb").read(), 0, None)
n = collections.Counter(i["kind"] for i in r["items"])
print(f"doors={n.get('door', 0)} windows={n.get('window', 0)} fixtures={n.get('fixture', 0)} "
      f"gpu_s={r['seconds']} wall_s={time.time() - t:.1f} (first call includes cold start)")
PYEOF
echo "OK. Flip: PDF_DETECT=1 in .env, then .venv/bin/python scripts/aiven_env.py <rev> (sets Modal token for OUR workspace) and redeploy."

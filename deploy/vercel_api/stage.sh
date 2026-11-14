#!/usr/bin/env bash
# Stage the API for Vercel (fallback host until the Aiven GitHub App exists). Usage: deploy/vercel_api/stage.sh <out_dir>
# Then: cd <out_dir> && vercel link --project hologram-api && vercel deploy --prod   (DATABASE_URL is a Vercel env secret)
set -euo pipefail
OUT=${1:?out dir}; ROOT=$(git rev-parse --show-toplevel)
mkdir -p "$OUT"
git -C "$ROOT" archive HEAD server engine | tar -x -C "$OUT"
cp -R "$ROOT/deploy/demo_artifacts" "$OUT/artifacts"  # includes local scene.usdz files (git-ignored) so iPhone AR can load them
rm -rf "$OUT/server/tests" "$OUT/engine/tests"
cp "$ROOT/deploy/vercel_api/index.py" "$ROOT/deploy/vercel_api/requirements.txt" "$ROOT/deploy/vercel_api/vercel.json" "$OUT/"

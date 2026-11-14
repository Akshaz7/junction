#!/usr/bin/env bash
# Renders the white STOA mark/wordmark used in the AR top lockup from the local-only logo SVG.
# The logo and the rendered PNG are gitignored (never commit them). Without the PNG the app shows "STOA PRO" as text.
# Needs rsvg-convert and ImageMagick (brew install librsvg imagemagick). Run before building the app.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SVG="${STOA_LOGO_SVG:-$ROOT/web/public/brand/stoa-logo.svg}"
OUT="$ROOT/ios/Hologram/Assets.xcassets/StoaLockup.imageset/stoa-lockup.png"
[ -f "$SVG" ] || { echo "Logo not found: $SVG (local only, not in git)" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
rsvg-convert -w 600 "$SVG" -o "$TMP/logo.png"
magick "$TMP/logo.png" -alpha extract "$TMP/mask.png"
magick "$TMP/logo.png" -fill white -colorize 100 "$TMP/mask.png" -compose CopyOpacity -composite "$OUT"
echo "Wrote $OUT"

#!/usr/bin/env bash
# Renders the 1024x1024 app icon: the Stoa wordmark in white, centred, 70% wide, on dark green.
# The logo (web/public/brand/stoa-logo.svg) and the rendered PNG are local only and gitignored.
# Needs rsvg-convert and ImageMagick (brew install librsvg imagemagick). Run before building the app.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
SVG="${STOA_LOGO_SVG:-$ROOT/web/public/brand/stoa-logo.svg}"
OUT="$ROOT/ios/Hologram/Assets.xcassets/AppIcon.appiconset/icon-1024.png"
GREEN="${ICON_BG:-#173d2a}"
[ -f "$SVG" ] || { echo "Logo not found: $SVG (local only, not in git)" >&2; exit 1; }
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
rsvg-convert -w 717 "$SVG" -o "$TMP/logo.png"
# Everything visible becomes white, keeping the logo's own alpha.
magick "$TMP/logo.png" -alpha extract "$TMP/mask.png"
magick "$TMP/logo.png" -fill white -colorize 100 "$TMP/mask.png" -compose CopyOpacity -composite "$TMP/white.png"
magick -size 1024x1024 "xc:$GREEN" "$TMP/white.png" -gravity center -composite -alpha off "$OUT"
echo "Wrote $OUT"

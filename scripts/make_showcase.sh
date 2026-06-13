#!/usr/bin/env bash
# make_showcase.sh — regenerate the README showcase screenshots from a real output HTML.
#
# Usage:   bash scripts/make_showcase.sh <trip>.html [out_dir]
# Example: bash scripts/make_showcase.sh examples/成都4日游行程.html assets
#
# Produces (always from a REAL run artifact — never a mocked page):
#   hero-desktop.png   1280px-wide top of page: themed header + overview + Leaflet map
#   mobile.png         390px-wide phone view of the top of page
#   full.png           one 1280x16000 full-page capture — crop section shots
#                      (住宿备选, day timeline) from it with PIL, e.g.:
#                      py -c "from PIL import Image; Image.open('assets/full.png').crop((0,Y1,1280,Y2)).save('assets/hotels-desktop.png')"
#                      (Don't screenshot a #fragment URL directly: the anchor jump
#                      lands before layout settles and you get a black frame.)
#
# Needs Chrome or Edge. The virtual-time budget gives Leaflet time to pull OSM tiles.
set -euo pipefail

HTML="${1:?usage: make_showcase.sh <trip>.html [out_dir]}"
OUT="${2:-assets}"
mkdir -p "$OUT"

BROWSER=""
for c in "/c/Program Files/Google/Chrome/Application/chrome.exe" \
         "/c/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" \
         "$(command -v google-chrome || true)" \
         "$(command -v chromium || true)"; do
  [ -n "$c" ] && [ -e "$c" ] && BROWSER="$c" && break
done
[ -n "$BROWSER" ] || { echo "no Chrome/Edge found"; exit 1; }

if command -v cygpath >/dev/null 2>&1; then
  URL="file:///$(cygpath -m "$(realpath "$HTML")")"
else
  URL="file://$(realpath "$HTML")"
fi

shot() { # shot <outfile> <WxH> <url>
  # --headless=new is REQUIRED for narrow (mobile) widths: the old headless mode
  # lays the page out at a wider viewport and clips the screenshot to the window,
  # truncating the right edge. New headless honors the real device-width viewport.
  "$BROWSER" --headless=new --disable-gpu --hide-scrollbars --force-device-scale-factor=1 \
    --virtual-time-budget=9000 --window-size="$2" --screenshot="$(command -v cygpath >/dev/null 2>&1 && cygpath -w "$PWD/$1" || echo "$PWD/$1")" \
    "$3" 2>/dev/null
  echo "wrote $1"
}

shot "$OUT/hero-desktop.png" "1280,1700"  "$URL"
shot "$OUT/full.png"         "1280,16000" "$URL"

# mobile.png is NOT a plain --window-size=390 shot: headless misrenders a narrow
# top-level viewport on hi-DPI displays (right edge truncates). Use the iframe-
# wrapper renderer instead (desktop top-level + a 390px sub-frame = true mobile).
py "$(dirname "$0")/make_mobile_shot.py" "$HTML" "$OUT/mobile.png" 2>/dev/null \
  || python3 "$(dirname "$0")/make_mobile_shot.py" "$HTML" "$OUT/mobile.png"

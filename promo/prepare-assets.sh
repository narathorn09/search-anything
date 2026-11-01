#!/bin/sh
# Gets everything the film needs that is not in this repo:
#   - the onetake library (lib/motion.js) and scripts, from github.com/feitangyuan/onetake (PolyForm Noncommercial)
#   - the app's fonts, copied into public/
# The footage itself comes from record-product.js (see README.md).
set -e
cd "$(dirname "$0")"
ONETAKE="${ONETAKE:-$HOME/onetake}"
[ -d "$ONETAKE" ] || git clone --depth 1 https://github.com/feitangyuan/onetake "$ONETAKE"
cp "$ONETAKE/lib/motion.js" film/
mkdir -p public
cp ../cahon/static/fonts/google-sans-*.woff2 public/
echo "ready: film/motion.js, public/ fonts (onetake at $ONETAKE)"

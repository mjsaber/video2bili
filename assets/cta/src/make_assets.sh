#!/usr/bin/env bash
# Regenerate the static overlay assets (background, subscribe button, arrow).
# The mascot itself comes from gen_char.py (codex image_gen) — run that separately.
set -euo pipefail
cd "$(dirname "$0")"

# Warm radial-gradient background: gold glow center -> near-black edges.
magick -size 1920x1080 radial-gradient:'#4a3414'-'#080604' bg.png

# Plain red rounded subscribe button (the 訂閱 text is drawn by ffmpeg drawtext
# in build_tts.sh — ImageMagick's freetype can't load macOS .ttc CJK fonts).
magick -size 400x132 xc:none -fill '#FF0000' -draw 'roundrectangle 0,0,399,131,26,26' button.png

# Chunky right-pointing arrow (yellow fill, black outline).
magick -size 230x150 xc:none -fill '#FFD400' -stroke black -strokewidth 7 \
  -draw 'polygon 12,48 120,48 120,14 218,75 120,136 120,102 12,102' arrow.png

echo "[make_assets] bg.png button.png arrow.png regenerated"

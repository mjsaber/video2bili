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

# Grey "已訂閱" button (post-click state; CJK text drawn by ffmpeg drawtext).
magick -size 400x132 xc:none -fill '#6E6E6E' -draw 'roundrectangle 0,0,399,131,26,26' button_grey.png

# Notification bell (gold, black outline) — dome + lip + clapper.
magick -size 200x210 xc:none -fill '#FFD400' -stroke black -strokewidth 6 \
  -draw 'circle 100,26 100,14' \
  -draw 'path "M 100,22 C 58,22 54,62 51,112 C 49,142 28,152 28,160 L 172,160 C 172,152 151,142 149,112 C 146,62 142,22 100,22 Z"' \
  -draw 'roundrectangle 24,158,176,176,8,8' \
  -draw 'circle 100,192 100,178' \
  bell.png

# Dark-mode YouTube-style comment card (beat B): rounded dark card + gold
# letter-avatar circle. All CJK text (avatar glyph, username, comment body)
# is drawn by ffmpeg drawtext in build_tts.sh — same .ttc limitation as above.
magick -size 640x150 xc:none \
  -fill '#212121' -stroke '#3a3a3a' -strokewidth 2 \
  -draw 'roundrectangle 1,1,638,148,24,24' \
  -fill '#E8A33D' -stroke none -draw 'circle 75,75 75,33' \
  comment_card.png

echo "[make_assets] button_grey.png bell.png comment_card.png regenerated"

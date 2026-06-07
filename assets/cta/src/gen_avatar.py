"""Generate a channel-avatar headshot of the 女老板 (boss-lady) mascot.

Same character design as gen_char.py (honey-gold twin-tail tavern-keeper girl)
but framed as a head-and-shoulders bust on a warm amber glow, composed so a
centered circular crop keeps the whole face — i.e. a proper YouTube avatar that
stays legible at tiny size. Square output (1024x1024).

Usage:
    uv run python gen_avatar.py <out.png> ["extra prompt clause"]

The optional second arg lets the caller fan out a few expression variants in
parallel and pick the best.
"""
import sys
from pathlib import Path

from video2yt import image_gen

BASE = (
    "Anime bust portrait — head and shoulders, face centered and looking at the "
    "viewer — of a cheerful cozy-fantasy tavern-keeper girl. Honey-gold twin-tail "
    "hair, big sparkling eyes, warm happy open smile, a small pointed tavern hat, "
    "and a warm fantasy bartender outfit with a tiny apron. Clean cel-shaded anime "
    "style, thick bold outlines, vibrant warm gold and amber palette, high contrast "
    "and simple bold shapes so it stays clearly readable as a tiny circular profile "
    "avatar. Warm radial amber-glow background, no scenery and no clutter. The face "
    "must be large, centered, and fully inside the frame with margin, composed so a "
    "centered circular crop keeps the entire face and hat. No text, no letters, no "
    "numbers, no logos, no watermark, no UI, no border, no frame."
)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/avatar/avatar.png")
extra = sys.argv[2] if len(sys.argv) > 2 else ""
out.parent.mkdir(parents=True, exist_ok=True)

prompt = BASE + (" " + extra if extra else "")

img = image_gen.generate_codex(prompt, codex_size="1024x1024", timeout=600)
print(f"[avatar] returned mode={img.mode} size={img.size}", file=sys.stderr)
img.save(out)
print(f"[avatar] saved {out}", file=sys.stderr)

"""Generate the channel mascot via codex image_gen, preserving alpha.

Bypasses the video2yt-image CLI on purpose: that CLI force-converts to RGB
(image_gen_cli.run) which would flatten the transparent background we need
for an ffmpeg overlay. We call generate_codex() directly and save the raw
PNG with whatever mode the model returned, then report alpha presence.
"""
import sys
from pathlib import Path

from video2yt import image_gen

PROMPT = (
    "Full-body chibi anime mascot girl, energetic dancing pose: both arms "
    "raised up, one leg kicked out, mid-bounce, cheerful big sparkling eyes, "
    "wide happy open smile, lots of motion in hair and skirt. Cozy fantasy "
    "tavern-keeper theme: honey-gold twin-tail hair, a warm fantasy bartender "
    "outfit with a small apron and a tiny pointed tavern hat, holding one "
    "glowing golden coin/token. Clean cel-shaded anime style, thick bold "
    "outlines, vibrant warm gold and amber palette, high contrast so it reads "
    "clearly even at small size, mascot-friendly and friendly. The WHOLE body "
    "from head to feet must be visible and centered with margin around it. "
    "Transparent background with real alpha channel, absolutely no background "
    "scenery, no ground, no drop shadow, no text, no letters, no numbers, no "
    "logos, no watermark, no UI."
)

out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("output/mascot/mascot_raw.png")
out.parent.mkdir(parents=True, exist_ok=True)

img = image_gen.generate_codex(PROMPT, codex_size="1024x1536", timeout=600)
print(f"[gen] returned mode={img.mode} size={img.size}", file=sys.stderr)
img.save(out)
print(f"[gen] saved {out}", file=sys.stderr)

# Report alpha so we know whether to colorkey instead.
if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
    rgba = img.convert("RGBA")
    alpha = rgba.getchannel("A")
    lo, hi = alpha.getextrema()
    print(f"[gen] alpha extrema=({lo},{hi}) -> {'HAS transparency' if lo < 250 else 'alpha is opaque'}", file=sys.stderr)
else:
    print("[gen] NO alpha channel (opaque) -> will need chroma/colorkey fallback", file=sys.stderr)

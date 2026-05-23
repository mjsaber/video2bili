"""Polish pass for the locked 1280x720 YouTube thumbnail layout.

Adds the two finishing touches that `video2yt-thumbnail` does not handle:
1. Radial vignette darkening the corners ~30% to focus the eye toward center.
2. The 8-char two-tier title — primary 4 chars (white, large) over a secondary
   4-char payoff (saturated gold, smaller) — drawn into the left half.

The CLI's `--title` only supports single-row text. This script is invoked AFTER
`video2yt-thumbnail` and operates on its output PNG.

The visual params (font sizes, positions, colors, stroke widths) are locked
2026-05-10 on the `zaige` project. Do NOT tweak them per-project — the whole
point is a consistent thumbnail brand. See
`docs/superpowers/specs/2026-04-18-video-production-workflow.md` Bonus
section.

Usage:
    uv run python scripts/thumbnail_polish.py \\
        --input  output/<project>/thumbnail_pre_polish.png \\
        --output output/<project>/thumbnail.png \\
        --primary   "宰割亡靈" \\
        --secondary "兩千攻擊"
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_INDEX = 1  # W6 Bold


def apply_vignette(img: Image.Image, strength: float = 0.30) -> Image.Image:
    W, H = img.size
    mask = Image.new("L", (W, H), 255)
    md = ImageDraw.Draw(mask)
    cx, cy = W / 2, H / 2
    max_r = math.hypot(cx, cy)
    steps = 80
    for i in range(steps, 0, -1):
        r = max_r * (i / steps)
        falloff = (i / steps) ** 2.2
        val = int(255 * (1.0 - strength * (1.0 - falloff)))
        md.ellipse((cx - r, cy - r, cx + r, cy + r), fill=val)
    mask = mask.filter(ImageFilter.GaussianBlur(40))
    r, g, b, a = img.split()
    rgb = Image.merge("RGB", (r, g, b))
    rgb = Image.composite(rgb, Image.new("RGB", (W, H), (0, 0, 0)), mask)
    return Image.merge("RGBA", (*rgb.split(), a))


def render_row(
    canvas_size: tuple[int, int],
    text: str,
    font_size: int,
    x: int,
    y: int,
    color: tuple[int, int, int, int],
    stroke_color: tuple[int, int, int, int],
    stroke_width: int,
    char_gap: int,
    shadow_offset: tuple[int, int],
    shadow_blur: int,
    shadow_alpha: int,
) -> tuple[Image.Image, Image.Image]:
    W, H = canvas_size
    font = ImageFont.truetype(FONT_PATH, font_size, index=FONT_INDEX)
    sb = font.getbbox("国")
    ch_w = sb[2] - sb[0]

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for ci, ch in enumerate(text):
        cx_ = x + ci * (ch_w + char_gap)
        sd.text(
            (cx_ + shadow_offset[0] - sb[0], y + shadow_offset[1] - sb[1]),
            ch, font=font, fill=(0, 0, 0, shadow_alpha),
        )
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))

    text_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    for ci, ch in enumerate(text):
        cx_ = x + ci * (ch_w + char_gap)
        td.text(
            (cx_ - sb[0], y - sb[1]),
            ch, font=font, fill=color,
            stroke_width=stroke_width, stroke_fill=stroke_color,
        )
    return shadow, text_layer


def polish(src: Path, dst: Path, primary: str, secondary: str) -> None:
    if len(primary) != 4 or len(secondary) != 4:
        raise ValueError(
            f"primary and secondary must each be 4 CJK chars (got "
            f"{len(primary)}+{len(secondary)})"
        )

    img = Image.open(src).convert("RGBA")
    img = apply_vignette(img, strength=0.30)

    sl1, tl1 = render_row(
        canvas_size=img.size, text=primary,
        font_size=180, x=20, y=140,
        color=(255, 255, 255, 255),
        stroke_color=(0, 0, 0, 255),
        stroke_width=16, char_gap=-10,
        shadow_offset=(10, 14), shadow_blur=12, shadow_alpha=235,
    )
    img = Image.alpha_composite(img, sl1)
    img = Image.alpha_composite(img, tl1)

    sl2, tl2 = render_row(
        canvas_size=img.size, text=secondary,
        font_size=130, x=30, y=380,
        color=(245, 195, 75, 255),
        stroke_color=(70, 25, 0, 255),
        stroke_width=12, char_gap=-6,
        shadow_offset=(7, 10), shadow_blur=10, shadow_alpha=220,
    )
    img = Image.alpha_composite(img, sl2)
    img = Image.alpha_composite(img, tl2)

    dst.parent.mkdir(parents=True, exist_ok=True)
    img.save(dst)
    print(f"[polish] wrote {dst} (two-tier 8-char)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path,
                    help="thumbnail_pre_polish.png from video2yt-thumbnail")
    ap.add_argument("--output", required=True, type=Path,
                    help="final thumbnail.png path")
    ap.add_argument("--primary", required=True,
                    help="4-char primary row (流派 name)")
    ap.add_argument("--secondary", required=True,
                    help="4-char secondary payoff row")
    args = ap.parse_args()
    polish(args.input, args.output, args.primary, args.secondary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Warm-tavern YouTube thumbnail compositor (1280x720).

Single self-contained pass that takes the raw pieces — generated background,
card art, channel logo, and the 女老板 mascot — and produces the final cover:

  1. lift the background mid-tones + warm tint  (kill the near-black gloom)
  2. radial vignette darkening the EDGES (center stays bright)
  3. card art, tilted, with a warm glow — the credibility hero, center-right
  4. warm-charcoal LEFT gradient scrim — a legible white-text anchor, not pure black
  5. 女老板 mascot bottom-right with a warm rim + halo — the bright brand focal point
  6. logo top-left
  7. 8-char two-tier title — primary 4 chars (white) over secondary 4 chars (gold)

Locked 2026-06-07 (supersedes the 2026-05-10 dark layout that ran the base
`video2yt-thumbnail` render then a vignette+title-only polish). Do NOT tweak the
visual constants per-project — a consistent thumbnail brand is the whole point.
See the `Bonus — YouTube thumbnail` step in
`docs/superpowers/specs/2026-04-18-video-production-workflow.md`.

Usage:
    uv run python scripts/thumbnail_polish.py \\
        --bg        output/<project>/thumbnail_bg.png \\
        --card      assets/cards/<slug>_zhTW_bgs_512.png \\
        --output    output/<project>/thumbnail.png \\
        --primary   "雙重縫針" \\
        --secondary "百萬身材"
"""
from __future__ import annotations

import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

W, H = 1280, 720
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_INDEX = 1  # W6 Bold

DEFAULT_LOGO = Path("assets/hsbg_logo.png")
DEFAULT_MASCOT = Path("assets/cta/src/mascot_raw.png")

# --- locked visual constants ---
BG_BRIGHT = 1.12
BG_COLOR = 1.18
WARM_TINT = (255, 170, 70)
WARM_TINT_ALPHA = 0.08
VIGNETTE = 0.22

CARD_H = 668            # big card = impact; bleeds toward right/bottom edges
CARD_TILT = -8.0
CARD_TOP = 34
CARD_RIGHT_INSET = 64   # px from right edge to the card's right side

MASCOT_H = 372          # corner host — small enough to yield space to the card
MASCOT_RIGHT_INSET = -8  # negative = bleed slightly past the right edge
MASCOT_BOTTOM_BLEED = 12  # px feet extend past the bottom
MASCOT_CROP_LEFT = 0.06   # crop the outer arm so she hugs the corner
MASCOT_HALO_PAD = 60

SCRIM_FILL = (30, 24, 18)  # warm charcoal, NOT pure black
SCRIM_ALPHA0 = 210
SCRIM_WIDTH = 600

LOGO_W = 180
LOGO_MARGIN = 16


def lift_warm(bg: Image.Image) -> Image.Image:
    """Raise mid-tones + saturation and lay a faint warm tint over the bg."""
    bg = ImageEnhance.Brightness(bg).enhance(BG_BRIGHT)
    bg = ImageEnhance.Color(bg).enhance(BG_COLOR)
    tint = Image.new("RGBA", bg.size, (*WARM_TINT, int(255 * WARM_TINT_ALPHA)))
    return Image.alpha_composite(bg.convert("RGBA"), tint)


def apply_vignette(img: Image.Image, strength: float) -> Image.Image:
    """Darken the EDGES (center stays ~255). Concentric ellipses are drawn
    largest-first, so the smallest (center) wins last; ``i/80`` tracks the
    pixel-radius fraction, so ``strength * (i/80)**2.2`` darkens with radius."""
    mask = Image.new("L", (W, H), 255)
    md = ImageDraw.Draw(mask)
    cx, cy = W / 2, H / 2
    max_r = math.hypot(cx, cy)
    for i in range(80, 0, -1):
        r = max_r * (i / 80)
        falloff = (i / 80) ** 2.2
        val = int(255 * (1.0 - strength * falloff))
        md.ellipse((cx - r, cy - r, cx + r, cy + r), fill=val)
    mask = mask.filter(ImageFilter.GaussianBlur(40))
    r, g, b, a = img.split()
    rgb = Image.composite(Image.merge("RGB", (r, g, b)),
                          Image.new("RGB", (W, H), (0, 0, 0)), mask)
    return Image.merge("RGBA", (*rgb.split(), a))


def left_scrim() -> Image.Image:
    """Warm-charcoal gradient over the left text zone (alpha SCRIM_ALPHA0→0)."""
    xs = np.arange(W, dtype=float)
    a = np.clip(1.0 - xs / SCRIM_WIDTH, 0, 1) * SCRIM_ALPHA0
    alpha = np.tile(a.astype(np.uint8), (H, 1))
    layer = Image.new("RGBA", (W, H), (*SCRIM_FILL, 0))
    layer.putalpha(Image.fromarray(alpha, "L"))
    return layer


def paste_card(canvas: Image.Image, card_path: Path) -> None:
    card = Image.open(card_path).convert("RGBA")
    sw, sh = card.size
    card = card.resize((round(sw * CARD_H / sh), CARD_H), Image.LANCZOS)
    card = card.rotate(CARD_TILT, resample=Image.BICUBIC, expand=True)
    cw, ch = card.size
    glow = Image.new("RGBA", (cw + 80, ch + 80), (0, 0, 0, 0))
    glow.paste((255, 200, 90, 200), (40, 40), card.split()[3])
    glow = glow.filter(ImageFilter.GaussianBlur(26))
    x = W - cw - CARD_RIGHT_INSET
    y = CARD_TOP
    canvas.alpha_composite(glow, (x - 40, y - 40))
    canvas.alpha_composite(card, (x, y))


def litho_mascot(mascot_path: Path) -> Image.Image:
    """Mascot with a warm halo + gold rim so she reads as lit, not pasted."""
    m = Image.open(mascot_path).convert("RGBA")
    sw, sh = m.size
    if MASCOT_CROP_LEFT > 0:
        m = m.crop((int(sw * MASCOT_CROP_LEFT), 0, sw, sh))
        sw, sh = m.size
    m = m.resize((round(sw * MASCOT_H / sh), MASCOT_H), Image.LANCZOS)
    cw, ch = m.size
    alpha = m.split()[3]

    pad = MASCOT_HALO_PAD
    big = (cw + pad * 2, ch + pad * 2)
    halo = Image.new("RGBA", big, (0, 0, 0, 0))
    halo.paste((255, 180, 90, 255), (pad, pad), alpha)
    halo = halo.filter(ImageFilter.GaussianBlur(22))
    halo.putalpha(halo.split()[3].point(lambda v: int(v * 0.40)))

    dil = alpha.filter(ImageFilter.MaxFilter(7))
    ring = Image.fromarray(
        np.clip(np.asarray(dil).astype(int) - np.asarray(alpha).astype(int),
                0, 255).astype(np.uint8), "L")
    rim = Image.new("RGBA", big, (0, 0, 0, 0))
    rim.paste((255, 205, 110, 255), (pad, pad), ring)
    rim = rim.filter(ImageFilter.GaussianBlur(3))

    out = Image.new("RGBA", big, (0, 0, 0, 0))
    out.alpha_composite(halo)
    out.alpha_composite(rim)
    out.alpha_composite(m, (pad, pad))
    return out


def render_title_row(canvas, text, font_size, x, y, color, stroke_color,
                     stroke_width, char_gap, shadow_off, shadow_blur,
                     shadow_alpha) -> None:
    font = ImageFont.truetype(FONT_PATH, font_size, index=FONT_INDEX)
    sb = font.getbbox("国")
    ch_w = sb[2] - sb[0]
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for ci, ch in enumerate(text):
        cx_ = x + ci * (ch_w + char_gap)
        sd.text((cx_ + shadow_off[0] - sb[0], y + shadow_off[1] - sb[1]),
                ch, font=font, fill=(0, 0, 0, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas.alpha_composite(shadow)
    tl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(tl)
    for ci, ch in enumerate(text):
        cx_ = x + ci * (ch_w + char_gap)
        td.text((cx_ - sb[0], y - sb[1]), ch, font=font, fill=color,
                stroke_width=stroke_width, stroke_fill=stroke_color)
    canvas.alpha_composite(tl)


def build(bg_path: Path, card_path: Path, logo_path: Path,
          mascot_path: Path | None, primary: str, secondary: str) -> Image.Image:
    bg = Image.open(bg_path).convert("RGBA").resize((W, H), Image.LANCZOS)
    canvas = lift_warm(bg)
    canvas = apply_vignette(canvas, VIGNETTE)
    paste_card(canvas, card_path)
    canvas.alpha_composite(left_scrim())

    if mascot_path is not None:
        mascot = litho_mascot(mascot_path)
        mw, mh = mascot.size
        mx = W - mw + MASCOT_HALO_PAD - MASCOT_RIGHT_INSET
        my = H - mh + MASCOT_HALO_PAD + MASCOT_BOTTOM_BLEED
        canvas.alpha_composite(mascot, (mx, my))

    logo = Image.open(logo_path).convert("RGBA")
    logo = logo.resize((LOGO_W, round(logo.size[1] * LOGO_W / logo.size[0])),
                       Image.LANCZOS)
    canvas.alpha_composite(logo, (LOGO_MARGIN, LOGO_MARGIN))

    render_title_row(canvas, primary, 180, 20, 140, (255, 255, 255, 255),
                     (0, 0, 0, 255), 16, -10, (10, 14), 12, 235)
    render_title_row(canvas, secondary, 130, 30, 380, (245, 195, 75, 255),
                     (70, 25, 0, 255), 12, -6, (7, 10), 10, 220)
    return canvas.convert("RGB")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bg", required=True, type=Path,
                    help="background image (thumbnail_bg.png from video2yt-image)")
    ap.add_argument("--card", required=True, type=Path,
                    help="card art PNG (zhTW BGS art)")
    ap.add_argument("--output", required=True, type=Path, help="final thumbnail.png")
    ap.add_argument("--primary", required=True, help="4-char primary row (流派 name)")
    ap.add_argument("--secondary", required=True, help="4-char secondary payoff row")
    ap.add_argument("--logo", type=Path, default=DEFAULT_LOGO,
                    help=f"channel logo (default: {DEFAULT_LOGO})")
    ap.add_argument("--mascot", type=Path, default=DEFAULT_MASCOT,
                    help=f"女老板 mascot PNG with alpha (default: {DEFAULT_MASCOT})")
    ap.add_argument("--no-mascot", action="store_true",
                    help="omit the mascot (rare; brand consistency wants her in)")
    args = ap.parse_args()

    if len(args.primary) != 4 or len(args.secondary) != 4:
        raise ValueError(
            f"primary and secondary must each be 4 CJK chars (got "
            f"{len(args.primary)}+{len(args.secondary)})")

    mascot = None if args.no_mascot else args.mascot
    img = build(args.bg, args.card, args.logo, mascot, args.primary, args.secondary)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    print(f"[polish] wrote {args.output} "
          f"(warm-tavern{'' if args.no_mascot else ' + mascot'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

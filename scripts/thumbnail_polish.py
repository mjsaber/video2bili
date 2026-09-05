"""YouTube thumbnail compositor (1280x720), Japanese anime pencil sketch by default.

Use a genuinely generated sketch background and matching transparent mascot.
The compositor preserves paper tones, adds dark ink titles and subtle shadows,
and keeps official card art recognizable. --style warm-tavern selects the legacy
amber palette, glow and dark scrim. Layout (brand/payoff) is independent of style.

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
import hashlib
import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from video2yt.visual_style import DEFAULT_STYLE, STYLES, default_mascot

W, H = 1280, 720
FONT_PATH = "/System/Library/Fonts/Hiragino Sans GB.ttc"
FONT_INDEX = 1  # W6 Bold

DEFAULT_LOGO = Path("assets/hsbg_logo.png")
DEFAULT_MASCOT = default_mascot(DEFAULT_STYLE)
PAPER = (252, 250, 245, 255)
INK = (40, 44, 49, 255)
ACCENT = (58, 108, 100, 255)  # Deep sage ink complements the fresh pastel background.

# --- legacy warm-tavern constants ---
BG_BRIGHT = 1.12
BG_COLOR = 1.18
WARM_TINT = (255, 170, 70)
WARM_TINT_ALPHA = 0.08
VIGNETTE = 0.22

CARD_H = 668            # big card = impact; bleeds toward right/bottom edges
CARD_TILT = -8.0
CARD_TOP = 34
CARD_RIGHT_INSET = 64   # px from right edge to the card's right side

# dual-card fan (--card2): bottoms overlap, tops fan apart so both art
# crops stay visible; the cards' text boxes may squeeze each other (OK per
# user, comeback 2026-07-19). The combined image then rides the normal
# CARD_H/CARD_TILT pipeline.
FAN_BACK_TILT = 22      # ccw — back card's top leans left
FAN_FRONT_TILT = -10    # cw — front card's top leans right
FAN_OVERLAP = 0.26      # front card starts at this fraction of back width
FAN_FRONT_DROP = 30     # px the front card sits below the back card

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
TEXT_RIGHT = 720  # text ink, including its stroke, must stay left of this edge
MIN_TITLE_SIZE = 32


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


def left_scrim(style: str = "warm-tavern") -> Image.Image:
    """Paper or charcoal gradient behind titles, selected independently of layout."""
    xs = np.arange(W, dtype=float)
    sketch = style == "anime-sketch"
    width = TEXT_RIGHT + 120 if sketch else SCRIM_WIDTH
    a = np.clip(1.0 - xs / width, 0, 1) * (160 if sketch else SCRIM_ALPHA0)
    alpha = np.tile(a.astype(np.uint8), (H, 1))
    layer = Image.new("RGBA", (W, H), (*(PAPER[:3] if sketch else SCRIM_FILL), 0))
    layer.putalpha(Image.fromarray(alpha, "L"))
    return layer


def combine_cards_fan(back_path: Path, front_path: Path) -> Image.Image:
    """Fan two card renders: bottoms overlapping, tops spread apart."""
    back = Image.open(back_path).convert("RGBA")
    front = Image.open(front_path).convert("RGBA")
    b = back.rotate(FAN_BACK_TILT, expand=True, resample=Image.BICUBIC)
    f = front.rotate(FAN_FRONT_TILT, expand=True, resample=Image.BICUBIC)
    overlap_x = int(b.width * FAN_OVERLAP)
    w = max(b.width, overlap_x + f.width)
    baseline = max(b.height, f.height)
    h = baseline + FAN_FRONT_DROP
    fan = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    fan.alpha_composite(b, (0, baseline - b.height))
    fan.alpha_composite(f, (overlap_x, baseline - f.height + FAN_FRONT_DROP))
    return fan.crop(fan.getbbox())


def paste_card(canvas: Image.Image, card_path: Path,
               card2_path: Path | None = None, style: str = DEFAULT_STYLE) -> None:
    if card2_path is not None:
        card = combine_cards_fan(card_path, card2_path)
    else:
        card = Image.open(card_path).convert("RGBA")
    sw, sh = card.size
    card = card.resize((round(sw * CARD_H / sh), CARD_H), Image.LANCZOS)
    card = card.rotate(CARD_TILT, resample=Image.BICUBIC, expand=True)
    cw, ch = card.size
    glow = Image.new("RGBA", (cw + 80, ch + 80), (0, 0, 0, 0))
    sketch = style == "anime-sketch"
    glow.paste((40, 44, 49, 70) if sketch else (255, 200, 90, 200),
               (40, 40), card.split()[3])
    glow = glow.filter(ImageFilter.GaussianBlur(8 if sketch else 26))
    x = W - cw - CARD_RIGHT_INSET
    y = CARD_TOP
    canvas.alpha_composite(glow, (x - 40, y - 40))
    canvas.alpha_composite(card, (x, y))


def litho_mascot(mascot_path: Path, style: str = DEFAULT_STYLE) -> Image.Image:
    """Size the mascot; add a warm halo and gold rim only in the legacy theme."""
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
    if style == "anime-sketch":
        out = Image.new("RGBA", big, (0, 0, 0, 0))
        out.alpha_composite(m, (pad, pad))
        return out
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


@dataclass
class TitleRow:
    font: ImageFont.FreeTypeFont
    bbox: tuple[int, int, int, int]
    offsets: list[float]
    stroke_width: int


def fit_title_row(text: str, font_size: int, max_width: int,
                  stroke_width: int, char_gap: int) -> TitleRow:
    """Fit actual glyph bounds plus stroke; never squeeze below a readable size."""
    if not text.strip() or "\n" in text or "\r" in text:
        raise ValueError("title rows must be nonempty single lines")
    for size in range(font_size, MIN_TITLE_SIZE - 1, -1):
        font = ImageFont.truetype(FONT_PATH, size, index=FONT_INDEX)
        stroke = max(1, round(stroke_width * size / font_size))
        gap = char_gap * size / font_size
        glyphs = {ch: (font.getbbox(ch, stroke_width=stroke), font.getlength(ch))
                  for ch in set(text)}
        offsets = []
        bounds = []
        cursor = 0.0
        for ch in text:
            bbox, advance = glyphs[ch]
            offsets.append(cursor)
            bounds.append((cursor + bbox[0], bbox[1], cursor + bbox[2], bbox[3]))
            cursor += advance + gap
        bbox = (math.floor(min(b[0] for b in bounds)), min(b[1] for b in bounds),
                math.ceil(max(b[2] for b in bounds)), max(b[3] for b in bounds))
        if bbox[2] - bbox[0] <= max_width:
            return TitleRow(font, bbox, offsets, stroke)
    raise ValueError(f"title row cannot fit {max_width}px at minimum font size {MIN_TITLE_SIZE}: {text!r}")


def render_title_row(canvas, text, font_size, x, y, color, stroke_color,
                     stroke_width, char_gap, shadow_off, shadow_blur,
                     shadow_alpha, *, max_width=None) -> None:
    width = TEXT_RIGHT - x if max_width is None else min(max_width, TEXT_RIGHT - x)
    row = fit_title_row(text, font_size, width, stroke_width, char_gap)
    font, sb = row.font, row.bbox
    if x < 0 or y < 0 or y + sb[3] - sb[1] > H:
        raise ValueError("title row exceeds the thumbnail text area")
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    for ci, ch in enumerate(text):
        cx_ = x + row.offsets[ci]
        sd.text((cx_ + shadow_off[0] - sb[0], y + shadow_off[1] - sb[1]),
                ch, font=font, fill=(0, 0, 0, shadow_alpha))
    shadow = shadow.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas.alpha_composite(shadow)
    tl = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    td = ImageDraw.Draw(tl)
    for ci, ch in enumerate(text):
        cx_ = x + row.offsets[ci]
        td.text((cx_ - sb[0], y - sb[1]), ch, font=font, fill=color,
                stroke_width=row.stroke_width, stroke_fill=stroke_color)
    canvas.alpha_composite(tl)


def build(bg_path: Path, card_path: Path, logo_path: Path | None,
          mascot_path: Path | None, primary: str, secondary: str,
          tertiary: str | None = None,
          card2_path: Path | None = None, layout: str = "brand",
          style: str = DEFAULT_STYLE) -> Image.Image:
    if layout not in ("brand", "payoff"):
        raise ValueError(f"unknown thumbnail layout: {layout}")
    if style not in STYLES:
        raise ValueError(f"unknown thumbnail style: {style}")
    sketch = style == "anime-sketch"
    bg = Image.open(bg_path).convert("RGBA").resize((W, H), Image.LANCZOS)
    canvas = bg if sketch else apply_vignette(lift_warm(bg), VIGNETTE)
    paste_card(canvas, card_path, card2_path, style=style)
    canvas.alpha_composite(left_scrim(style))

    if mascot_path is not None:
        mascot = litho_mascot(mascot_path, style=style)
        mw, mh = mascot.size
        mx = W - mw + MASCOT_HALO_PAD - MASCOT_RIGHT_INSET
        my = H - mh + MASCOT_HALO_PAD + MASCOT_BOTTOM_BLEED
        canvas.alpha_composite(mascot, (mx, my))

    if logo_path is not None:
        logo = Image.open(logo_path).convert("RGBA")
        logo = logo.resize((LOGO_W, round(logo.size[1] * LOGO_W / logo.size[0])),
                           Image.LANCZOS)
        canvas.alpha_composite(logo, (LOGO_MARGIN, LOGO_MARGIN))

    def title_row(canvas, text, font_size, x, y, color, stroke_color,
                  stroke_width, char_gap, shadow_off, shadow_blur, shadow_alpha):
        if sketch:
            color = INK if color == (255, 255, 255, 255) else ACCENT
            stroke_color, stroke_width = PAPER, 3
            shadow_off, shadow_blur, shadow_alpha = (0, 0), 0, 0
        render_title_row(canvas, text, font_size, x, y, color, stroke_color,
                         stroke_width, char_gap, shadow_off, shadow_blur, shadow_alpha)

    if layout == "payoff":
        payoff = fit_title_row(secondary, 200, TEXT_RIGHT - 20, 16, -8)
        topic_size = max(MIN_TITLE_SIZE, min(112, int(payoff.font.size * 0.68)))
        title_row(canvas, secondary, payoff.font.size, 20, 150, (245, 195, 75, 255),
                         (70, 25, 0, 255), payoff.stroke_width, -8, (10, 14), 12, 235)
        title_row(canvas, primary, topic_size, 30, 410, (255, 255, 255, 255),
                         (0, 0, 0, 255), 10, -5, (7, 10), 10, 220)
        if tertiary is not None:
            title_row(canvas, tertiary, min(96, topic_size), 30, 560,
                             (245, 195, 75, 255), (70, 25, 0, 255), 8, -4, (7, 10), 10, 220)
        return canvas.convert("RGB")

    title_row(canvas, primary, 180, 20, 140, (255, 255, 255, 255),
                     (0, 0, 0, 255), 16, -10, (10, 14), 12, 235)
    if tertiary is None:
        title_row(canvas, secondary, 130, 30, 380, (245, 195, 75, 255),
                         (70, 25, 0, 255), 12, -6, (7, 10), 10, 220)
    else:
        # compact 3-row variant: secondary+tertiary share the gold payoff style
        title_row(canvas, secondary, 130, 30, 355, (245, 195, 75, 255),
                         (70, 25, 0, 255), 12, -6, (7, 10), 10, 220)
        title_row(canvas, tertiary, 130, 30, 545, (245, 195, 75, 255),
                         (70, 25, 0, 255), 12, -6, (7, 10), 10, 220)
    return canvas.convert("RGB")


def asset_record(path: Path | None) -> dict | None:
    if path is None:
        return None
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": str(path.resolve()), "sha256": digest.hexdigest()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--bg", required=True, type=Path,
                    help="background image (thumbnail_bg.png from video2yt-image)")
    ap.add_argument("--card", required=True, type=Path,
                    help="card art PNG (zhTW BGS art)")
    ap.add_argument("--card2", type=Path, default=None,
                    help="optional second card: fans behind --card2 front card "
                         "(--card = back/left, --card2 = front/right)")
    ap.add_argument("--output", required=True, type=Path, help="final thumbnail.png")
    ap.add_argument("--primary", required=True, help="topic row (auto-fitted to the left text area)")
    ap.add_argument("--secondary", required=True, help="payoff row; dominant in payoff layout")
    ap.add_argument("--tertiary", default=None,
                    help="optional auto-fitted third row")
    ap.add_argument("--style", choices=STYLES, default=DEFAULT_STYLE,
                    help="Visual theme (default: anime-sketch; requires sketch source artwork)")
    ap.add_argument("--layout", choices=("brand", "payoff"), default="brand")
    ap.add_argument("--logo", type=Path, default=DEFAULT_LOGO,
                    help=f"channel logo (default: {DEFAULT_LOGO})")
    ap.add_argument("--mascot", type=Path,
                    help="女老板 PNG with alpha (default: matching the selected style)")
    ap.add_argument("--no-mascot", action="store_true",
                    help="omit the mascot (rare; brand consistency wants her in)")
    ap.add_argument("--no-logo", action="store_true", help="omit the channel logo")
    ap.add_argument("--variant-id", help="local variant identifier; requires title and hypothesis")
    ap.add_argument("--video-title", help="candidate YouTube title for the local packaging variant")
    ap.add_argument("--hypothesis", help="what this variant is intended to test")
    args = ap.parse_args(argv)
    variant_fields = (args.variant_id, args.video_title, args.hypothesis)
    variant = any(value is not None for value in variant_fields)
    if variant and not all(value is not None and value.strip() for value in variant_fields):
        raise ValueError("--variant-id, --video-title, and --hypothesis are required together and must be nonempty")
    manifest_path = args.output.with_suffix(".variant.json")
    mobile_path = args.output.with_name(f"{args.output.stem}_mobile.png")
    if variant:
        for destination in (args.output, manifest_path, mobile_path):
            if destination.exists():
                raise FileExistsError(f"variant output already exists; use a new output name: {destination}")

    mascot = None if args.no_mascot else (args.mascot or default_mascot(args.style))
    logo = None if args.no_logo else args.logo
    img = build(args.bg, args.card, logo, mascot, args.primary, args.secondary,
                args.tertiary, card2_path=args.card2, layout=args.layout, style=args.style)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    img.save(args.output)
    if variant:
        img.resize((320, 180), Image.LANCZOS).save(mobile_path)
        manifest = {
            "id": args.variant_id, "title": args.video_title, "hypothesis": args.hypothesis,
            "layout": args.layout, "style": args.style,
            "texts": {"primary": args.primary, "secondary": args.secondary, "tertiary": args.tertiary},
            "assets": {name: asset_record(path) for name, path in {
                "background": args.bg, "card": args.card, "card2": args.card2,
                "logo": logo, "mascot": mascot,
            }.items()},
            "thumbnail_path": str(args.output.resolve()),
            "thumbnail_sha256": asset_record(args.output)["sha256"],
            "mobile_preview_path": str(mobile_path.resolve()),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending_manual_studio_experiment",
        }
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"[polish] wrote {args.output} "
          f"({args.style}{'' if args.no_mascot else ' + mascot'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

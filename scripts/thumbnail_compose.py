"""Compose a YouTube thumbnail: background + logo + title + (optional) tilted card.

Three orientations:
  - horizontal-bottom:  title across the bottom (legacy)
  - vertical-left:      title stacked vertically on the left (legacy)
  - card-tilt-right:    NEW DEFAULT — logo top-left, season top-right,
                        vertical title with drop-shadow on the left,
                        tilted card art on the right.

Usage (card-tilt-right, the recommended layout for new projects):
    uv run python scripts/thumbnail_compose.py \\
        --bg          output/<project>/thumbnail_bg.png \\
        --logo        assets/hsbg_logo.png \\
        --card        assets/cards/<slug>_512.png \\
        --title       "<vertical-title>" \\
        --season      "S13" \\
        --orientation card-tilt-right \\
        --output      output/<project>/thumbnail.png
"""
from __future__ import annotations

import argparse
import math
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

DEFAULT_FONT = "/System/Library/Fonts/Hiragino Sans GB.ttc"
DEFAULT_FONT_INDEX = 1  # 0=W3 (Regular), 1=W6 (Bold)


def _draw_horizontal_bottom(
    draw: ImageDraw.ImageDraw,
    title: str,
    font: ImageFont.FreeTypeFont,
    *,
    target_w: int,
    target_h: int,
    bottom_margin: int,
    color: tuple[int, int, int],
    stroke_color: tuple[int, int, int],
    stroke_width: int,
) -> tuple[int, int]:
    bbox = draw.textbbox((0, 0), title, font=font, stroke_width=stroke_width)
    text_w = bbox[2] - bbox[0]
    text_h = bbox[3] - bbox[1]
    x = (target_w - text_w) // 2 - bbox[0]
    y = target_h - text_h - bottom_margin - bbox[1]
    draw.text((x, y), title, font=font, fill=color, stroke_width=stroke_width, stroke_fill=stroke_color)
    return text_w, text_h


def _tokenize_for_vertical(title: str) -> list[str]:
    """Split title into vertical-stacked tokens.

    Consecutive ASCII letters/digits cluster into one horizontal token (e.g. "S13").
    Each CJK character is its own token. Spaces are dropped.
    """
    tokens: list[str] = []
    buf = ""
    for ch in title:
        if ch.isspace():
            if buf:
                tokens.append(buf)
                buf = ""
            continue
        if ch.isascii() and (ch.isalnum() or ch in "._-+/"):
            buf += ch
        else:
            if buf:
                tokens.append(buf)
                buf = ""
            tokens.append(ch)
    if buf:
        tokens.append(buf)
    return tokens


def _auto_shrink_font_for_vertical(
    *,
    font_path: str,
    font_index: int,
    requested_size: int,
    n_tokens: int,
    available_h: int,
    line_spacing: float,
    min_size: int = 32,
) -> int:
    """Return a font size whose stacked rows fit within `available_h`.

    Vertical title silently overflowed in the legacy `vertical-left` mode (see spec
    tech-debt). This helper keeps the requested size when possible and shrinks
    in 4-pt steps otherwise. We use a CJK glyph as the row-height baseline so a
    short ASCII token doesn't underestimate stack height.
    """
    size = requested_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size, index=font_index)
        bbox = font.getbbox("国")
        row_h = int((bbox[3] - bbox[1]) * line_spacing)
        if row_h * n_tokens <= available_h:
            return size
        size -= 4
    return size


def _draw_vertical_block(
    draw: ImageDraw.ImageDraw,
    title: str,
    font: ImageFont.FreeTypeFont,
    *,
    target_w: int,
    target_h: int,
    anchor_x_ratio: float,
    line_spacing: float,
    color: tuple[int, int, int],
    stroke_color: tuple[int, int, int],
    stroke_width: int,
) -> tuple[int, int]:
    """Stack tokens (S13 = one row, 最 = one row, ...) vertically.

    The text block is horizontally centered on `anchor_x_ratio * target_w`
    and vertically centered in the canvas.
    """
    tokens = _tokenize_for_vertical(title)
    if not tokens:
        return 0, 0

    sample_bbox = draw.textbbox((0, 0), "国", font=font, stroke_width=stroke_width)
    row_h = int((sample_bbox[3] - sample_bbox[1]) * line_spacing)
    total_h = row_h * len(tokens)
    start_y = (target_h - total_h) // 2

    anchor_x = int(target_w * anchor_x_ratio)
    max_w = 0
    for i, tok in enumerate(tokens):
        bbox = draw.textbbox((0, 0), tok, font=font, stroke_width=stroke_width)
        tok_w = bbox[2] - bbox[0]
        max_w = max(max_w, tok_w)
        x = anchor_x - tok_w // 2 - bbox[0]
        y = start_y + i * row_h - bbox[1]
        draw.text((x, y), tok, font=font, fill=color, stroke_width=stroke_width, stroke_fill=stroke_color)
    return max_w, total_h


def _draw_vertical_block_dropshadow(
    canvas: Image.Image,  # RGBA
    title: str,
    font: ImageFont.FreeTypeFont,
    *,
    anchor_x: int,
    top_y: int,
    line_gap: int,
    color: tuple[int, int, int],
    shadow_offset: tuple[int, int],
    shadow_blur: int,
    shadow_fill: tuple[int, int, int, int],
) -> tuple[int, int]:
    """Vertical title with a soft dark drop-shadow (cleaner than a coloured stroke).

    Used by the `card-tilt-right` orientation. Two passes:
      1. blurred dark glyph on a separate RGBA layer, alpha-composited.
      2. clean coloured glyph on top — no stroke, sharp edges.
    """
    tokens = _tokenize_for_vertical(title)
    if not tokens:
        return 0, 0

    sample_bbox = font.getbbox("国")
    glyph_h = sample_bbox[3] - sample_bbox[1]
    row_h = glyph_h + line_gap

    # Pass 1: shadow on a separate transparent layer, then blur.
    shadow_layer = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sx, sy = shadow_offset
    max_w = 0
    for i, tok in enumerate(tokens):
        bbox = font.getbbox(tok)
        tok_w = bbox[2] - bbox[0]
        max_w = max(max_w, tok_w)
        x = anchor_x - tok_w // 2 - bbox[0] + sx
        y = top_y + i * row_h - bbox[1] + sy
        sd.text((x, y), tok, font=font, fill=shadow_fill)
    shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))
    canvas.alpha_composite(shadow_layer)

    # Pass 2: clean glyph.
    draw = ImageDraw.Draw(canvas)
    for i, tok in enumerate(tokens):
        bbox = font.getbbox(tok)
        tok_w = bbox[2] - bbox[0]
        x = anchor_x - tok_w // 2 - bbox[0]
        y = top_y + i * row_h - bbox[1]
        draw.text((x, y), tok, font=font, fill=color)

    total_h = row_h * len(tokens)
    return max_w, total_h


def _paste_tilted_card(
    canvas: Image.Image,  # RGBA mutable
    card_path: Path,
    *,
    target_w: int,
    target_h: int,
    card_target_h: int,
    card_tilt_deg: float,
    card_right_inset: int,
    card_glow_expand: int,
    shared_top_y: int,
) -> tuple[int, int]:
    """Paste a tilted card on the right with a soft dark drop-shadow.

    The visible TL corner of the rotated card is anchored to `shared_top_y` so it
    aligns with the title top. PIL rotates CCW around the bbox center; we compute
    the offset from bbox-TL to the original TL analytically.

    Returns the (card_x, card_y) used so callers can log layout details.
    """
    card = Image.open(card_path).convert("RGBA")
    sw, sh = card.size
    scale = card_target_h / sh
    card = card.resize((int(sw * scale), card_target_h), Image.LANCZOS)
    pre_w, pre_h = card.size  # before rotation
    card_rot = card.rotate(card_tilt_deg, resample=Image.BICUBIC, expand=True)
    cw, ch = card_rot.size

    # Compute where the original TL corner lands inside the rotated bbox.
    # PIL rotate() rotates by `angle` degrees CCW around the image center.
    theta = math.radians(card_tilt_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    tl_rot_y = -pre_w / 2 * sin_t + -pre_h / 2 * cos_t
    tl_offset_y = tl_rot_y + ch / 2

    # Soft drop-shadow behind the rotated card.
    shadow = Image.new("RGBA", (cw + card_glow_expand * 4, ch + card_glow_expand * 4), (0, 0, 0, 0))
    shadow_alpha = card_rot.split()[3].point(lambda v: 180 if v > 0 else 0)
    shadow.paste((0, 0, 0, 180), (card_glow_expand * 2, card_glow_expand * 2), shadow_alpha)
    shadow = shadow.filter(ImageFilter.GaussianBlur(card_glow_expand * 2))

    card_x = target_w - cw - card_right_inset
    card_y = round(shared_top_y - tl_offset_y)
    canvas.alpha_composite(shadow, (card_x - card_glow_expand * 2, card_y - card_glow_expand * 2))
    canvas.alpha_composite(card_rot, (card_x, card_y))
    return card_x, card_y


def _draw_season_top_right(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    target_w: int,
    inset_right: int,
    inset_top: int,
    color: tuple[int, int, int],
    stroke_color: tuple[int, int, int],
    stroke_width: int,
) -> None:
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    x = target_w - tw - inset_right - bbox[0]
    y = inset_top - bbox[1]
    draw.text(
        (x, y), text, font=font, fill=color,
        stroke_width=stroke_width, stroke_fill=stroke_color,
    )


def render_thumbnail(
    bg_path: Path,
    logo_path: Path,
    title: str,
    output_path: Path,
    *,
    target_w: int = 1280,
    target_h: int = 720,
    logo_max_w_ratio: float = 0.20,
    logo_target_w: int | None = None,  # absolute width override
    logo_margin: int = 28,
    title_font_size: int = 128,
    title_bottom_margin: int = 50,
    title_anchor_x_ratio: float = 0.25,
    title_line_spacing: float = 1.05,
    title_color: tuple[int, int, int] = (255, 255, 255),
    title_stroke_color: tuple[int, int, int] = (218, 165, 32),
    title_stroke_width: int = 6,
    font_path: str = DEFAULT_FONT,
    font_index: int = DEFAULT_FONT_INDEX,
    orientation: str = "card-tilt-right",
    # card-tilt-right specifics
    card_path: Path | None = None,
    card_target_h: int = 580,
    card_tilt_deg: float = -12.0,
    card_right_inset: int = 150,
    card_glow_expand: int = 12,
    season_text: str = "",
    season_size: int = 80,
    season_color: tuple[int, int, int] = (255, 230, 130),
    season_stroke_color: tuple[int, int, int] = (40, 10, 0),
    season_stroke_width: int = 5,
    season_inset_right: int = 35,
    season_inset_top: int = 35,
    shared_top_y: int = 145,
    title_anchor_x_abs: int | None = None,  # absolute x override for vertical title center
    title_line_gap: int = 8,
) -> None:
    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (target_w, target_h):
        bg = bg.resize((target_w, target_h), Image.LANCZOS)
    canvas = bg.copy()

    # ── Card (must paste before logo so logo overlays card if they overlap) ──
    if orientation == "card-tilt-right":
        if card_path is None:
            raise ValueError("--card is required for orientation card-tilt-right")
        _paste_tilted_card(
            canvas, card_path,
            target_w=target_w, target_h=target_h,
            card_target_h=card_target_h,
            card_tilt_deg=card_tilt_deg,
            card_right_inset=card_right_inset,
            card_glow_expand=card_glow_expand,
            shared_top_y=shared_top_y,
        )

    # ── Logo top-left ──
    logo = Image.open(logo_path).convert("RGBA")
    logo_w = logo_target_w if logo_target_w is not None else int(target_w * logo_max_w_ratio)
    scale = logo_w / logo.size[0]
    new_logo_size = (logo_w, int(logo.size[1] * scale))
    logo = logo.resize(new_logo_size, Image.LANCZOS)
    canvas.alpha_composite(logo, dest=(logo_margin, logo_margin))

    draw = ImageDraw.Draw(canvas)

    if orientation == "horizontal-bottom":
        font = ImageFont.truetype(font_path, title_font_size, index=font_index)
        text_w, text_h = _draw_horizontal_bottom(
            draw, title, font,
            target_w=target_w, target_h=target_h,
            bottom_margin=title_bottom_margin,
            color=title_color, stroke_color=title_stroke_color, stroke_width=title_stroke_width,
        )
    elif orientation == "vertical-left":
        n_tokens = max(1, len(_tokenize_for_vertical(title)))
        # Available height = full canvas minus a small top/bottom margin.
        available_h = target_h - 2 * logo_margin
        size = _auto_shrink_font_for_vertical(
            font_path=font_path, font_index=font_index,
            requested_size=title_font_size, n_tokens=n_tokens,
            available_h=available_h, line_spacing=title_line_spacing,
        )
        if size != title_font_size:
            print(
                f"[thumb] auto-shrunk title font {title_font_size}→{size} so "
                f"{n_tokens} tokens fit in {available_h}px",
                file=sys.stderr,
            )
        font = ImageFont.truetype(font_path, size, index=font_index)
        text_w, text_h = _draw_vertical_block(
            draw, title, font,
            target_w=target_w, target_h=target_h,
            anchor_x_ratio=title_anchor_x_ratio,
            line_spacing=title_line_spacing,
            color=title_color, stroke_color=title_stroke_color, stroke_width=title_stroke_width,
        )
    elif orientation == "card-tilt-right":
        n_tokens = max(1, len(_tokenize_for_vertical(title)))
        # Available height = canvas minus shared_top_y header band minus a small bottom margin.
        # The card is on the right, so the title can extend nearly to the bottom on the left.
        available_h = target_h - shared_top_y - logo_margin
        # Use additive line gap for this orientation (matches ringnaga look).
        size = title_font_size
        while size > 32:
            row_h = size + title_line_gap
            if row_h * n_tokens <= available_h:
                break
            size -= 4
        if size != title_font_size:
            print(
                f"[thumb] auto-shrunk title font {title_font_size}→{size} so "
                f"{n_tokens} tokens fit in {available_h}px",
                file=sys.stderr,
            )
        font = ImageFont.truetype(font_path, size, index=font_index)
        anchor_x = title_anchor_x_abs if title_anchor_x_abs is not None else int(target_w * title_anchor_x_ratio)
        text_w, text_h = _draw_vertical_block_dropshadow(
            canvas, title, font,
            anchor_x=anchor_x,
            top_y=shared_top_y,
            line_gap=title_line_gap,
            color=title_color,
            shadow_offset=(3, 4),
            shadow_blur=10,
            shadow_fill=(0, 0, 0, 230),
        )
        if season_text:
            season_font = ImageFont.truetype(font_path, season_size, index=font_index)
            _draw_season_top_right(
                draw, season_text, season_font,
                target_w=target_w,
                inset_right=season_inset_right,
                inset_top=season_inset_top,
                color=season_color,
                stroke_color=season_stroke_color,
                stroke_width=season_stroke_width,
            )
    else:
        raise ValueError(f"unknown orientation: {orientation}")

    canvas.convert("RGB").save(output_path, "PNG")
    print(
        f"[thumb] bg={bg_path.name} logo={new_logo_size[0]}x{new_logo_size[1]} "
        f"title({orientation})={text_w}x{text_h} → {output_path}",
        file=sys.stderr,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bg", type=Path, required=True)
    parser.add_argument("--logo", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("--output", "-o", type=Path, required=True)
    parser.add_argument("--target-size", default="1280x720")
    parser.add_argument("--font", default=DEFAULT_FONT)
    parser.add_argument("--font-index", type=int, default=DEFAULT_FONT_INDEX)
    parser.add_argument("--font-size", type=int, default=128)
    parser.add_argument("--logo-width-ratio", type=float, default=0.20)
    parser.add_argument(
        "--logo-target-w", type=int, default=None,
        help="Absolute logo width in px. Overrides --logo-width-ratio when set.",
    )
    parser.add_argument("--logo-margin", type=int, default=28)
    parser.add_argument("--title-bottom-margin", type=int, default=50)
    parser.add_argument(
        "--title-anchor-x-ratio", type=float, default=0.25,
        help="Horizontal anchor (fraction of width) for the text block center. "
             "0.25 = center of left half, 0.35 = nudged right to clear logo.",
    )
    parser.add_argument(
        "--title-anchor-x-abs", type=int, default=None,
        help="Absolute x (px) for vertical title center. Overrides ratio when set.",
    )
    parser.add_argument("--title-line-spacing", type=float, default=1.05,
                        help="Multiplicative line spacing (vertical-left).")
    parser.add_argument("--title-line-gap", type=int, default=8,
                        help="Additive line gap in px (card-tilt-right).")
    parser.add_argument("--stroke-width", type=int, default=6)
    parser.add_argument(
        "--orientation",
        choices=["horizontal-bottom", "vertical-left", "card-tilt-right"],
        default="card-tilt-right",
        help="card-tilt-right is the new default for HSBG-style thumbnails.",
    )

    # card-tilt-right specifics
    parser.add_argument("--card", type=Path, default=None,
                        help="Card art PNG (RGBA). Required for orientation card-tilt-right.")
    parser.add_argument("--season", default="",
                        help="Season text for top-right corner (e.g. 'S13'). Empty to skip.")
    parser.add_argument("--card-target-h", type=int, default=580)
    parser.add_argument("--card-tilt-deg", type=float, default=-12.0)
    parser.add_argument("--card-right-inset", type=int, default=150)
    parser.add_argument("--card-glow-expand", type=int, default=12)
    parser.add_argument("--season-size", type=int, default=80)
    parser.add_argument("--season-inset-right", type=int, default=35)
    parser.add_argument("--season-inset-top", type=int, default=35)
    parser.add_argument(
        "--shared-top-y", type=int, default=145,
        help="Y coord (px) where the title top AND the visible TL corner of the card both anchor.",
    )

    args = parser.parse_args()

    tw, th = (int(x) for x in args.target_size.lower().split("x"))
    args.output.parent.mkdir(parents=True, exist_ok=True)

    render_thumbnail(
        bg_path=args.bg,
        logo_path=args.logo,
        title=args.title,
        output_path=args.output,
        target_w=tw,
        target_h=th,
        logo_max_w_ratio=args.logo_width_ratio,
        logo_target_w=args.logo_target_w,
        logo_margin=args.logo_margin,
        title_font_size=args.font_size,
        title_bottom_margin=args.title_bottom_margin,
        title_anchor_x_ratio=args.title_anchor_x_ratio,
        title_anchor_x_abs=args.title_anchor_x_abs,
        title_line_spacing=args.title_line_spacing,
        title_line_gap=args.title_line_gap,
        title_stroke_width=args.stroke_width,
        font_path=args.font,
        font_index=args.font_index,
        orientation=args.orientation,
        card_path=args.card,
        card_target_h=args.card_target_h,
        card_tilt_deg=args.card_tilt_deg,
        card_right_inset=args.card_right_inset,
        card_glow_expand=args.card_glow_expand,
        season_text=args.season,
        season_size=args.season_size,
        season_inset_right=args.season_inset_right,
        season_inset_top=args.season_inset_top,
        shared_top_y=args.shared_top_y,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

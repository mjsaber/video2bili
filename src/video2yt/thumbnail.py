"""Compose a YouTube thumbnail: background + logo + title + (optional) tilted card.

Three orientations:
  - horizontal-bottom:  title across the bottom (legacy)
  - vertical-left:      title stacked vertically on the left (legacy)
  - card-tilt-right:    DEFAULT — logo top-left, season top-right, vertical title
                        with drop-shadow on the left, tilted card art on the right.
"""
from __future__ import annotations

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


def tokenize_for_vertical(title: str) -> list[str]:
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


def auto_shrink_font_for_vertical(
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

    Vertical title silently overflowed in the legacy `vertical-left` mode. This
    helper keeps the requested size when possible and shrinks in 4-pt steps
    otherwise. We use a CJK glyph as the row-height baseline so a short ASCII
    token doesn't underestimate stack height.
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


def auto_shrink_font_for_card_tilt(
    *,
    requested_size: int,
    n_tokens: int,
    available_h: int,
    line_gap: int,
    min_size: int = 32,
) -> int:
    """Card-tilt-right uses additive line gap (size + gap = row_h)."""
    size = requested_size
    while size > min_size:
        row_h = size + line_gap
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
    tokens = tokenize_for_vertical(title)
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
    """Vertical title with a soft dark drop-shadow.

    Two passes: blurred dark glyph on a separate RGBA layer, alpha-composited;
    then clean coloured glyph on top with no stroke.
    """
    tokens = tokenize_for_vertical(title)
    if not tokens:
        return 0, 0

    sample_bbox = font.getbbox("国")
    glyph_h = sample_bbox[3] - sample_bbox[1]
    row_h = glyph_h + line_gap

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
    card = Image.open(card_path).convert("RGBA")
    sw, sh = card.size
    scale = card_target_h / sh
    card = card.resize((int(sw * scale), card_target_h), Image.LANCZOS)
    pre_w, pre_h = card.size
    card_rot = card.rotate(card_tilt_deg, resample=Image.BICUBIC, expand=True)
    cw, ch = card_rot.size

    # PIL rotate() rotates by `angle` degrees CCW around the image center.
    theta = math.radians(card_tilt_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    tl_rot_y = -pre_w / 2 * sin_t + -pre_h / 2 * cos_t
    tl_offset_y = tl_rot_y + ch / 2

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
    logo_target_w: int | None = None,
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
    title_anchor_x_abs: int | None = None,
    title_line_gap: int = 8,
) -> None:
    if orientation == "card-tilt-right" and card_path is None:
        raise ValueError("--card is required for orientation card-tilt-right")
    if orientation not in ("horizontal-bottom", "vertical-left", "card-tilt-right"):
        raise ValueError(f"unknown orientation: {orientation}")

    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (target_w, target_h):
        bg = bg.resize((target_w, target_h), Image.LANCZOS)
    canvas = bg.copy()

    if orientation == "card-tilt-right":
        _paste_tilted_card(
            canvas, card_path,
            target_w=target_w, target_h=target_h,
            card_target_h=card_target_h,
            card_tilt_deg=card_tilt_deg,
            card_right_inset=card_right_inset,
            card_glow_expand=card_glow_expand,
            shared_top_y=shared_top_y,
        )

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
        n_tokens = max(1, len(tokenize_for_vertical(title)))
        available_h = target_h - 2 * logo_margin
        size = auto_shrink_font_for_vertical(
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
    else:  # card-tilt-right
        n_tokens = max(1, len(tokenize_for_vertical(title)))
        available_h = target_h - shared_top_y - logo_margin
        size = auto_shrink_font_for_card_tilt(
            requested_size=title_font_size, n_tokens=n_tokens,
            available_h=available_h, line_gap=title_line_gap,
        )
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

    output_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.convert("RGB").save(output_path, "PNG")
    print(
        f"[thumb] bg={bg_path.name} logo={new_logo_size[0]}x{new_logo_size[1]} "
        f"title({orientation})={text_w}x{text_h} → {output_path}",
        file=sys.stderr,
    )

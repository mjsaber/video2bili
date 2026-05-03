"""Compose a YouTube thumbnail: background + logo (top-left) + title text.

Usage:
    uv run python scripts/thumbnail_compose.py \\
        --bg output/back2back/thumbnail_bg.png \\
        --logo assets/hsbg_logo.png \\
        --title "S13 最強輪椅" \\
        --output output/back2back/thumbnail.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

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

    # Use a CJK glyph as the row-height baseline so rows are uniform.
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


def render_thumbnail(
    bg_path: Path,
    logo_path: Path,
    title: str,
    output_path: Path,
    *,
    target_w: int = 1280,
    target_h: int = 720,
    logo_max_w_ratio: float = 0.20,  # 20% of width
    logo_margin: int = 28,
    title_font_size: int = 128,
    title_bottom_margin: int = 50,
    title_anchor_x_ratio: float = 0.25,
    title_line_spacing: float = 1.05,
    title_color: tuple[int, int, int] = (255, 255, 255),
    title_stroke_color: tuple[int, int, int] = (218, 165, 32),  # gold
    title_stroke_width: int = 6,
    font_path: str = DEFAULT_FONT,
    font_index: int = DEFAULT_FONT_INDEX,
    orientation: str = "horizontal-bottom",
) -> None:
    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (target_w, target_h):
        bg = bg.resize((target_w, target_h), Image.LANCZOS)

    canvas = bg.copy()

    # Logo top-left
    logo = Image.open(logo_path).convert("RGBA")
    logo_max_w = int(target_w * logo_max_w_ratio)
    scale = logo_max_w / logo.size[0]
    new_logo_size = (logo_max_w, int(logo.size[1] * scale))
    logo = logo.resize(new_logo_size, Image.LANCZOS)
    canvas.alpha_composite(logo, dest=(logo_margin, logo_margin))

    font = ImageFont.truetype(font_path, title_font_size, index=font_index)
    draw = ImageDraw.Draw(canvas)

    if orientation == "horizontal-bottom":
        text_w, text_h = _draw_horizontal_bottom(
            draw, title, font,
            target_w=target_w, target_h=target_h,
            bottom_margin=title_bottom_margin,
            color=title_color, stroke_color=title_stroke_color, stroke_width=title_stroke_width,
        )
    elif orientation == "vertical-left":
        text_w, text_h = _draw_vertical_block(
            draw, title, font,
            target_w=target_w, target_h=target_h,
            anchor_x_ratio=title_anchor_x_ratio,
            line_spacing=title_line_spacing,
            color=title_color, stroke_color=title_stroke_color, stroke_width=title_stroke_width,
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
    parser.add_argument("--logo-margin", type=int, default=28)
    parser.add_argument("--title-bottom-margin", type=int, default=50)
    parser.add_argument(
        "--title-anchor-x-ratio", type=float, default=0.25,
        help="Horizontal anchor (fraction of width) for the text block center. "
             "0.25 = center of left half (default), 0.75 = center of right half.",
    )
    parser.add_argument("--title-line-spacing", type=float, default=1.05)
    parser.add_argument("--stroke-width", type=int, default=6)
    parser.add_argument(
        "--orientation",
        choices=["horizontal-bottom", "vertical-left"],
        default="horizontal-bottom",
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
        logo_margin=args.logo_margin,
        title_font_size=args.font_size,
        title_bottom_margin=args.title_bottom_margin,
        title_anchor_x_ratio=args.title_anchor_x_ratio,
        title_line_spacing=args.title_line_spacing,
        title_stroke_width=args.stroke_width,
        font_path=args.font,
        font_index=args.font_index,
        orientation=args.orientation,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())

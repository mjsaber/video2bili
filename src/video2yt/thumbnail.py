"""Compose a YouTube thumbnail: background + logo + title + (optional) card art.

Four orientations:
  - card-impact:        DEFAULT — Bilibili-BG style. Card art half-bleeds bottom-out
                        on the left at +10° tilt with golden glow; diagonal speed-lines
                        fan up-right behind it; a giant 2-4 char hook phrase in
                        rotated yellow with thick black stroke + drop-shadow anchors
                        the right; small white subtitle below; optional red pill
                        result-badge top-right; season text bottom-left; radial
                        vignette darkens the bg corners for text contrast.
  - card-tilt-right:    legacy — logo top-left, season top-right, vertical title with
                        drop-shadow on the left, tilted card art on the right.
  - vertical-left:      legacy — vertical title stack on the left, no card.
  - horizontal-bottom:  legacy — single horizontal title across the bottom.
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


# ---------------------------------------------------------------------------
# card-impact orientation helpers (Bilibili-BG style)
# ---------------------------------------------------------------------------


def _apply_radial_vignette(canvas: Image.Image, strength: float) -> None:
    """Darken the corners of `canvas` (RGBA, mutated in place).

    `strength` is the alpha at the corner (0.0 = no darkening, 1.0 = solid black).
    Generated as a small radial gradient resized with bicubic so the bigger images
    stay smooth without paying the cost of a per-pixel Python loop.
    """
    if strength <= 0:
        return
    w, h = canvas.size
    sw, sh = 64, 36
    cx, cy = sw / 2, sh / 2
    max_r = math.hypot(cx, cy)
    pixels = []
    for y in range(sh):
        for x in range(sw):
            r = math.hypot(x - cx, y - cy) / max_r
            pixels.append(int(255 * (r ** 2)))
    small = Image.new("L", (sw, sh))
    small.putdata(pixels)
    alpha = small.resize((w, h), Image.BICUBIC).point(
        lambda v: int(v * strength)
    )
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    overlay.putalpha(alpha)
    canvas.alpha_composite(overlay)


def _draw_speed_lines(
    canvas: Image.Image,
    *,
    origin_xy: tuple[int, int],
    direction_deg: float,
    count: int,
    spacing: int,
    length_min: int,
    length_max: int,
    thickness_min: int,
    thickness_max: int,
    color: tuple[int, int, int, int],
    blur: float,
) -> None:
    """Draw a fan of motion-streak lines emanating from `origin_xy` in `direction_deg`.

    The lines are evenly spaced perpendicular to the direction (so they look like
    parallel motion blur, not a sunburst). Length and thickness vary by index for
    a hand-drawn feel without random.
    """
    if count <= 0:
        return
    w, h = canvas.size
    layer = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)

    rad = math.radians(direction_deg)
    cos_d, sin_d = math.cos(rad), math.sin(rad)
    perp_cos, perp_sin = -sin_d, cos_d

    ox, oy = origin_xy
    for i in range(count):
        offset = (i - count / 2) * spacing
        sx = ox + perp_cos * offset
        sy = oy + perp_sin * offset
        length = length_min + ((i % 5) / 4.0) * (length_max - length_min)
        thickness = thickness_min + (i % 3) * max(1, (thickness_max - thickness_min) // 2)
        ex = sx + cos_d * length
        ey = sy + sin_d * length
        draw.line((sx, sy, ex, ey), fill=color, width=int(thickness))

    if blur > 0:
        layer = layer.filter(ImageFilter.GaussianBlur(blur))
    canvas.alpha_composite(layer)


def _paste_card_half_bleed(
    canvas: Image.Image,
    card_path: Path,
    *,
    target_w: int,
    target_h: int,
    height_ratio: float,
    bottom_bleed: int,
    anchor_x_ratio: float,
    tilt_deg: float,
    glow_color: tuple[int, int, int, int],
    glow_blur: float,
) -> tuple[int, int]:
    """Paste the card art tilted, half-bleeding past the bottom edge.

    Card height = target_h * height_ratio (>1 → taller than canvas). Vertical center
    sits at target_h - card_h/2 + bottom_bleed so the bottom of the card extends
    past the canvas edge by `bottom_bleed` px. A soft warm glow is drawn behind it.
    """
    card = Image.open(card_path).convert("RGBA")
    sw, sh = card.size
    target_card_h = int(target_h * height_ratio)
    scale = target_card_h / sh
    card = card.resize((int(sw * scale), target_card_h), Image.LANCZOS)
    card_rot = card.rotate(tilt_deg, resample=Image.BICUBIC, expand=True)
    cw, ch = card_rot.size

    center_x = int(target_w * anchor_x_ratio)
    card_x = center_x - cw // 2
    # Anchor the visual bottom of the card past the canvas edge.
    card_y = target_h - ch + bottom_bleed

    # Soft glow on its own layer (alpha-only) → blur → composite behind the card.
    glow_pad = int(glow_blur * 3)
    glow_size = (cw + glow_pad * 2, ch + glow_pad * 2)
    glow_layer = Image.new("RGBA", glow_size, (0, 0, 0, 0))
    card_alpha = card_rot.split()[3]
    # Pull a slightly dilated alpha for a halo, fill with glow_color.
    glow_layer.paste(glow_color, (glow_pad, glow_pad), card_alpha)
    glow_layer = glow_layer.filter(ImageFilter.GaussianBlur(glow_blur))

    canvas.alpha_composite(glow_layer, (card_x - glow_pad, card_y - glow_pad))
    canvas.alpha_composite(card_rot, (card_x, card_y))
    return card_x, card_y


def _render_text_to_layer(
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    color: tuple[int, int, int],
    stroke_color: tuple[int, int, int],
    stroke_width: int,
    shadow_offset: tuple[int, int],
    shadow_blur: float,
    shadow_fill: tuple[int, int, int, int],
) -> Image.Image:
    """Render `text` onto a tight transparent RGBA layer with stroke + drop-shadow.

    Returns a layer the size of (text + padding). Caller can rotate and paste it.
    """
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad = stroke_width + max(abs(shadow_offset[0]), abs(shadow_offset[1])) + int(shadow_blur * 2) + 4
    layer_w = tw + pad * 2
    layer_h = th + pad * 2

    shadow_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow_layer)
    sd.text(
        (pad - bbox[0] + shadow_offset[0], pad - bbox[1] + shadow_offset[1]),
        text, font=font, fill=shadow_fill,
    )
    if shadow_blur > 0:
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(shadow_blur))

    text_layer = Image.new("RGBA", (layer_w, layer_h), (0, 0, 0, 0))
    td = ImageDraw.Draw(text_layer)
    td.text(
        (pad - bbox[0], pad - bbox[1]),
        text, font=font, fill=color,
        stroke_width=stroke_width, stroke_fill=stroke_color,
    )

    return Image.alpha_composite(shadow_layer, text_layer)


def auto_shrink_font_for_hook(
    *,
    font_path: str,
    font_index: int,
    requested_size: int,
    text: str,
    max_width: int,
    min_size: int = 100,
) -> int:
    """Return the largest font size whose `text` width ≤ `max_width`."""
    size = requested_size
    while size > min_size:
        font = ImageFont.truetype(font_path, size, index=font_index)
        bbox = font.getbbox(text)
        if (bbox[2] - bbox[0]) <= max_width:
            return size
        size -= 8
    return size


def _draw_pill_badge(
    canvas: Image.Image,
    text: str,
    font: ImageFont.FreeTypeFont,
    *,
    top_right_xy: tuple[int, int],
    padding: tuple[int, int],
    fill: tuple[int, int, int],
    text_color: tuple[int, int, int],
    radius: int = 14,
) -> tuple[int, int]:
    """Draw a rounded-rect 'pill' badge anchored at its top-right corner.

    Returns (pill_w, pill_h) so callers can stack additional badges below.
    """
    bbox = font.getbbox(text)
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]
    pad_x, pad_y = padding
    pill_w = tw + pad_x * 2
    pill_h = th + pad_y * 2

    tr_x, tr_y = top_right_xy
    x0 = tr_x - pill_w
    y0 = tr_y
    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle(
        (x0, y0, x0 + pill_w, y0 + pill_h),
        radius=radius, fill=fill,
    )
    draw.text(
        (x0 + pad_x - bbox[0], y0 + pad_y - bbox[1]),
        text, font=font, fill=text_color,
    )
    return pill_w, pill_h


def _render_card_impact_branch(
    canvas: Image.Image,
    *,
    logo_path: Path,
    card_path: Path,
    hook: str,
    subtitle: str,
    season_text: str,
    result_badge: str,
    target_w: int,
    target_h: int,
    font_path: str,
    font_index: int,
    hook_size: int,
    hook_color: tuple[int, int, int],
    hook_stroke_color: tuple[int, int, int],
    hook_stroke_width: int,
    hook_rotation_deg: float,
    hook_anchor_x_ratio: float,
    hook_anchor_y_ratio: float,
    hook_max_width_ratio: float,
    subtitle_size: int,
    subtitle_color: tuple[int, int, int],
    subtitle_stroke_color: tuple[int, int, int],
    subtitle_stroke_width: int,
    subtitle_offset_y: int,
    result_badge_color: tuple[int, int, int],
    result_badge_text_color: tuple[int, int, int],
    result_badge_size: int,
    vignette_strength: float,
    speed_lines_enabled: bool,
    speed_lines_count: int,
    speed_lines_color: tuple[int, int, int, int],
    card_height_ratio: float,
    card_bottom_bleed: int,
    card_anchor_x_ratio: float,
    card_tilt_deg: float,
    card_glow_color: tuple[int, int, int, int],
    card_glow_blur: float,
    logo_target_w: int,
    logo_margin: int,
    season_size: int,
    season_color: tuple[int, int, int],
    season_stroke_color: tuple[int, int, int],
    season_stroke_width: int,
) -> tuple[int, int]:
    """Bilibili-BG style composition. Mutates `canvas`. Returns (hook_w, hook_h).

    Composition order matters: vignette → speed-lines → card → logo → hook → subtitle
    → badges. Speed-lines go behind the card so the card stays the visual hero.
    """
    _apply_radial_vignette(canvas, vignette_strength)

    if speed_lines_enabled:
        # Emit two diagonal fans so motion is visible AROUND the card (most lines
        # would otherwise sit behind the card art and get occluded). Top-right fan
        # goes up-right; bottom-right fan goes down-right. Drawn before card so
        # the card stays the visual hero.
        _draw_speed_lines(
            canvas,
            origin_xy=(int(target_w * 0.55), int(target_h * 0.30)),
            direction_deg=-15.0,
            count=speed_lines_count,
            spacing=42,
            length_min=320, length_max=560,
            thickness_min=3, thickness_max=7,
            color=speed_lines_color,
            blur=1.6,
        )
        _draw_speed_lines(
            canvas,
            origin_xy=(int(target_w * 0.55), int(target_h * 0.78)),
            direction_deg=15.0,
            count=max(3, speed_lines_count - 2),
            spacing=42,
            length_min=240, length_max=420,
            thickness_min=3, thickness_max=6,
            color=speed_lines_color,
            blur=1.6,
        )

    _paste_card_half_bleed(
        canvas, card_path,
        target_w=target_w, target_h=target_h,
        height_ratio=card_height_ratio,
        bottom_bleed=card_bottom_bleed,
        anchor_x_ratio=card_anchor_x_ratio,
        tilt_deg=card_tilt_deg,
        glow_color=card_glow_color,
        glow_blur=card_glow_blur,
    )

    logo = Image.open(logo_path).convert("RGBA")
    scale = logo_target_w / logo.size[0]
    new_logo_size = (logo_target_w, int(logo.size[1] * scale))
    logo = logo.resize(new_logo_size, Image.LANCZOS)
    canvas.alpha_composite(logo, dest=(logo_margin, logo_margin))

    max_hook_w = int(target_w * hook_max_width_ratio)
    size = auto_shrink_font_for_hook(
        font_path=font_path, font_index=font_index,
        requested_size=hook_size, text=hook, max_width=max_hook_w,
    )
    hook_font = ImageFont.truetype(font_path, size, index=font_index)
    hook_layer = _render_text_to_layer(
        hook, hook_font,
        color=hook_color,
        stroke_color=hook_stroke_color,
        stroke_width=hook_stroke_width,
        shadow_offset=(6, 8),
        shadow_blur=22.0,
        shadow_fill=(0, 0, 0, 220),
    )
    hook_rotated = hook_layer.rotate(
        hook_rotation_deg, resample=Image.BICUBIC, expand=True,
    )
    rw, rh = hook_rotated.size
    hook_anchor_x = int(target_w * hook_anchor_x_ratio)
    hook_anchor_y = int(target_h * hook_anchor_y_ratio)
    hook_top_left = (hook_anchor_x - rw // 2, hook_anchor_y - rh // 2)
    canvas.alpha_composite(hook_rotated, hook_top_left)

    if subtitle:
        sub_font = ImageFont.truetype(font_path, subtitle_size, index=font_index)
        sub_layer = _render_text_to_layer(
            subtitle, sub_font,
            color=subtitle_color,
            stroke_color=subtitle_stroke_color,
            stroke_width=subtitle_stroke_width,
            shadow_offset=(2, 3),
            shadow_blur=8.0,
            shadow_fill=(0, 0, 0, 180),
        )
        sw_, sh_ = sub_layer.size
        sub_x = hook_anchor_x - sw_ // 2
        sub_y = hook_top_left[1] + rh + subtitle_offset_y
        canvas.alpha_composite(sub_layer, (sub_x, sub_y))

    if result_badge:
        badge_font = ImageFont.truetype(font_path, result_badge_size, index=font_index)
        _draw_pill_badge(
            canvas, result_badge, badge_font,
            top_right_xy=(target_w - logo_margin, logo_margin),
            padding=(28, 14),
            fill=result_badge_color,
            text_color=result_badge_text_color,
        )

    if season_text:
        season_font = ImageFont.truetype(font_path, season_size, index=font_index)
        bb = season_font.getbbox(season_text)
        stw = bb[2] - bb[0]
        sth = bb[3] - bb[1]
        sx = logo_margin - bb[0]
        sy = target_h - logo_margin - sth - bb[1]
        ImageDraw.Draw(canvas).text(
            (sx, sy), season_text, font=season_font, fill=season_color,
            stroke_width=season_stroke_width, stroke_fill=season_stroke_color,
        )

    print(
        f"[thumb] card-impact: hook='{hook}' size={size} rot={hook_rotation_deg}° "
        f"hook_box={rw}x{rh} subtitle={'yes' if subtitle else 'no'} "
        f"badge={'yes' if result_badge else 'no'}",
        file=sys.stderr,
    )
    return rw, rh


def render_thumbnail(
    bg_path: Path,
    logo_path: Path,
    title: str,
    output_path: Path,
    *,
    target_w: int = 1280,
    target_h: int = 720,
    logo_max_w_ratio: float | None = None,
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
    orientation: str = "card-impact",
    card_path: Path | None = None,
    card_target_h: int = 580,
    card_tilt_deg: float | None = None,
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
    # card-impact orientation params (defaults tuned for HSBG aesthetic)
    hook: str = "",
    subtitle: str = "",
    result_badge: str = "",
    hook_size: int = 240,
    hook_color: tuple[int, int, int] = (255, 230, 60),
    hook_stroke_color: tuple[int, int, int] = (8, 4, 4),
    hook_stroke_width: int = 10,
    hook_rotation_deg: float = -8.0,
    hook_anchor_x_ratio: float = 0.65,
    hook_anchor_y_ratio: float = 0.42,
    hook_max_width_ratio: float = 0.55,
    subtitle_size: int = 56,
    subtitle_color: tuple[int, int, int] = (255, 255, 255),
    subtitle_stroke_color: tuple[int, int, int] = (0, 0, 0),
    subtitle_stroke_width: int = 4,
    subtitle_offset_y: int = 24,
    result_badge_color: tuple[int, int, int] = (220, 30, 40),
    result_badge_text_color: tuple[int, int, int] = (255, 255, 255),
    result_badge_size: int = 56,
    vignette_strength: float = 0.55,
    speed_lines_enabled: bool = True,
    speed_lines_count: int = 7,
    speed_lines_color: tuple[int, int, int, int] = (255, 255, 255, 150),
    card_height_ratio: float = 1.10,
    card_bottom_bleed: int = 70,
    card_anchor_x_ratio: float = 0.27,
    card_glow_color: tuple[int, int, int, int] = (255, 200, 80, 200),
    card_glow_blur: float = 25.0,
) -> None:
    if orientation == "card-impact":
        if card_path is None:
            raise ValueError("--card is required for orientation card-impact")
        if not hook:
            raise ValueError("--hook is required for orientation card-impact")
    if orientation == "card-tilt-right" and card_path is None:
        raise ValueError("--card is required for orientation card-tilt-right")
    if orientation not in (
        "card-impact", "horizontal-bottom", "vertical-left", "card-tilt-right",
    ):
        raise ValueError(f"unknown orientation: {orientation}")

    # Resolve orientation-aware defaults for sentinel-None params. Doing this here
    # (instead of via argparse defaults) lets every CLI control flow through
    # without silent overrides — a user passing `--card-tilt-deg -12` for
    # card-impact gets -12, not the orientation default.
    if card_tilt_deg is None:
        card_tilt_deg = 10.0 if orientation == "card-impact" else -12.0
    if logo_max_w_ratio is None:
        logo_max_w_ratio = 0.125 if orientation == "card-impact" else 0.20

    bg = Image.open(bg_path).convert("RGBA")
    if bg.size != (target_w, target_h):
        bg = bg.resize((target_w, target_h), Image.LANCZOS)
    canvas = bg.copy()

    if orientation == "card-impact":
        # Logo width: --logo-target-w (absolute) wins, else --logo-width-ratio,
        # else card-impact default 0.125 * target_w (≈ 160 at 1280).
        if logo_target_w is not None:
            effective_logo_w = logo_target_w
        else:
            effective_logo_w = int(target_w * logo_max_w_ratio)
        _render_card_impact_branch(
            canvas,
            logo_path=logo_path, card_path=card_path,
            hook=hook, subtitle=subtitle,
            season_text=season_text, result_badge=result_badge,
            target_w=target_w, target_h=target_h,
            font_path=font_path, font_index=font_index,
            hook_size=hook_size,
            hook_color=hook_color, hook_stroke_color=hook_stroke_color,
            hook_stroke_width=hook_stroke_width,
            hook_rotation_deg=hook_rotation_deg,
            hook_anchor_x_ratio=hook_anchor_x_ratio,
            hook_anchor_y_ratio=hook_anchor_y_ratio,
            hook_max_width_ratio=hook_max_width_ratio,
            subtitle_size=subtitle_size,
            subtitle_color=subtitle_color,
            subtitle_stroke_color=subtitle_stroke_color,
            subtitle_stroke_width=subtitle_stroke_width,
            subtitle_offset_y=subtitle_offset_y,
            result_badge_color=result_badge_color,
            result_badge_text_color=result_badge_text_color,
            result_badge_size=result_badge_size,
            vignette_strength=vignette_strength,
            speed_lines_enabled=speed_lines_enabled,
            speed_lines_count=speed_lines_count,
            speed_lines_color=speed_lines_color,
            card_height_ratio=card_height_ratio,
            card_bottom_bleed=card_bottom_bleed,
            card_anchor_x_ratio=card_anchor_x_ratio,
            card_tilt_deg=card_tilt_deg,
            card_glow_color=card_glow_color,
            card_glow_blur=card_glow_blur,
            logo_target_w=effective_logo_w,
            logo_margin=logo_margin,
            season_size=season_size,
            season_color=season_color,
            season_stroke_color=season_stroke_color,
            season_stroke_width=season_stroke_width,
        )
        output_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.convert("RGB").save(output_path, "PNG")
        return

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

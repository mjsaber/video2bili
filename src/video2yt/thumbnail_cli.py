"""CLI for video2yt-thumbnail: compose a YouTube thumbnail PNG."""

import argparse
import sys
from pathlib import Path

from video2yt import thumbnail


def _log(msg: str) -> None:
    print(f"[video2yt-thumbnail] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-thumbnail",
        description=(
            "Compose a YouTube thumbnail (1280x720 by default) from a background, "
            "a logo, a title, and optionally a card. Default orientation is "
            "card-impact (Bilibili-BG style). The legacy card-tilt-right layout, "
            "vertical-left, and horizontal-bottom remain available via --orientation."
        ),
    )
    parser.add_argument("--bg", type=Path, required=True,
                        help="Background image. Resized to --target-size if needed.")
    parser.add_argument("--logo", type=Path, required=True,
                        help="Logo PNG. Drawn top-left for every orientation.")
    parser.add_argument("--title", required=True,
                        help="Title text. Used by legacy orientations; card-impact "
                             "uses --hook + --subtitle instead but still requires this.")
    parser.add_argument("-o", "--output", type=Path, required=True,
                        help="Output PNG path.")
    parser.add_argument("--target-size", default="1280x720",
                        help="WIDTHxHEIGHT, e.g. 1280x720 (YouTube) or 1920x1080.")
    parser.add_argument("--font", default=thumbnail.DEFAULT_FONT,
                        help=f"Font file path. Default: {thumbnail.DEFAULT_FONT}.")
    parser.add_argument("--font-index", type=int, default=thumbnail.DEFAULT_FONT_INDEX,
                        help="Font face index inside the .ttc collection (0=Regular, 1=Bold).")
    parser.add_argument(
        "--logo-width-ratio", type=float, default=None,
        help="Logo width as fraction of canvas width. Honored by all orientations. "
             "Orientation-specific default when omitted: 0.20 for legacy, 0.125 for "
             "card-impact (smaller so the hook gets visual priority).",
    )
    parser.add_argument(
        "--logo-target-w", type=int, default=None,
        help="Absolute logo width in px. Overrides --logo-width-ratio. Honored by "
             "all orientations.",
    )
    parser.add_argument("--logo-margin", type=int, default=28,
                        help="Inset (px) for the logo from the top-left corner.")
    parser.add_argument(
        "--orientation",
        choices=["card-impact", "horizontal-bottom", "vertical-left", "card-tilt-right"],
        default="card-impact",
        help="card-impact (default) is the Bilibili-BG style. card-tilt-right "
             "is the legacy locked layout. vertical-left and horizontal-bottom "
             "are pre-card legacy layouts.",
    )
    parser.add_argument("--card", type=Path, default=None,
                        help="Card art PNG (RGBA). Required for card-impact and card-tilt-right.")
    parser.add_argument("--season", default="",
                        help="Season text. Placed bottom-left in card-impact, top-right "
                             "in card-tilt-right; ignored by other orientations.")
    parser.add_argument("--season-size", type=int, default=80,
                        help="Season text font size.")
    parser.add_argument(
        "--card-tilt-deg", type=float, default=None,
        help="Card rotation in degrees. Used only by card orientations (card-impact, "
             "card-tilt-right); ignored by vertical-left/horizontal-bottom. "
             "Orientation default when omitted: +10° (card-impact, forward lean), "
             "-12° (card-tilt-right).",
    )

    # Flags that apply only to legacy text orientations.
    legacy = parser.add_argument_group(
        "legacy text orientations (horizontal-bottom / vertical-left / card-tilt-right)",
        "Ignored when --orientation is card-impact.",
    )
    legacy.add_argument(
        "--font-size", type=int, default=128,
        help="Title font size. card-impact uses --hook-size instead.",
    )
    legacy.add_argument(
        "--title-bottom-margin", type=int, default=50,
        help="(horizontal-bottom only) Px from canvas bottom to the title baseline.",
    )
    legacy.add_argument(
        "--title-anchor-x-ratio", type=float, default=0.25,
        help="(vertical-left + card-tilt-right) Horizontal anchor fraction "
             "for the vertical text block center.",
    )
    legacy.add_argument(
        "--title-anchor-x-abs", type=int, default=None,
        help="(card-tilt-right only) Absolute x (px) for vertical title center; "
             "overrides --title-anchor-x-ratio.",
    )
    legacy.add_argument("--title-line-spacing", type=float, default=1.05,
                        help="(vertical-left only) Multiplicative line spacing.")
    legacy.add_argument("--title-line-gap", type=int, default=8,
                        help="(card-tilt-right only) Additive line gap in px.")
    legacy.add_argument(
        "--stroke-width", type=int, default=6,
        help="(horizontal-bottom + vertical-left only) Title stroke (outline) width. "
             "card-tilt-right uses a drop shadow without stroke; card-impact uses "
             "internal hook/subtitle stroke widths.",
    )

    # Flags specific to the card-tilt-right orientation.
    tilt = parser.add_argument_group(
        "card-tilt-right orientation",
        "Ignored when --orientation is anything else.",
    )
    tilt.add_argument("--card-target-h", type=int, default=580,
                      help="Card height in px.")
    tilt.add_argument("--card-right-inset", type=int, default=150,
                      help="Px inset from the right edge for the card.")
    tilt.add_argument("--card-glow-expand", type=int, default=12,
                      help="Card glow halo expand in px.")
    tilt.add_argument("--season-inset-right", type=int, default=35,
                      help="Px inset from the right edge for the season text.")
    tilt.add_argument("--season-inset-top", type=int, default=35,
                      help="Px inset from the top edge for the season text.")
    tilt.add_argument("--shared-top-y", type=int, default=145,
                      help="Y coord (px) where the title top + visible card TL anchor.")

    # card-impact orientation
    impact = parser.add_argument_group(
        "card-impact orientation",
        "Ignored when --orientation is anything else.",
    )
    impact.add_argument(
        "--hook", default="",
        help="Punchy 2-4 char phrase, e.g. '破局'/'T0最强'/'9鸡满配'. Required for card-impact.",
    )
    impact.add_argument(
        "--subtitle", default="",
        help="Smaller white descriptor (6-14 chars), placed below the hook.",
    )
    impact.add_argument(
        "--result-badge", default="",
        help="Optional red pill in top-right corner, e.g. '9鸡' or 'T0'.",
    )
    impact.add_argument("--hook-size", type=int, default=240,
                        help="Hook font size (auto-shrunk if too wide).")
    impact.add_argument("--hook-rotation-deg", type=float, default=-8.0,
                        help="Hook rotation. -8° gives a forward dynamic feel.")
    impact.add_argument("--hook-anchor-x-ratio", type=float, default=0.65,
                        help="Horizontal anchor fraction for the hook center.")
    impact.add_argument("--hook-anchor-y-ratio", type=float, default=0.42,
                        help="Vertical anchor fraction for the hook center.")
    impact.add_argument("--vignette-strength", type=float, default=0.55,
                        help="Corner darkening for text contrast. 0=off, 1=corners black.")
    impact.add_argument(
        "--no-speed-lines", action="store_false", dest="speed_lines_enabled",
        help="Disable the diagonal motion-streak lines behind the card.",
    )
    impact.add_argument("--card-bottom-bleed", type=int, default=70,
                        help="Px the card extends past the canvas bottom edge.")
    impact.add_argument("--card-anchor-x-ratio", type=float, default=0.27,
                        help="Horizontal center of the card as fraction of width.")
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    tw, th = (int(x) for x in args.target_size.lower().split("x"))
    thumbnail.render_thumbnail(
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
        hook=args.hook,
        subtitle=args.subtitle,
        result_badge=args.result_badge,
        hook_size=args.hook_size,
        hook_rotation_deg=args.hook_rotation_deg,
        hook_anchor_x_ratio=args.hook_anchor_x_ratio,
        hook_anchor_y_ratio=args.hook_anchor_y_ratio,
        vignette_strength=args.vignette_strength,
        speed_lines_enabled=args.speed_lines_enabled,
        card_bottom_bleed=args.card_bottom_bleed,
        card_anchor_x_ratio=args.card_anchor_x_ratio,
    )
    _log(f"saved {args.output}")
    return args.output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError, OSError) as e:
        # OSError covers PIL UnidentifiedImageError + ImageFont.truetype failures
        # (corrupt or missing background/logo/card PNG, missing system font, etc.).
        _log(f"error: {e}")
        return 1

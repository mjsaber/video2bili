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
            "a logo, a title, and optionally a tilted card. Default orientation is "
            "card-tilt-right (the locked HSBG layout)."
        ),
    )
    parser.add_argument("--bg", type=Path, required=True)
    parser.add_argument("--logo", type=Path, required=True)
    parser.add_argument("--title", required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    parser.add_argument("--target-size", default="1280x720")
    parser.add_argument("--font", default=thumbnail.DEFAULT_FONT)
    parser.add_argument("--font-index", type=int, default=thumbnail.DEFAULT_FONT_INDEX)
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
        help="Horizontal anchor (fraction of width) for the text block center.",
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
    )
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
        help="Y coord (px) where title top AND visible TL corner of the card both anchor.",
    )
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
    )
    _log(f"saved {args.output}")
    return args.output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1

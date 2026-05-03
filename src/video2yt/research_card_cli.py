"""CLI for video2yt-research-card: look up a Hearthstone card and download its 512px art."""

import argparse
import sys
from pathlib import Path

from requests.exceptions import RequestException

from video2yt import research_card


def _log(msg: str) -> None:
    print(f"[video2yt-research-card] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-research-card",
        description=(
            "Look up a Hearthstone card on hearthstonejson.com and download its "
            "512px art (default: assets/cards/<slug>_512.png)."
        ),
    )
    name_grp = parser.add_mutually_exclusive_group(required=True)
    name_grp.add_argument(
        "--name",
        help="Card name (enUS, e.g. 'Ring Bearer').",
    )
    name_grp.add_argument(
        "--id",
        help="Exact card id (e.g. 'BG34_921'); skips name lookup, no metadata fetch.",
    )
    parser.add_argument(
        "--style",
        choices=["render", "bgs", "auto"],
        default="auto",
        help=(
            "auto = bgs for battlegrounds cards, render otherwise (default). "
            "render = full card with frame; bgs = battlegrounds-tier card."
        ),
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output PNG path. Default: assets/cards/<slug>_512.png",
    )
    parser.add_argument(
        "--no-cache",
        action="store_true",
        help="Force re-download of cards.json even if a fresh cache exists.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    if args.id:
        card_id = args.id
        slug = research_card.slugify(card_id)
        # Without metadata, --style auto can't tell BG from render. Default to bgs since
        # the project's primary use case is battlegrounds; user can override with --style.
        style = "bgs" if args.style == "auto" else args.style
        _log(f"using id={card_id} (skipping metadata fetch) → style={style}")
    else:
        cards = research_card.load_cards(no_cache=args.no_cache)
        card = research_card.find_card(cards, args.name)
        card_id = card["id"]
        slug = research_card.slugify(card["name"])
        if args.style == "auto":
            style = "bgs" if research_card.is_battlegrounds(card) else "render"
        else:
            style = args.style
        _log(
            f"matched: {card['name']} ({card_id}, set={card.get('set', '?')}) → style={style}"
        )

    output = args.output or (Path("assets/cards") / f"{slug}_512.png")
    research_card.download_art(card_id, style, output)
    _log(f"saved {output}")
    return output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1
    except RequestException as e:
        _log(f"network error: {e}")
        return 1

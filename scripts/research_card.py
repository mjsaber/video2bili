"""Find a Hearthstone card by name and download its 512px art to assets/cards/.

Backed by the public hearthstonejson.com data dump:
  - Card metadata: https://api.hearthstonejson.com/v1/latest/enUS/cards.json
  - Card art:      https://art.hearthstonejson.com/v1/<style>/latest/enUS/512x/<id>.png

Two art styles are supported via --style:
  - render: full rendered card (default; matches assets/cards/ring_bearer_512.png)
  - bgs:    battlegrounds-style cropped art (per output/ringnaga/WORKFLOW_NOTES.md)

Usage:
    uv run python scripts/research_card.py --name "Ring Bearer"
    uv run python scripts/research_card.py --name "Ring Bearer" --style bgs
    uv run python scripts/research_card.py --name "Ring Bearer" -o my_card.png
"""
from __future__ import annotations

import argparse
import re
import sys
import time
from pathlib import Path

import requests

CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
ART_URL_TEMPLATE = "https://art.hearthstonejson.com/v1/{style}/latest/enUS/512x/{id}.png"
CACHE_PATH = Path.home() / ".cache" / "video2yt" / "hearthstonejson_cards.json"
CACHE_TTL_SECS = 7 * 24 * 3600  # 7 days


def load_cards(no_cache: bool = False) -> list[dict]:
    """Return the parsed cards.json, fetching and caching on cache miss."""
    if not no_cache and CACHE_PATH.exists():
        age = time.time() - CACHE_PATH.stat().st_mtime
        if age < CACHE_TTL_SECS:
            print(f"[research] using cached cards.json ({age/3600:.1f}h old)", file=sys.stderr)
            import json
            return json.loads(CACHE_PATH.read_text(encoding="utf-8"))

    print(f"[research] fetching {CARDS_URL} (~30MB, may take a few seconds)", file=sys.stderr)
    resp = requests.get(CARDS_URL, timeout=60)
    resp.raise_for_status()
    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    CACHE_PATH.write_bytes(resp.content)
    return resp.json()


def find_card(cards: list[dict], name: str) -> dict:
    """Find one card whose enUS name matches `name` (case-insensitive)."""
    needle = name.strip().casefold()
    exact = [c for c in cards if c.get("name", "").casefold() == needle]
    if exact:
        winner = _pick_best(exact)
        if winner:
            return winner
        names = [f"  - {c['name']} ({c.get('id', '?')}, set={c.get('set', '?')})" for c in exact]
        raise SystemExit(
            f"ambiguous: {len(exact)} cards exactly named {name!r}. Disambiguate by id "
            f"with --id <ID>:\n" + "\n".join(names)
        )

    substring = [c for c in cards if needle in c.get("name", "").casefold()]
    if not substring:
        raise SystemExit(
            f"no card found matching {name!r}. Tip: hearthstonejson.com lists names in enUS; "
            "pass the English name (e.g. 'Ring Bearer', not '戒指龍')."
        )
    winner = _pick_best(substring)
    if winner:
        return winner

    names = [f"  - {c['name']} ({c.get('id', '?')}, set={c.get('set', '?')})" for c in substring[:15]]
    more = "" if len(substring) <= 15 else f"\n  ...and {len(substring) - 15} more"
    raise SystemExit(
        f"ambiguous: {len(substring)} cards contain {name!r}. Narrow down or use --id:\n"
        + "\n".join(names) + more
    )


def _pick_best(candidates: list[dict]) -> dict | None:
    """Apply tiebreakers: 1 candidate wins; else prefer BG + non-golden + non-tavern variant.

    Returns the unique winner, or None if still ambiguous.
    """
    if len(candidates) == 1:
        return candidates[0]
    pool = [c for c in candidates if _is_battlegrounds(c)] or candidates
    # Drop golden variants (ids ending in '_G' or '_g').
    non_golden = [c for c in pool if not c.get("id", "").lower().endswith("_g")]
    pool = non_golden or pool
    return pool[0] if len(pool) == 1 else None


def _is_battlegrounds(card: dict) -> bool:
    if card.get("set") == "BATTLEGROUNDS":
        return True
    if card.get("battlegroundsHero") or card.get("battlegroundsBuddyDbfId"):
        return True
    if "techLevel" in card:
        return True
    return False


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def download_art(card_id: str, style: str, output: Path) -> None:
    url = ART_URL_TEMPLATE.format(style=style, id=card_id)
    print(f"[research] downloading {url}", file=sys.stderr)
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        raise SystemExit(
            f"art not found at {url}. Try --style {'bgs' if style == 'render' else 'render'}, "
            f"or check the card id on hearthstonejson.com."
        )
    resp.raise_for_status()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(resp.content)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    name_grp = parser.add_mutually_exclusive_group(required=True)
    name_grp.add_argument("--name", help="Card name (enUS, e.g. 'Ring Bearer').")
    name_grp.add_argument("--id", help="Exact card id (e.g. 'BG29_HERO_402'), skips name lookup.")
    parser.add_argument(
        "--style", choices=["render", "bgs", "auto"], default="auto",
        help="auto = bgs for battlegrounds cards, render otherwise (default). "
             "render = full card with frame; bgs = battlegrounds-tier card.",
    )
    parser.add_argument(
        "--output", "-o", type=Path, default=None,
        help="Output PNG path. Default: assets/cards/<slug>_512.png",
    )
    parser.add_argument("--no-cache", action="store_true", help="Force re-download of cards.json.")
    args = parser.parse_args()

    if args.id:
        card_id = args.id
        slug = slugify(card_id)
        # Without metadata, --style auto can't tell BG from render. Default to bgs since
        # the project's primary use case is battlegrounds; user can override with --style render.
        style = "bgs" if args.style == "auto" else args.style
    else:
        cards = load_cards(no_cache=args.no_cache)
        card = find_card(cards, args.name)
        card_id = card["id"]
        slug = slugify(card["name"])
        if args.style == "auto":
            style = "bgs" if _is_battlegrounds(card) else "render"
        else:
            style = args.style
        print(
            f"[research] matched: {card['name']} ({card_id}, set={card.get('set', '?')}) → style={style}",
            file=sys.stderr,
        )

    output = args.output or (Path("assets/cards") / f"{slug}_512.png")
    download_art(card_id, style, output)
    print(f"[research] saved {output}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())

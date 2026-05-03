"""Hearthstone card lookup against the public hearthstonejson.com data dump.

Two endpoints:
  - Card metadata: https://api.hearthstonejson.com/v1/latest/enUS/cards.json (~30 MB)
  - Card art:      https://art.hearthstonejson.com/v1/<style>/latest/enUS/512x/<id>.png

Two art styles:
  - render: full rendered card with frame (constructed cards live here)
  - bgs:    battlegrounds-tier card (BG-set cards live here)

The metadata blob is cached at `~/.cache/video2yt/hearthstonejson_cards.json` for
7 days to avoid repeated 30 MB downloads.
"""
from __future__ import annotations

import json
import re
import sys
import time
from pathlib import Path

import requests

CARDS_URL = "https://api.hearthstonejson.com/v1/latest/enUS/cards.json"
ART_URL_TEMPLATE = "https://art.hearthstonejson.com/v1/{style}/latest/enUS/512x/{id}.png"
DEFAULT_CACHE_PATH = Path.home() / ".cache" / "video2yt" / "hearthstonejson_cards.json"
CACHE_TTL_SECS = 7 * 24 * 3600


def slugify(name: str) -> str:
    """Lowercase + collapse non-alphanumeric runs to underscores. Trim leading/trailing _."""
    s = name.strip().lower()
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def is_battlegrounds(card: dict) -> bool:
    """True iff the card is a Battlegrounds-set / BG-tier / BG hero entry."""
    if card.get("set") == "BATTLEGROUNDS":
        return True
    if card.get("battlegroundsHero") or card.get("battlegroundsBuddyDbfId"):
        return True
    if "techLevel" in card:
        return True
    return False


def pick_best(candidates: list[dict]) -> dict | None:
    """Apply tiebreakers: prefer BG variant, drop golden (`_G` suffix). None if still ambiguous."""
    if len(candidates) == 1:
        return candidates[0]
    pool = [c for c in candidates if is_battlegrounds(c)] or candidates
    non_golden = [c for c in pool if not c.get("id", "").lower().endswith("_g")]
    pool = non_golden or pool
    return pool[0] if len(pool) == 1 else None


def find_card(cards: list[dict], name: str) -> dict:
    """Find one card whose enUS name matches `name` (case-insensitive).

    Tries exact match first, then substring. Raises `ValueError` with a helpful
    list when zero or multiple-after-tiebreak matches are found.
    """
    needle = name.strip().casefold()
    exact = [c for c in cards if c.get("name", "").casefold() == needle]
    if exact:
        winner = pick_best(exact)
        if winner:
            return winner
        names = [
            f"  - {c['name']} ({c.get('id', '?')}, set={c.get('set', '?')})"
            for c in exact
        ]
        raise ValueError(
            f"ambiguous: {len(exact)} cards exactly named {name!r}. "
            f"Disambiguate by id with --id <ID>:\n" + "\n".join(names)
        )

    substring = [c for c in cards if needle in c.get("name", "").casefold()]
    if not substring:
        raise ValueError(
            f"no card found matching {name!r}. Tip: hearthstonejson.com lists "
            "names in enUS; pass the English name (e.g. 'Ring Bearer', not '戒指龍')."
        )
    winner = pick_best(substring)
    if winner:
        return winner

    names = [
        f"  - {c['name']} ({c.get('id', '?')}, set={c.get('set', '?')})"
        for c in substring[:15]
    ]
    more = "" if len(substring) <= 15 else f"\n  ...and {len(substring) - 15} more"
    raise ValueError(
        f"ambiguous: {len(substring)} cards contain {name!r}. Narrow down or use --id:\n"
        + "\n".join(names) + more
    )


def load_cards(
    *,
    no_cache: bool = False,
    cache_path: Path | None = None,
) -> list[dict]:
    """Return the parsed cards.json, fetching and caching on cache miss/expiry."""
    cache_path = cache_path if cache_path is not None else DEFAULT_CACHE_PATH

    if not no_cache and cache_path.exists():
        age = time.time() - cache_path.stat().st_mtime
        if age < CACHE_TTL_SECS:
            print(
                f"[research_card] using cached cards.json ({age/3600:.1f}h old)",
                file=sys.stderr,
            )
            return json.loads(cache_path.read_text(encoding="utf-8"))

    print(
        f"[research_card] fetching {CARDS_URL} (~30MB, may take a few seconds)",
        file=sys.stderr,
    )
    resp = requests.get(CARDS_URL, timeout=60)
    resp.raise_for_status()
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(resp.content)
    return resp.json()


def download_art(card_id: str, style: str, output: Path) -> None:
    """Download the 512px card art to `output`. Raises `ValueError` on 404."""
    url = ART_URL_TEMPLATE.format(style=style, id=card_id)
    print(f"[research_card] downloading {url}", file=sys.stderr)
    resp = requests.get(url, timeout=30)
    if resp.status_code == 404:
        other = "bgs" if style == "render" else "render"
        raise ValueError(
            f"art not found at {url}. Try --style {other}, "
            "or check the card id on hearthstonejson.com."
        )
    resp.raise_for_status()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(resp.content)

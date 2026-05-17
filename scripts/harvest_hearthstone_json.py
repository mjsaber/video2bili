#!/usr/bin/env python3
"""HearthstoneJSON BG card harvester (one-off, not part of the runtime).

Downloads (or reads from cache) the latest Hearthstone card JSON in zhCN,
filters BG-pool entries by type, dedupes by name, prints YAML-ready
category lists to stdout for manual paste into
``src/video2yt/data/bg_glossary.yaml``'s ``canonical.*`` sections.

Categories emitted:
  hero    — ``battlegroundsHero==True`` (all BG heroes; HearthstoneJSON has
            no "current rotation" field, so this includes retired heroes)
  minion  — ``isBattlegroundsPoolMinion==True`` (current pool)
  spell   — ``isBattlegroundsPoolSpell==True`` (subset of type=BATTLEGROUND_SPELL)
  trinket — ``type==BATTLEGROUND_TRINKET`` minus entries whose name ends in
            ``肖像`` (those are portrait skins, not real trinkets)

All categories are deduped by name and sorted by Unicode codepoint.

Usage::

  uv run python scripts/harvest_hearthstone_json.py [--cache PATH]

When a Hearthstone patch lands and the BG pool rotates, re-run this and
update the YAML by hand. The script intentionally does NOT write the YAML
directly — the categorization is human-reviewed.
"""
import argparse
import json
import sys
import urllib.request
from pathlib import Path

URL = "https://api.hearthstonejson.com/v1/latest/zhCN/cards.json"

# Names whose suffix marks them as cosmetic portrait skins, not real trinkets.
TRINKET_EXCLUDE_SUFFIXES = ("肖像",)


def fetch_cards(cache: Path | None) -> list[dict]:
    if cache is not None and cache.exists():
        print(f"Using cached cards.json: {cache}", file=sys.stderr)
        return json.loads(cache.read_text(encoding="utf-8"))
    print(f"Downloading {URL} …", file=sys.stderr)
    with urllib.request.urlopen(URL) as r:
        data = r.read()
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_bytes(data)
        print(f"Cached to: {cache}", file=sys.stderr)
    return json.loads(data)


def _dedup_sorted(names: list[str]) -> list[str]:
    return sorted(set(n for n in names if n))


def filter_heroes(cards: list[dict]) -> list[str]:
    return _dedup_sorted(
        c.get("name", "") for c in cards if c.get("battlegroundsHero") is True
    )


def filter_minions(cards: list[dict]) -> list[str]:
    return _dedup_sorted(
        c.get("name", "")
        for c in cards
        if c.get("isBattlegroundsPoolMinion") is True
    )


def filter_spells(cards: list[dict]) -> list[str]:
    return _dedup_sorted(
        c.get("name", "")
        for c in cards
        if c.get("isBattlegroundsPoolSpell") is True
    )


def filter_trinkets(cards: list[dict]) -> list[str]:
    names = []
    for c in cards:
        if c.get("type") != "BATTLEGROUND_TRINKET":
            continue
        n = c.get("name", "")
        if not n or any(n.endswith(s) for s in TRINKET_EXCLUDE_SUFFIXES):
            continue
        names.append(n)
    return _dedup_sorted(names)


def emit_yaml_section(label: str, items: list[str]) -> None:
    print(f"  {label}:")
    for item in items:
        # Quote names that contain YAML-special characters. Real BG card names
        # don't contain these in practice, but guard anyway so a future patch
        # introducing a card like "X: Y" doesn't silently corrupt the YAML.
        if any(ch in item for ch in [":", "#", '"', "'", "[", "]", "{", "}", "&", "*"]):
            esc = item.replace('"', '\\"')
            print(f'    - "{esc}"')
        else:
            print(f"    - {item}")


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--cache", type=Path, default=None,
        help="Local path to read/write the cards.json blob",
    )
    args = p.parse_args()
    cards = fetch_cards(args.cache)
    heroes = filter_heroes(cards)
    minions = filter_minions(cards)
    spells = filter_spells(cards)
    trinkets = filter_trinkets(cards)

    print(f"# Harvest report ({len(cards)} total cards)", file=sys.stderr)
    print(f"#   hero    = {len(heroes):>3} entries", file=sys.stderr)
    print(f"#   minion  = {len(minions):>3} entries", file=sys.stderr)
    print(f"#   spell   = {len(spells):>3} entries", file=sys.stderr)
    print(
        f"#   trinket = {len(trinkets):>3} entries (after dropping {TRINKET_EXCLUDE_SUFFIXES} suffix)",
        file=sys.stderr,
    )
    print(file=sys.stderr)

    emit_yaml_section("hero", heroes)
    print()
    emit_yaml_section("minion", minions)
    print()
    emit_yaml_section("spell", spells)
    print()
    emit_yaml_section("trinket", trinkets)
    return 0


if __name__ == "__main__":
    sys.exit(main())

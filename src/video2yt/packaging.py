"""Search-keyword rules for YouTube title/tags (Taiwan zhTW audience).

Evidence: assets/analytics/2026-09-13_market_search_keywords.md and
2026-09-13_search_terms_28d.md. Google Trends (TW, YouTube search) puts
「爐石戰記」 at ~3.8× the interest of 「英雄戰場」; simplified-Chinese terms
produced zero searches in 28 days; tribe words are the only intent-bearing
autocomplete layer; searchers type 不死族/納迦 rather than the official
亡靈/娜迦.
"""
from __future__ import annotations

REQUIRED_TITLE_TERMS: tuple[str, ...] = ("爐石戰記", "英雄戰場")
REQUIRED_TAGS: tuple[str, ...] = ("爐石戰記", "英雄戰場", "英雄戰場教學", "Hearthstone Battlegrounds")
SIMPLIFIED_TAGS: tuple[str, ...] = ("酒馆战棋", "炉石传说", "炉石", "战棋", "酒馆")
TRIBE_TERMS: tuple[str, ...] = (
    "野獸", "海盜", "惡魔", "機械", "龍", "魚人", "元素",
    "亡靈", "不死族", "娜迦", "納迦", "野豬人", "變異怪",
)
# official zhTW name -> colloquial spelling searchers actually type
TRIBE_ALIASES: dict[str, str] = {"亡靈": "不死族", "娜迦": "納迦"}


def search_keyword_issues(meta: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings) for the title/tags in an upload metadata dict."""
    title: str = meta.get("title", "") or ""
    tags: list[str] = list(meta.get("tags", []) or [])
    errors: list[str] = []
    warnings: list[str] = []

    missing_title = [t for t in REQUIRED_TITLE_TERMS if t not in title]
    if missing_title:
        errors.append(f"title lacks required search terms {missing_title}; use suffix「｜爐石戰記 英雄戰場」")

    tags_lower = {t.lower() for t in tags}
    missing_tags = [t for t in REQUIRED_TAGS if t.lower() not in tags_lower]
    if missing_tags:
        errors.append(f"tags lack required search terms {missing_tags}")

    simplified = [t for t in tags if any(s in t for s in SIMPLIFIED_TAGS)]
    if simplified:
        errors.append(f"tags contain simplified-Chinese terms with zero TW search volume {simplified}")

    if not any(t in title for t in TRIBE_TERMS):
        warnings.append(f"title has no tribe word ({'/'.join(TRIBE_TERMS)}); tribe words are the only intent-bearing autocomplete layer")

    text = title + " " + " ".join(tags)
    for official, colloquial in TRIBE_ALIASES.items():
        if official in text and colloquial not in tags:
            warnings.append(f"tags lack colloquial spelling「{colloquial}」for「{official}」(searchers type the colloquial form)")

    return errors, warnings

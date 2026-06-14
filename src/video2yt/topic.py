"""Discover Bilibili Hearthstone Battlegrounds topic candidates.

Pipeline:
  1. Parse a whitelist of (streamer_name, uid) pairs.
  2. For each streamer, fetch recent uploads via bilibili-api-python.
  3. Filter to last N days, duration ≥ min, exclude tutorial/intro titles.
  4. Sample danmaku from each surviving video.
  5. Ask Codex to extract {strategy, core_card, hero, trinket, summary,
     highlights} from title + description + danmaku samples.
  6. Group summaries into pairs (≥2 distinct streamers) along THREE axes:
     same core_card (流派), same hero (英雄), same trinket (饰品). The 英雄/饰品
     axes require the two picks to run *different* core_cards so they never
     just re-list a 流派 pair.
  7. Mark pairs whose subject already appears in output/<project>/
     intro_script.txt or done_topics.txt.
  8. Render to Markdown, one section per axis.

bilibili-api-python is async. The public functions in this module are sync
wrappers (asyncio.run) so callers and tests don't have to touch the event loop.

LLM summarization shells out to Codex (see image_gen.py's `generate_codex` for
the canonical pattern: tempdir + write instruction + read output file).
"""
from __future__ import annotations

import asyncio
import json
import re
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path

# Default heuristics. The tutorial regex aims at common 介绍/教程-style titles
# that we explicitly do NOT want — only 对战/实战 should pass.
DEFAULT_EXCLUDE_TITLE_RE = re.compile(
    r"教程|介绍|解读|盘点|集锦|教学|攻略|讲解|新手|开箱|抽卡|预告|采访|测评|"
    r"复盘|赛事|新版本爆料|更新|公告|采访|杂谈|聊天"
)
# Positive title filter — required because the whitelist now mixes BG-only
# streamers with general 炉石 streamers (瓦莉拉, 衣锦夜行, 安德罗妮…) whose
# recent uploads include constructed-mode and brawl content. Without this,
# Codex would be asked to extract a BG '流派' from videos that aren't BG.
DEFAULT_INCLUDE_TITLE_RE = re.compile(r"战棋|战旗")
DEFAULT_MIN_DURATION_SECONDS = 120  # 2 min — short-attack-form videos
                                    # (e.g. 景清's 5-7 min recap clips) count as
                                    # 对战 in this project's actual workflow.
DEFAULT_DAYS = 7
DEFAULT_DANMAKU_SAMPLE = 80
DEFAULT_PAGES_PER_STREAMER = 2


@dataclass(frozen=True)
class Streamer:
    name: str
    uid: int
    # True for general-炉石 channels (瓦莉拉, 衣锦夜行…) that mix BG with
    # constructed-mode uploads; the include-title filter is applied to those.
    # False (default) for BG-dedicated channels — those titles often skip
    # the redundant '战棋' keyword so the include filter would over-prune.
    is_mixed: bool = False


@dataclass
class VideoCandidate:
    bvid: str
    title: str
    description: str
    duration_seconds: int
    play_count: int
    created_ts: int
    streamer: str

    @property
    def url(self) -> str:
        return f"https://www.bilibili.com/video/{self.bvid}"


@dataclass
class VideoSummary:
    candidate: VideoCandidate
    strategy: str
    core_card: str
    summary: str
    highlights: str
    hero: str = ""      # the BG 英雄 played this game ("" if unclear)
    trinket: str = ""   # the signature 饰品 that defined the run ("" if none)


@dataclass
class TopicPair:
    strategy: str
    summaries: list[VideoSummary]
    is_already_done: bool
    done_marker: str | None  # path or done_topics entry that matched
    score: float = 0.0
    axis: str = "流派"  # 流派 | 英雄 | 饰品 — which dimension paired these two


def parse_streamers(path: Path) -> list[Streamer]:
    """Parse a '<name> <uid> [mixed]' per-line whitelist file.

    The optional 3rd token marks the streamer as a general-炉石 channel
    whose uploads include constructed mode; the include-title filter is
    applied to those. Default (no 3rd token) = BG-dedicated channel.

    Skips blank lines and `#` comments. Raises ValueError if the file is empty
    of valid entries — a CLI invocation with no streamers is almost certainly
    user error worth surfacing loudly.
    """
    if not path.exists():
        raise FileNotFoundError(f"streamers whitelist not found: {path}")
    streamers: list[Streamer] = []
    for lineno, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) not in (2, 3):
            raise ValueError(
                f"{path}:{lineno}: expected '<name> <uid> [mixed]', got {raw!r}"
            )
        name, uid_str, *rest = parts
        try:
            uid = int(uid_str)
        except ValueError:
            raise ValueError(f"{path}:{lineno}: uid must be int, got {uid_str!r}")
        if uid <= 0:
            raise ValueError(
                f"{path}:{lineno}: uid must be positive, got {uid}. "
                "Find UID in https://space.bilibili.com/<UID>."
            )
        is_mixed = False
        if rest:
            tag = rest[0].lower()
            if tag != "mixed":
                raise ValueError(
                    f"{path}:{lineno}: 3rd token must be 'mixed' or omitted, got {rest[0]!r}"
                )
            is_mixed = True
        streamers.append(Streamer(name=name, uid=uid, is_mixed=is_mixed))
    if not streamers:
        raise ValueError(
            f"{path} contains no valid streamer entries. "
            "Add lines like '炉石郭枫 12345' (the int after space.bilibili.com/)."
        )
    return streamers


def parse_done_topics(path: Path) -> set[str]:
    """One-strategy-per-line file. Returns empty set if file doesn't exist."""
    if not path.exists():
        return set()
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line and not line.startswith("#"):
            out.add(line)
    return out


def scan_done_corpus_from_output(output_root: Path) -> dict[str, str]:
    """Build a search corpus from past projects under `output_root`.

    Returns map: relative-project-path → search-blob.

    The blob is `<folder_name>\\n<intro_script.txt content>`. Annotation is then
    done with substring matching (see `annotate_already_done`) instead of
    pre-extracting strategies via regex — that approach was fragile (extracted
    noise like '零流派' from filler text and missed real strategies like
    '戒指龙' that have no 流/派/套路/阵容 suffix).

    Cross-script matches (Traditional ↔ Simplified) are intentionally NOT
    handled here — bridge them by listing the strategy in `done_topics.txt`.
    """
    found: dict[str, str] = {}
    if not output_root.exists():
        return found
    for script in output_root.glob("*/intro_script.txt"):
        rel = str(script.parent.relative_to(output_root.parent))
        body = script.read_text(encoding="utf-8", errors="ignore")
        found[rel] = f"{script.parent.name}\n{body}"
    return found


def parse_length_string(length: str) -> int:
    """Parse a Bilibili 'length' field ('MM:SS' or 'HH:MM:SS') to seconds."""
    parts = length.strip().split(":")
    if not all(p.isdigit() for p in parts):
        raise ValueError(f"unparseable length string: {length!r}")
    if len(parts) == 2:
        m, s = (int(x) for x in parts)
        return m * 60 + s
    if len(parts) == 3:
        h, m, s = (int(x) for x in parts)
        return h * 3600 + m * 60 + s
    raise ValueError(f"unparseable length string: {length!r}")


def load_credential_from_browser(browser: str = "chrome"):
    """Extract Bilibili cookies from a local browser (via yt_dlp) and build a
    Credential. Without this, anonymous calls hit HTTP 412 (B 站风控).

    All extraction failures are normalized to RuntimeError so the CLI's
    `main()` catch handles them cleanly. Common causes: browser not
    installed, no profile, Bilibili not logged in, cookie DB locked by an
    open browser, missing keyring on Linux.
    """
    import yt_dlp.cookies
    from bilibili_api import Credential
    try:
        jar = yt_dlp.cookies.extract_cookies_from_browser(browser)
    except Exception as exc:
        raise RuntimeError(
            f"could not load cookies from {browser!r}: {exc}. "
            "Hints: (1) close the browser if it's open (it locks the cookie "
            "DB); (2) try a different browser via --cookies-from-browser "
            "{firefox,safari,edge,chromium}; (3) skip auth via "
            "--cookies-from-browser '' (anonymous calls will hit B 站 412)."
        ) from exc
    pick: dict[str, str] = {}
    for c in jar:
        if c.domain.endswith("bilibili.com") and c.name in {
            "SESSDATA", "bili_jct", "buvid3", "buvid4", "DedeUserID",
        }:
            pick[c.name] = c.value
    if not pick.get("SESSDATA"):
        raise RuntimeError(
            f"no Bilibili SESSDATA cookie found in {browser}. "
            "Log into bilibili.com in that browser first, or skip auth via "
            "--cookies-from-browser ''."
        )
    return Credential(
        sessdata=pick.get("SESSDATA"),
        bili_jct=pick.get("bili_jct"),
        buvid3=pick.get("buvid3"),
        buvid4=pick.get("buvid4"),
        dedeuserid=pick.get("DedeUserID"),
    )


async def _async_fetch_videos(uid: int, pages: int, credential=None) -> list[dict]:
    from bilibili_api import user as bili_user
    u = bili_user.User(uid, credential=credential)
    out: list[dict] = []
    for pn in range(1, pages + 1):
        resp = await u.get_videos(pn=pn, ps=30)
        vlist = resp.get("list", {}).get("vlist", []) or []
        out.extend(vlist)
        if len(vlist) < 30:
            break
    return out


def fetch_recent_videos(
    streamer: Streamer,
    *,
    since_ts: int,
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    exclude_title_re: re.Pattern[str] = DEFAULT_EXCLUDE_TITLE_RE,
    include_title_re: re.Pattern[str] | None = None,
    pages: int = DEFAULT_PAGES_PER_STREAMER,
    credential=None,
) -> list[VideoCandidate]:
    """Fetch this streamer's recent uploads and return the surviving battle candidates.

    Filters: created_ts ≥ since_ts, duration ≥ min,
    title NOT matching exclude_title_re, title matching include_title_re
    (if provided — None disables the positive filter, which is the default
    because BG-dedicated channels often skip the redundant '战棋' keyword).
    The orchestrator (`run_topic`) sets this per-streamer based on
    `streamer.is_mixed`.
    """
    raw = asyncio.run(_async_fetch_videos(streamer.uid, pages, credential))
    out: list[VideoCandidate] = []
    for v in raw:
        created = int(v.get("created", 0))
        if created < since_ts:
            continue
        title = str(v.get("title", "")).strip()
        if not title or exclude_title_re.search(title):
            continue
        if include_title_re is not None and not include_title_re.search(title):
            continue
        try:
            duration = parse_length_string(str(v.get("length", "0:00")))
        except ValueError:
            continue
        if duration < min_duration_seconds:
            continue
        bvid = str(v.get("bvid", "")).strip()
        if not bvid:
            continue
        out.append(VideoCandidate(
            bvid=bvid,
            title=title,
            description=str(v.get("description", "")).strip(),
            duration_seconds=duration,
            play_count=int(v.get("play", 0)),
            created_ts=created,
            streamer=streamer.name,
        ))
    return out


async def _async_fetch_danmaku(bvid: str, credential=None) -> list[str]:
    from bilibili_api import video as bili_video
    v = bili_video.Video(bvid=bvid, credential=credential)
    danmakus = await v.get_danmakus(page_index=0)
    return [getattr(d, "text", "") for d in danmakus if getattr(d, "text", "")]


def fetch_danmaku_sample(
    bvid: str,
    sample_size: int = DEFAULT_DANMAKU_SAMPLE,
    *,
    credential=None,
) -> list[str]:
    """Fetch danmaku for a video and return up to `sample_size` evenly-spaced texts.

    Even sampling preserves coverage across the timeline (early-game vs late-game
    chat differ a lot for BG matches).
    """
    all_texts = asyncio.run(_async_fetch_danmaku(bvid, credential))
    if len(all_texts) <= sample_size:
        return all_texts
    step = len(all_texts) / sample_size
    return [all_texts[int(i * step)] for i in range(sample_size)]


def _build_codex_input(
    candidates: list[VideoCandidate],
    danmaku_by_bvid: dict[str, list[str]],
) -> dict:
    return {
        "videos": [
            {
                "bvid": c.bvid,
                "title": c.title,
                "description": c.description[:500],
                "danmaku": danmaku_by_bvid.get(c.bvid, [])[:DEFAULT_DANMAKU_SAMPLE],
            }
            for c in candidates
        ]
    }


CODEX_INSTRUCTION = """\
Read the JSON file at ./input.json. It contains a list of Hearthstone \
Battlegrounds (炉石战旗) gameplay videos in Chinese. For each video object, \
produce one summary with these exact string fields:

  - bvid: copy from input.
  - strategy: the canonical comp / 流派 name in 2-6 Chinese characters \
(e.g. "戒指龙流", "九鸡野兽", "背靠背流", "火车头流"). Pick ONE; pick the most \
specific name shared across title + danmaku.
  - core_card: ONE core card name (Chinese).
  - hero: the Battlegrounds HERO the streamer played this game (英雄), in \
Chinese (e.g. "玛维", "克罗米", "提克特斯", "苔丝·格雷迈恩"). Use "" if the hero \
is not clearly identifiable from the title + danmaku.
  - trinket: the ONE signature 饰品 (大/小饰品 / trinket) that defined this run, \
in Chinese (e.g. "废品回收", "复生", "透镜"). Use "" if no single 饰品 stands out.
  - summary: ONE sentence ≤40 Chinese characters describing what the streamer did.
  - highlights: ONE sentence ≤40 Chinese characters describing what NEW idea \
or twist this video shows for that strategy (different饰品/英雄/build path).

Write the result to ./output.json as a JSON array (one object per input video, \
same order). Do NOT print anything else. Do NOT ask clarifying questions.
"""


def summarize_with_codex(
    candidates: list[VideoCandidate],
    danmaku_by_bvid: dict[str, list[str]],
    *,
    timeout: int = 600,
) -> list[VideoSummary]:
    """Run one batched Codex call to summarize all candidates.

    Same tempdir-write pattern as image_gen.generate_codex (avoids stdout-parsing
    fragility and stays within Codex sandbox defaults).
    """
    if not candidates:
        return []
    payload = _build_codex_input(candidates, danmaku_by_bvid)
    by_bvid = {c.bvid: c for c in candidates}

    with tempfile.TemporaryDirectory(prefix="codex_topic_") as tmpdir:
        tmp = Path(tmpdir)
        (tmp / "input.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        cmd = [
            "codex", "exec",
            "--sandbox", "workspace-write",
            "--cd", str(tmp),
            "--skip-git-repo-check",
            CODEX_INSTRUCTION,
        ]
        print(
            f"[topic] codex exec on {len(candidates)} candidate(s) "
            f"(timeout={timeout}s)",
            file=sys.stderr,
        )
        try:
            subprocess.run(cmd, check=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            raise RuntimeError(
                f"codex exec timed out after {timeout}s. "
                "Try a smaller batch or increase --codex-timeout."
            )
        except subprocess.CalledProcessError as exc:
            raise RuntimeError(
                f"codex exec failed (exit {exc.returncode}). "
                "Re-run interactively with the same prompt to debug."
            ) from exc

        out_path = tmp / "output.json"
        if not out_path.exists():
            raise RuntimeError(
                f"codex finished but {out_path} does not exist. "
                "Codex may have written to a different name; re-run interactively."
            )
        try:
            raw = json.loads(out_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"codex output is not valid JSON: {exc}")

    if not isinstance(raw, list):
        raise RuntimeError(f"codex output must be a JSON array; got {type(raw).__name__}")

    out: list[VideoSummary] = []
    for entry in raw:
        bvid = entry.get("bvid")
        cand = by_bvid.get(bvid)
        if cand is None:
            continue
        out.append(VideoSummary(
            candidate=cand,
            strategy=str(entry.get("strategy", "")).strip(),
            core_card=str(entry.get("core_card", "")).strip(),
            summary=str(entry.get("summary", "")).strip(),
            highlights=str(entry.get("highlights", "")).strip(),
            hero=str(entry.get("hero", "")).strip(),
            trinket=str(entry.get("trinket", "")).strip(),
        ))
    return out


def _best_distinct_pair(
    group: list[VideoSummary], *, require_distinct_core_card: bool
) -> list[VideoSummary] | None:
    """Pick a high-traction pair of summaries from DISTINCT streamers.

    With ``require_distinct_core_card`` the two picks must also run two KNOWN,
    *different* core_cards — used for the 英雄/饰品 axes so a pair surfaced there
    is genuinely "same hero/trinket, two *different* builds" and never re-lists a
    流派 (same-core_card) pair. A blank core_card is "unknown", NOT "different":
    a pair where either side's comp is unidentified can't support the "不同打法"
    claim, so it is rejected (and never emitted with an unknown core card).

    Scans every (anchor, partner) candidate in play-count order (highest first)
    and returns the first that satisfies the constraints, so the higher-played
    summary leads the pair. Crucially it does NOT anchor only on the single
    highest-play summary: when that top video can pair only with same-streamer
    or (for the distinct-core_card axes) same/blank-core_card entries, a valid
    pair built from lower-play summaries still exists and must not be silently
    dropped. Returns None only when no pair satisfies the constraints.
    """
    ordered = sorted(group, key=lambda x: x.candidate.play_count, reverse=True)
    for i, anchor in enumerate(ordered):
        anchor_card = anchor.core_card.strip()
        for partner in ordered[i + 1:]:
            if partner.candidate.streamer == anchor.candidate.streamer:
                continue
            if require_distinct_core_card:
                partner_card = partner.core_card.strip()
                if not anchor_card or not partner_card or \
                        anchor_card == partner_card:
                    continue
            return [anchor, partner]
    return None


def _group_by_key(
    summaries: list[VideoSummary],
    key_fn,
    axis: str,
    *,
    label_from_strategy: bool,
    require_distinct_core_card: bool = False,
) -> list[TopicPair]:
    """Bucket summaries by ``key_fn`` and emit one TopicPair per bucket that
    has a valid distinct-streamer pair. Blank keys are skipped.

    ``label_from_strategy`` controls the displayed name: the 流派 axis uses the
    higher-played pick's strategy (Codex returns the comp name there); the
    英雄/饰品 axes use the bucket key (the hero/trinket name) directly.
    """
    buckets: dict[str, list[VideoSummary]] = {}
    for s in summaries:
        key = key_fn(s).strip()
        if not key:
            continue
        buckets.setdefault(key, []).append(s)
    out: list[TopicPair] = []
    for key, group in buckets.items():
        picked = _best_distinct_pair(
            group, require_distinct_core_card=require_distinct_core_card
        )
        if picked is None:
            continue
        label = (picked[0].strategy or key) if label_from_strategy else key
        out.append(TopicPair(
            strategy=label,
            summaries=picked,
            is_already_done=False,
            done_marker=None,
            axis=axis,
        ))
    return out


def group_pairs(summaries: list[VideoSummary]) -> list[TopicPair]:
    """Group by `core_card`. Keep groups with ≥2 distinct streamers.

    Why core_card not strategy: in practice Codex returns slightly different
    strategy names for the same comp across videos (e.g. '戒指龙流' vs
    '亡灵戒指龙'), but the core_card is the actual pivotal Hearthstone card
    and stays stable. Within a group, take the 2 highest-played summaries
    from distinct streamers; the displayed `strategy` field for the pair is
    that of the higher-played pick.
    """
    return _group_by_key(
        summaries, lambda s: s.core_card, "流派", label_from_strategy=True,
    )


def group_hero_pairs(summaries: list[VideoSummary]) -> list[TopicPair]:
    """Pair two streamers who played the same HERO with *different* comps.

    Same hero + same core_card is already a 流派 pair, so we require distinct
    core_cards here — the value of a 英雄 topic is contrasting two builds on one
    hero, not re-surfacing a comp the 流派 axis already caught.
    """
    return _group_by_key(
        summaries, lambda s: s.hero, "英雄",
        label_from_strategy=False, require_distinct_core_card=True,
    )


def group_trinket_pairs(summaries: list[VideoSummary]) -> list[TopicPair]:
    """Pair two streamers who built around the same 饰品 with *different* comps.

    Distinct-core_card requirement is the same as `group_hero_pairs`: a 饰品
    topic is worthwhile when it shows two different ways to abuse one trinket.
    """
    return _group_by_key(
        summaries, lambda s: s.trinket, "饰品",
        label_from_strategy=False, require_distinct_core_card=True,
    )


def _norm_strategy(s: str) -> str:
    """Strip 流/派 suffixes — '戒指龙流' and '戒指龙' should compare equal."""
    return s.replace("流", "").replace("派", "").strip()


def _pair_needles(pair: TopicPair) -> list[str]:
    """Normalized substrings used to decide whether a pair is already done.

    流派 axis: the comp name + both core cards (the comp is the subject).
    英雄/饰品 axis: only the hero/trinket name — the subject is that hero or
    trinket, so we must NOT mark it done just because one of the two contrasting
    comps was covered before.

    Min-length 2 drops one-character needles like '流' that would match
    everywhere.
    """
    if pair.axis == "流派":
        raws = (
            pair.strategy,
            pair.summaries[0].core_card,
            pair.summaries[1].core_card,
        )
    else:
        raws = (pair.strategy,)
    needles: list[str] = []
    for raw in raws:
        n = _norm_strategy(raw)
        if len(n) >= 2:
            needles.append(n)
    return needles


def annotate_already_done(
    pairs: list[TopicPair],
    done_corpus: dict[str, str],
    done_from_file: set[str],
) -> None:
    """In-place: mark each pair as already-done if its subject (see
    `_pair_needles`) appears in any past project's corpus blob, or in the
    manual done list.

    Matching is substring (case-sensitive, no T↔S conversion). For cross-script
    cases, list the strategy explicitly in `done_topics.txt`.
    """
    for pair in pairs:
        needles = _pair_needles(pair)
        if not needles:
            continue
        for project, blob in done_corpus.items():
            if any(needle in blob for needle in needles):
                pair.is_already_done = True
                pair.done_marker = f"{project}/"
                break
        if pair.is_already_done:
            continue
        for done_strat in done_from_file:
            done_n = _norm_strategy(done_strat)
            if not done_n:
                continue
            if any(needle in done_n or done_n in needle for needle in needles):
                pair.is_already_done = True
                pair.done_marker = f"done_topics: {done_strat}"
                break


def score_pair(pair: TopicPair) -> float:
    """Heuristic ranking score. Higher = better topic.

    Components:
      - log10(play1 * play2): rewards high-traction matches.
      - +2.0 if novel (not already done).
    """
    import math
    plays = max(1, pair.summaries[0].candidate.play_count) * \
            max(1, pair.summaries[1].candidate.play_count)
    score = math.log10(plays)
    if not pair.is_already_done:
        score += 2.0
    return score


_AXIS_ORDER = ["流派", "英雄", "饰品"]
_AXIS_SECTION_TITLE = {
    "流派": "## 流派配对（同核心卡）",
    "英雄": "## 英雄配对（同英雄 · 不同打法）",
    "饰品": "## 饰品配对（同饰品 · 不同打法）",
}


def _render_pair(lines: list[str], i: int, pair: TopicPair) -> None:
    marker = f" [新{pair.axis} ✨]" if not pair.is_already_done \
        else f" [已做过 → {pair.done_marker}]"
    lines.append(f"### #{i} {pair.axis}：{pair.strategy}{marker}  · 分数 {pair.score:.2f}")
    lines.append("")
    for s in pair.summaries:
        c = s.candidate
        mins = c.duration_seconds // 60
        secs = c.duration_seconds % 60
        plays = f"{c.play_count/10000:.1f}万" if c.play_count >= 10000 \
            else str(c.play_count)
        extra = []
        if s.hero:
            extra.append(f"英雄：{s.hero}")
        if s.trinket:
            extra.append(f"饰品：{s.trinket}")
        extra_str = (" · " + " · ".join(extra)) if extra else ""
        lines.append(f"- **{c.streamer}**: [{c.title}]({c.url})")
        lines.append(
            f"  - 播放 {plays} · 时长 {mins}:{secs:02d} · 核心卡：{s.core_card}{extra_str}"
        )
        lines.append(f"  - 概要：{s.summary}")
        lines.append(f"  - 亮点：{s.highlights}")
    lines.append("")


def render_markdown(pairs: list[TopicPair], window_days: int, generated_at: str) -> str:
    """Format the final report as Markdown, one section per axis (流派/英雄/饰品)."""
    lines: list[str] = []
    lines.append(f"# 选题候选 · {generated_at} (近 {window_days} 天)")
    lines.append("")
    if not pairs:
        lines.append("_本期没有任何流派被两位主播同时打过。可放宽时间窗口或扩充白名单。_")
        return "\n".join(lines) + "\n"
    lines.append(
        f"共 {len(pairs)} 对配对（流派 / 英雄 / 饰品三维度，各维度内按热度+新颖度排序）"
    )
    lines.append("")
    by_axis: dict[str, list[TopicPair]] = {a: [] for a in _AXIS_ORDER}
    for p in pairs:
        by_axis.setdefault(p.axis, []).append(p)
    for axis in _AXIS_ORDER:
        axis_pairs = by_axis.get(axis) or []
        if not axis_pairs:
            continue
        lines.append(_AXIS_SECTION_TITLE.get(axis, f"## {axis}配对"))
        lines.append("")
        for i, pair in enumerate(
            sorted(axis_pairs, key=lambda p: p.score, reverse=True), 1
        ):
            _render_pair(lines, i, pair)
    return "\n".join(lines) + "\n"


def _write_and_print_report(report_path: Path, markdown: str) -> None:
    """Write the report to disk AND echo it to stdout.

    The full link-bearing report (every candidate with both bilibili URLs) must
    reach the chat verbatim; the agent relays this block and only LAYERS
    done/patch annotations on top. It must never hand-author a condensed
    candidate list (that is how source URLs get dropped — see the
    topic-summary link rule). Logs elsewhere go to stderr; this goes to stdout.
    """
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(markdown, encoding="utf-8")
    print(f"[topic] wrote {report_path}", file=sys.stderr)
    print("\n===== CHAT-READY REPORT (relay verbatim; do not retype candidates) =====")
    print(markdown)
    print("===== END CHAT-READY REPORT =====")


def run_topic(
    *,
    streamers: list[Streamer],
    days: int,
    output_root: Path,
    done_topics_file: Path | None,
    report_path: Path,
    min_duration_seconds: int = DEFAULT_MIN_DURATION_SECONDS,
    danmaku_sample_size: int = DEFAULT_DANMAKU_SAMPLE,
    pages_per_streamer: int = DEFAULT_PAGES_PER_STREAMER,
    codex_timeout: int = 600,
    now_ts: int | None = None,
    credential=None,
) -> Path:
    """Top-level orchestrator. Returns the report path.

    Side effects: writes the markdown report. Logs progress to stderr.
    """
    if now_ts is None:
        now_ts = int(time.time())
    since_ts = now_ts - days * 86400

    print(
        f"[topic] window: last {days} days · {len(streamers)} streamer(s)"
        f" · auth={'on' if credential else 'off'}",
        file=sys.stderr,
    )
    candidates: list[VideoCandidate] = []
    for s in streamers:
        try:
            cs = fetch_recent_videos(
                s,
                since_ts=since_ts,
                min_duration_seconds=min_duration_seconds,
                include_title_re=DEFAULT_INCLUDE_TITLE_RE if s.is_mixed else None,
                pages=pages_per_streamer,
                credential=credential,
            )
        except Exception as exc:
            print(f"[topic] skipping {s.name} (uid={s.uid}): {exc}", file=sys.stderr)
            continue
        print(f"[topic]   {s.name}: {len(cs)} battle candidate(s)", file=sys.stderr)
        candidates.extend(cs)

    if not candidates:
        print("[topic] no candidates; writing empty report", file=sys.stderr)
        _write_and_print_report(
            report_path,
            render_markdown(
                [],
                window_days=days,
                generated_at=time.strftime("%Y-%m-%d", time.localtime(now_ts)),
            ),
        )
        return report_path

    print(f"[topic] sampling danmaku for {len(candidates)} video(s)", file=sys.stderr)
    danmaku_by_bvid: dict[str, list[str]] = {}
    for c in candidates:
        try:
            danmaku_by_bvid[c.bvid] = fetch_danmaku_sample(
                c.bvid, danmaku_sample_size, credential=credential,
            )
        except Exception as exc:
            print(f"[topic]   {c.bvid} danmaku fail ({exc}); using []", file=sys.stderr)
            danmaku_by_bvid[c.bvid] = []

    print(f"[topic] summarizing via codex", file=sys.stderr)
    summaries = summarize_with_codex(candidates, danmaku_by_bvid, timeout=codex_timeout)
    print(f"[topic]   {len(summaries)} summary record(s)", file=sys.stderr)

    comp_pairs = group_pairs(summaries)
    hero_pairs = group_hero_pairs(summaries)
    trinket_pairs = group_trinket_pairs(summaries)
    pairs = comp_pairs + hero_pairs + trinket_pairs
    print(
        f"[topic] grouped: {len(comp_pairs)} 流派 / {len(hero_pairs)} 英雄 / "
        f"{len(trinket_pairs)} 饰品 pair(s) before annotation",
        file=sys.stderr,
    )

    done_corpus = scan_done_corpus_from_output(output_root)
    done_from_file = parse_done_topics(done_topics_file) if done_topics_file else set()
    annotate_already_done(pairs, done_corpus, done_from_file)
    for pair in pairs:
        pair.score = score_pair(pair)

    _write_and_print_report(
        report_path,
        render_markdown(
            pairs,
            window_days=days,
            generated_at=time.strftime("%Y-%m-%d", time.localtime(now_ts)),
        ),
    )
    return report_path

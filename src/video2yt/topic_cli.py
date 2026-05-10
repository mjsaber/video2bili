"""CLI for video2yt-topic: discover paired Hearthstone Battlegrounds topic candidates."""

import argparse
import sys
import time
from pathlib import Path

from video2yt import topic


def _log(msg: str) -> None:
    print(f"[video2yt-topic] {msg}", file=sys.stderr)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-topic",
        description=(
            "Search Bilibili for recent battle-style videos from a whitelist of "
            "Hearthstone Battlegrounds streamers, summarize each via Codex, and "
            "report 流派 pairs (two streamers playing the same comp) as topic "
            "candidates. Writes a Markdown report under output/topics/."
        ),
    )
    parser.add_argument(
        "--days",
        type=int,
        default=topic.DEFAULT_DAYS,
        help=f"Recency window in days (default {topic.DEFAULT_DAYS}).",
    )
    parser.add_argument(
        "--whitelist",
        type=Path,
        default=Path("assets/topic/streamers.txt"),
        help="Streamer whitelist path. Default: assets/topic/streamers.txt",
    )
    parser.add_argument(
        "--done-topics",
        type=Path,
        default=Path("assets/topic/done_topics.txt"),
        help=(
            "Optional manual list of strategies you've already covered. "
            "Augments the auto-scan of output/<project>/intro_script.txt. "
            "Default: assets/topic/done_topics.txt (empty file shipped)."
        ),
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=Path("output"),
        help="Root containing past <project>/intro_script.txt files. Default: output/",
    )
    parser.add_argument(
        "-o",
        "--report",
        type=Path,
        default=None,
        help="Output Markdown path. Default: output/topics/<YYYY-MM-DD>.md",
    )
    parser.add_argument(
        "--min-duration",
        type=int,
        default=topic.DEFAULT_MIN_DURATION_SECONDS,
        help=(
            "Minimum duration in seconds to consider a video a 对战 (default "
            f"{topic.DEFAULT_MIN_DURATION_SECONDS}). Filters out shorts/intros."
        ),
    )
    parser.add_argument(
        "--danmaku-sample",
        type=int,
        default=topic.DEFAULT_DANMAKU_SAMPLE,
        help=(
            "Number of danmaku to sample per video as Codex context "
            f"(default {topic.DEFAULT_DANMAKU_SAMPLE})."
        ),
    )
    parser.add_argument(
        "--pages",
        type=int,
        default=topic.DEFAULT_PAGES_PER_STREAMER,
        help=(
            "Pages of recent uploads to fetch per streamer "
            f"(default {topic.DEFAULT_PAGES_PER_STREAMER}, 30 entries/page)."
        ),
    )
    parser.add_argument(
        "--codex-timeout",
        type=int,
        default=600,
        help="Seconds to wait for the codex summarization batch (default 600).",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    streamers = topic.parse_streamers(args.whitelist)
    _log(f"loaded {len(streamers)} streamer(s) from {args.whitelist}")

    if args.report is None:
        date_str = time.strftime("%Y-%m-%d")
        report_path = Path("output") / "topics" / f"{date_str}.md"
    else:
        report_path = args.report

    return topic.run_topic(
        streamers=streamers,
        days=args.days,
        output_root=args.output_root,
        done_topics_file=args.done_topics,
        report_path=report_path,
        min_duration_seconds=args.min_duration,
        danmaku_sample_size=args.danmaku_sample,
        pages_per_streamer=args.pages,
        codex_timeout=args.codex_timeout,
    )


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1

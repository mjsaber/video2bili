"""``video2yt-prefetch`` — serial pre-download of Stage 1 sources.

Fills the same Stage 1 fetch cache that ``video2yt-fetch`` / Step 6 use,
ahead of time, so the bandwidth-heavy yt-dlp download overlaps the
bandwidth-free Step 1–5 intro work. Serial by design — parallel downloads
trigger yt-dlp merger-hiccup truncation. See
docs/superpowers/specs/2026-05-29-prefetch-cli-design.md.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from video2yt import fetch
from video2yt.download import TruncatedDownloadError
from video2yt.fetch_cli import preflight

MAX_ATTEMPTS = 3


def _log(msg: str) -> None:
    print(f"[video2yt-prefetch] {msg}", file=sys.stderr)


class PrefetchResolutionError(RuntimeError):
    """Downloaded source resolution is below the requested quality floor."""


@dataclass
class PrefetchOutcome:
    url: str
    bv_id: str
    title: str
    width: int
    height: int
    from_cache: bool
    elapsed: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-prefetch",
        description=(
            "Serially pre-download one or more Bilibili sources into the "
            "Stage 1 fetch cache (mp4 + danmaku XML), so Step 6 hits a warm "
            "cache. Serial by design — parallel downloads trigger yt-dlp "
            "merger-hiccup truncation. Background it with a trailing '&'."
        ),
    )
    parser.add_argument("urls", nargs="+", help="One or more Bilibili video URLs")
    parser.add_argument(
        "-o", "--temp-dir", type=Path, default=Path("./temp"),
        help="Parent temp directory; per-segment subfolders created inside (default: ./temp)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=1080, choices=[1080, 720, 480],
        help="Max video quality; sources below this fail-fast (default: 1080)",
    )
    parser.add_argument(
        "--codec", default="h264", choices=["h264", "h265", "auto"],
        help="Video codec preference (default: h264)",
    )
    parser.add_argument(
        "-b", "--browser", default="chrome",
        help="Browser to read cookies from (default: chrome)",
    )
    return parser.parse_args(argv)


def _quarantine_lowres(result: fetch.FetchResult) -> None:
    """Rename the cached low-res video + danmaku XML with a `.lowres` suffix.

    fetch_and_build writes the files to the shared Stage 1 cache before
    returning, so a bare fail-fast would leave a complete, AV-consistent
    low-res file that download.fetch's cache probe (`<bv>.mp4`, `<bv>*.xml`)
    would silently serve to Step 6 until merge fails. Renaming past those
    globs forces a re-download. Mirrors download.fetch's `.broken` quarantine.
    """
    for path in (result.raw_video, result.danmaku_xml):
        if path.exists():
            path.rename(path.with_name(path.name + ".lowres"))


def _prefetch_one(
    url: str, temp_dir: Path, quality: int, codec: str, browser: str
) -> PrefetchOutcome:
    """Prefetch a single URL into the Stage 1 cache. Raises on failure.

    Truncated yt-dlp merges (TruncatedDownloadError) are retried up to
    MAX_ATTEMPTS — re-calling fetch_and_build re-downloads, because
    download.fetch's cache probe quarantines the prior truncated file to
    .broken and falls through to a fresh yt-dlp run.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = fetch.fetch_and_build(
                url=url, temp_dir=temp_dir, quality=quality,
                codec=codec, browser=browser,
            )
        except TruncatedDownloadError:
            if attempt == MAX_ATTEMPTS:
                raise
            _log(f"  truncated merge, retry {attempt + 1}/{MAX_ATTEMPTS}")
            continue
        if result.info.height < quality:
            _quarantine_lowres(result)
            raise PrefetchResolutionError(
                f"{result.bv_id}: got {result.info.width}x{result.info.height}, "
                f"requested <={quality}p (VIP-locked source? merge needs "
                f"1920x1080). Quarantined cached files to *.lowres; re-run "
                f"after fixing the source."
            )
        return PrefetchOutcome(
            url=url,
            bv_id=result.bv_id,
            title=result.metadata.get("title") or result.bv_id,
            width=result.info.width,
            height=result.info.height,
            from_cache=result.from_cache,
            elapsed=result.elapsed,
        )


def run(args: argparse.Namespace) -> list[PrefetchOutcome]:
    preflight()
    done: list[PrefetchOutcome] = []
    for url in args.urls:
        _log(f"prefetching {url}")
        outcome = _prefetch_one(
            url, args.temp_dir, args.quality, args.codec, args.browser
        )
        tag = "cached" if outcome.from_cache else "downloaded"
        _log(
            f"  ok bv={outcome.bv_id} {outcome.width}x{outcome.height} "
            f"{tag} ({outcome.elapsed:.1f}s) {outcome.title!r}"
        )
        done.append(outcome)
    _log(f"summary: {len(done)}/{len(args.urls)} prefetched")
    return done


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except KeyboardInterrupt:
        _log("cancelled")
        return 130
    except subprocess.CalledProcessError as e:
        tool = e.cmd[0] if e.cmd else "subprocess"
        _log(f"error: {tool} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        # fail-fast: PrefetchResolutionError + TruncatedDownloadError are RuntimeError
        _log(f"error: {e}")
        return 1

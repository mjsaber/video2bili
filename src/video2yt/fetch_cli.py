"""``video2yt-fetch`` — Stage 1 entry point of the per-segment pipeline.

Wraps ``fetch.fetch_and_build`` with the standard CLI shape
(``preflight`` / ``parse_args`` / ``run`` / ``main``).
See ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §7
``video2yt-fetch`` for the contract.
"""

import argparse
import importlib
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import fetch


def _log(msg: str) -> None:
    print(f"[video2yt-fetch] {msg}", file=sys.stderr)


def preflight() -> None:
    """Fail fast if required external dependencies are missing."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: brew install ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "ffprobe not found in PATH (usually ships with ffmpeg)"
        )
    if shutil.which("yt-dlp") is None:
        raise RuntimeError(
            "yt-dlp not found in PATH. Install via: uv tool install yt-dlp"
        )
    try:
        mod = importlib.import_module("biliass")
        if mod is None:
            raise ImportError("biliass is None")
    except ImportError as e:
        raise RuntimeError(
            "biliass not available. Reinstall with: uv sync"
        ) from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-fetch",
        description=(
            "Stage 1 of the per-segment pipeline: download Bilibili video "
            "+ raw danmaku XML via yt-dlp, then build the un-cut danmaku "
            "ASS via biliass. Output lives in a per-segment subfolder of "
            "the temp directory."
        ),
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument(
        "-o", "--temp-dir", type=Path, default=Path("./temp"),
        help="Parent temp directory; per-segment subfolder is created inside (default: ./temp)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=1080, choices=[1080, 720, 480],
        help="Max video quality (default: 1080)",
    )
    parser.add_argument(
        "--codec", default="h264", choices=["h264", "h265", "auto"],
        help="Video codec preference (default: h264 — most compatible)",
    )
    parser.add_argument(
        "-b", "--browser", default="chrome",
        help="Browser to read cookies from (default: chrome)",
    )
    parser.add_argument(
        "--font-face", default="Hiragino Sans GB",
        help="Font family for rendered danmaku (default: Hiragino Sans GB)",
    )
    parser.add_argument(
        "--font-size", type=int, default=None,
        help=(
            "Font size in pixels for standard (size=25) danmaku. "
            "Default: auto — video_height * 25 / 540 (Bilibili native)."
        ),
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> fetch.FetchResult:
    preflight()
    _log(f"fetching {args.url}")
    result = fetch.fetch_and_build(
        url=args.url,
        temp_dir=args.temp_dir,
        quality=args.quality,
        codec=args.codec,
        browser=args.browser,
        font_face=args.font_face,
        font_size=args.font_size,
    )
    cache_tag = " (cached)" if result.from_cache else ""
    _log(
        f"bv={result.bv_id} title={result.metadata.get('title')!r} "
        f"video={result.info.width}x{result.info.height} {result.info.duration:.1f}s{cache_tag}"
    )
    _log(f"danmaku: {result.n_danmaku} lines -> {result.danmaku_ass.name}")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        result = run(args)
        _log(f"success: {result.raw_video} (elapsed {result.elapsed:.1f}s)")
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
        _log(f"error: {e}")
        return 1

"""``video2yt-music-mix`` — Stage 4 entry point.

Builds the CC0 music bed for a per-segment raw mp4. See ``music_mix.render``
for the contract.

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §7
``video2yt-music-mix``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import music_mix


def _log(msg: str) -> None:
    print(f"[video2yt-music-mix] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: brew install ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "ffprobe not found in PATH (usually ships with ffmpeg)"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-music-mix",
        description=(
            "Stage 4 of the per-segment pipeline: build a stitched CC0 "
            "music bed that matches the raw mp4's duration, plus the "
            "attribution lines for the YouTube description."
        ),
    )
    parser.add_argument(
        "raw_mp4", type=Path,
        help="The <bv>.mp4 produced by video2yt-fetch.",
    )
    parser.add_argument(
        "--crossfade", type=float, default=2.0,
        help="Crossfade length in seconds between consecutive tracks (default 2.0).",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Seed the track-shuffle for reproducible beds.",
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Bypass cache and rebuild the bed even if outputs are present.",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> music_mix.MusicMixResult:
    preflight()
    if not args.raw_mp4.exists():
        raise FileNotFoundError(f"raw mp4 not found: {args.raw_mp4}")
    _log(f"target: {args.raw_mp4.name}")
    result = music_mix.render(
        raw_mp4=args.raw_mp4,
        crossfade=args.crossfade,
        seed=args.seed,
        force=args.force,
    )
    cache_tag = " (cached)" if result.from_cache else ""
    _log(
        f"bed: {result.bed_wav.name}{cache_tag}  "
        f"duration={result.duration_seconds:.1f}s  tracks={result.tracks_used}"
    )
    _log(f"credits: {result.credits_txt.name}")
    return result


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        result = run(args)
        _log(
            f"success: {result.bed_wav}  elapsed={result.elapsed:.1f}s  "
            f"from_cache={result.from_cache}"
        )
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
    except FileNotFoundError as e:
        _log(f"error: {e}")
        return 1
    except (ValueError, RuntimeError) as e:
        _log(f"error: {e}")
        return 2

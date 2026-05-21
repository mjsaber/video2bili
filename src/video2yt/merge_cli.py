"""CLI entry point for ``video2yt-merge``.

Concatenates multiple 1920x1080 30fps h264 MP4 segments into one video with
per-segment loudness-normalized audio, chapter markers embedded into the MP4,
and a YouTube chapters text file.
"""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import merge, validate
from video2yt.cli import _sanitize_title


def _log(msg: str) -> None:
    print(f"[video2yt-merge] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. brew install ffmpeg")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-merge",
        description=(
            "Concatenate multiple 1920x1080 h264 MP4 segments into one video "
            "with -14 LUFS audio, chapter markers embedded into the MP4, "
            "and a YouTube chapters text file."
        ),
    )
    parser.add_argument(
        "--segment", type=Path, action="append", default=[],
        help="Input video segment (mp4). Must be 1920x1080 30fps h264. Repeatable.",
    )
    parser.add_argument(
        "--label", action="append", default=[],
        help="Chapter label for the corresponding --segment. Repeatable, must pair with --segment.",
    )
    parser.add_argument(
        "--title", required=True,
        help="Output video title. Used for output filename and chapters file.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output MP4 file path. Default: <first_segment_parent>/<sanitized_title>.mp4",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()

    if len(args.segment) != len(args.label):
        raise ValueError(
            f"--segment ({len(args.segment)}) and --label ({len(args.label)}) "
            f"counts must match"
        )
    if len(args.segment) < 3:
        raise ValueError(
            "at least 3 segments are required to merge: each segment becomes one "
            "chapter, and YouTube only renders chapter segmentation with 3+ chapters"
        )

    segments = [
        merge.Segment(path=p, label=lbl)
        for p, lbl in zip(args.segment, args.label)
    ]

    _log(f"validating {len(segments)} segments (strict 1920x1080 30fps h264)")
    merge.validate_segments_strict(segments)

    total = sum(s.duration for s in segments)
    _log(f"total duration: {total:.2f}s ({len(segments)} segments)")
    for s in segments:
        _log(f"  - {s.path.name}: {s.duration:.2f}s — {s.label!r}")

    # Resolve output path
    if args.output:
        output_path = args.output
    else:
        safe_title = _sanitize_title(args.title)
        output_path = segments[0].path.parent / f"{safe_title}.mp4"

    _log(f"rendering -> {output_path}")
    merge_inputs = merge.MergeInputs(segments=segments, title=args.title)
    merge.render(merge_inputs, output_path)

    # Validate output
    _log("validating output")
    info = validate.probe(output_path)
    if not info.has_video or info.vcodec != "h264":
        raise ValueError(f"output vcodec {info.vcodec!r} != h264")
    if info.width != 1920 or info.height != 1080:
        raise ValueError(f"output resolution {info.width}x{info.height} != 1920x1080")
    if abs(info.duration - total) > 1.0:
        raise ValueError(
            f"output duration {info.duration:.2f}s differs from expected {total:.2f}s by > 1s"
        )

    chapters_path = output_path.parent / f"{output_path.stem}_chapters.txt"
    _log(f"chapters: {chapters_path}")
    _log(f"success: {output_path}")
    return output_path


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except subprocess.CalledProcessError as e:
        _log(f"error: {(e.cmd[0] if e.cmd else 'subprocess')} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1

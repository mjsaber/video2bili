"""``video2yt-burn`` — Stage 5 entry point.

Wraps ``burn.render`` with the full T6 single-pass burn shape: danmaku
ASS + cleaned subtitle ASS + speech+CC0-bed amix + optional cuts/speed
in one ffmpeg invocation.

Inputs are read from a single ``<dir>/`` containing (per the spec §4
Stage 5 contract):
  - ``<bv>.mp4``
  - ``<bv>.danmaku.ass``  (un-cut; burn rewrites ephemerally if --cut is set)
  - ``<bv>/speech.wav``           (when --no-music-swap is NOT set)
  - ``<bv>/speech.cleaned.ass``   (when --no-subtitle is NOT set)
  - ``<bv>.music_bed.wav``        (when --no-music-swap is NOT set)

Spec: ``docs/superpowers/specs/2026-05-24-step6-restructure.md`` §4
Stage 5 + §6 + §7 ``video2yt-burn``.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import burn, cuts


def _log(msg: str) -> None:
    print(f"[video2yt-burn] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: brew install ffmpeg "
            "(must include libass — see CLAUDE.md 'Known gotchas')."
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-burn",
        description=(
            "Stage 5 of the per-segment pipeline: a single ffmpeg pass "
            "that burns danmaku ASS + cleaned subtitle ASS into the video "
            "AND mixes speech.wav + CC0 music_bed.wav into the audio, "
            "optionally applying --cut and --speed."
        ),
    )
    parser.add_argument(
        "temp_dir", type=Path,
        help="Per-segment temp dir containing <bv>.mp4 and friends.",
    )
    parser.add_argument(
        "--bv", required=True,
        help="BV id; resolves the per-file paths inside temp_dir.",
    )
    parser.add_argument(
        "-o", "--output", type=Path, required=True,
        help="Final mp4 path (e.g. output/<project>/<dir>/<bv>_final.mp4).",
    )
    parser.add_argument(
        "--cut", action="append", default=[], metavar="START~END",
        help=(
            "Time range to REMOVE from the output. Repeatable. "
            "START/END accept SS, MM:SS, or HH:MM:SS."
        ),
    )
    parser.add_argument(
        "--speed", type=float, default=1.0,
        help="Playback multiplier in [0.5, 2.0] (default 1.0).",
    )
    parser.add_argument(
        "--preview-seconds", type=int, default=None,
        help="Cap output to the first N seconds (preview iteration).",
    )
    parser.add_argument(
        "--no-subtitle", action="store_true",
        help="Skip the cleaned-subtitle layer. Danmaku is still burned.",
    )
    parser.add_argument(
        "--no-music-swap", action="store_true",
        help=(
            "Skip the speech+bed amix. Maps <bv>.mp4's native audio "
            "instead — for streamers whose source music is already "
            "royalty-clear."
        ),
    )
    return parser.parse_args(argv)


def _resolve_paths(temp_dir: Path, bv: str, no_subtitle: bool,
                   no_music_swap: bool):
    """Locate the canonical Stage 5 inputs under ``temp_dir``."""
    video = temp_dir / f"{bv}.mp4"
    danmaku_ass = temp_dir / f"{bv}.danmaku.ass"
    bv_dir = temp_dir / bv
    speech_wav = None if no_music_swap else bv_dir / "speech.wav"
    music_bed = None if no_music_swap else temp_dir / f"{bv}.music_bed.wav"
    cleaned_ass = None if no_subtitle else bv_dir / "speech.cleaned.ass"

    missing: list[Path] = []
    if not video.exists():
        missing.append(video)
    if not danmaku_ass.exists():
        missing.append(danmaku_ass)
    if speech_wav is not None and not speech_wav.exists():
        missing.append(speech_wav)
    if music_bed is not None and not music_bed.exists():
        missing.append(music_bed)
    if cleaned_ass is not None and not cleaned_ass.exists():
        missing.append(cleaned_ass)
    if missing:
        bullets = "\n  - ".join(str(p) for p in missing)
        raise FileNotFoundError(
            "missing required Stage 5 inputs:\n  - " + bullets + "\n"
            "Did you run video2yt-fetch / -stems / -subtitle / -music-mix first?"
        )
    return video, danmaku_ass, speech_wav, music_bed, cleaned_ass


def run(args: argparse.Namespace) -> Path:
    preflight()

    if not (0.5 <= args.speed <= 2.0):
        raise ValueError(
            f"--speed must be between 0.5 and 2.0, got {args.speed}"
        )

    video, danmaku_ass, speech_wav, music_bed, cleaned_ass = _resolve_paths(
        args.temp_dir, args.bv,
        no_subtitle=args.no_subtitle, no_music_swap=args.no_music_swap,
    )

    # Probe video duration so cuts can be normalized.
    from video2yt import validate
    info = validate.probe(video)

    cut_ranges: list[tuple[float, float]] = []
    keep_ranges: list[tuple[float, float]] | None = None
    if args.cut:
        raw_cuts = [cuts.parse_cut_range(s) for s in args.cut]
        cut_ranges = cuts.normalize_cuts(raw_cuts, total_duration=info.duration)
        keep_ranges = cuts.keep_ranges_from_cuts(
            cut_ranges, total_duration=info.duration,
        )
        total_removed = sum(end - start for start, end in cut_ranges)
        _log(f"cut ranges: {cut_ranges} → keep: {keep_ranges} (removed {total_removed:.2f}s)")

    _log(
        f"burning {video.name} → {args.output.name} "
        f"(subtitle={not args.no_subtitle}, music_swap={not args.no_music_swap}, "
        f"speed={args.speed}, cuts={len(cut_ranges)}, "
        f"preview={args.preview_seconds})"
    )

    output = burn.render(
        video_path=video,
        ass_path=danmaku_ass,
        output_path=args.output,
        max_duration=args.preview_seconds,
        keep_ranges=keep_ranges,
        speed=args.speed,
        cleaned_ass=cleaned_ass,
        speech_wav=speech_wav,
        music_bed_wav=music_bed,
        apply_subtitle=not args.no_subtitle,
        apply_music_swap=not args.no_music_swap,
        cut_ranges=cut_ranges or None,
    )
    return output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
    except SystemExit as e:
        return int(e.code or 0)
    try:
        out = run(args)
        _log(f"success: {out}")
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

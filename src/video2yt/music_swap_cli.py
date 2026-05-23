"""video2yt-music-swap entry point.

Replaces the streamer's copyrighted background music in a burnt Bilibili
segment with a CC0 royalty-free music bed (Approach A — see the design spec).
"""
import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import music_swap


def _log(msg: str) -> None:
    print(f"[video2yt-music-swap] {msg}", file=sys.stderr)


def preflight() -> None:
    """Fail fast if ffmpeg, ffprobe, or the demucs package are unavailable."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: "
            "brew install homebrew-ffmpeg/ffmpeg/ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH (usually ships with ffmpeg)")
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError(
            "demucs package not found. Install with: uv add demucs"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-music-swap",
        description=(
            "Isolate the commentary voice from a burnt Bilibili segment and "
            "replace the streamer's background music with a CC0 music bed."
        ),
    )
    parser.add_argument("input", type=Path, help="Input segment MP4")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output MP4 (default: <input stem>_clean.mp4 alongside the input)",
    )
    parser.add_argument(
        "--music-volume", type=float, default=0.25,
        help="Music bed level relative to the voice (default: 0.25)",
    )
    parser.add_argument(
        "--no-duck", action="store_true",
        help="Disable sidechain ducking; mix the bed at a flat level",
    )
    parser.add_argument(
        "--no-vocal-gate", action="store_true",
        help=(
            "Disable post-Demucs vocal gating. Useful for A/B comparison; "
            "default is to gate low-level non-speech bleed."
        ),
    )
    parser.add_argument(
        "--vocal-gate-threshold", type=float, default=0.015,
        help=(
            "ffmpeg agate threshold as linear amplitude (default: 0.015, "
            "about -36.5 dBFS). Lower keeps more voice but more BGM bleed; "
            "higher suppresses more bleed but may clip quiet speech."
        ),
    )
    parser.add_argument(
        "--vocal-gate-release-ms", type=int, default=250,
        help="Vocal gate release time in milliseconds (default: 250).",
    )
    parser.add_argument(
        "--model", default="htdemucs",
        help="Demucs separation model (default: htdemucs)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Seed for reproducible music-track selection",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="Keep the temp directory (extracted WAV, Demucs output)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()
    if not args.input.exists():
        raise FileNotFoundError(f"input file not found: {args.input}")
    output = args.output or args.input.with_name(
        f"{args.input.stem}_clean.mp4"
    )
    inputs = music_swap.MusicSwapInputs(
        input_path=args.input,
        output_path=output,
        music_volume=args.music_volume,
        duck=not args.no_duck,
        model=args.model,
        seed=args.seed,
        keep_temp=args.keep_temp,
        vocal_gate=not args.no_vocal_gate,
        vocal_gate_threshold=args.vocal_gate_threshold,
        vocal_gate_release_ms=args.vocal_gate_release_ms,
    )
    _log(f"music-swapping {args.input.name} -> {output.name}")
    return music_swap.render(inputs)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except subprocess.CalledProcessError as e:
        tool = e.cmd[0] if e.cmd else "subprocess"
        _log(f"error: {tool} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1

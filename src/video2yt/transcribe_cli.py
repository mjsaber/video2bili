"""CLI for video2yt-transcribe: audio + script -> SRT via whisperx alignment."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import transcribe, validate


def _log(msg: str) -> None:
    print(f"[video2yt-transcribe] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH (whisperx needs it to read audio)"
        )
    try:
        import whisperx  # noqa: F401
    except ImportError as e:
        raise RuntimeError(
            "whisperx not installed. Run: uv add whisperx"
        ) from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-transcribe",
        description=(
            "Align an audio file to a script using whisperx forced alignment, "
            "producing an SRT with the script's text and audio-derived timestamps."
        ),
    )
    parser.add_argument(
        "--audio", type=Path, required=True, help="Audio file"
    )
    parser.add_argument(
        "--script",
        type=Path,
        required=True,
        help="Script file (plain text or markdown)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=None,
        help="Output SRT file path (default: <audio>.srt next to the audio file)",
    )
    parser.add_argument(
        "--language",
        default="zh",
        help="Audio language (default: zh for Chinese). Passed to whisperx.",
    )
    parser.add_argument(
        "--model",
        default="small",
        help=(
            "Whisper model name (tiny/base/small/medium/large-v3). "
            "Default: small for speed. Use large-v3 for best quality."
        ),
    )
    parser.add_argument(
        "--device",
        default="cpu",
        help=(
            "whisperx device (cpu/cuda/mps). Default: cpu. "
            "On macOS, CPU is usually the only reliable option."
        ),
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()

    if not args.audio.exists():
        raise FileNotFoundError(f"audio file not found: {args.audio}")
    if not args.script.exists():
        raise FileNotFoundError(f"script file not found: {args.script}")

    _log("probing audio")
    audio_info = validate.probe(args.audio)
    if not audio_info.has_audio:
        raise ValueError(f"audio file has no audio stream: {args.audio}")
    _log(f"audio duration: {audio_info.duration:.2f}s")

    script_text = args.script.read_text(encoding="utf-8")
    _log(f"read script: {len(script_text)} chars")

    _log(
        f"running whisperx (model={args.model}, language={args.language}, "
        f"device={args.device})"
    )
    _log("  (first run downloads models; subsequent runs are faster)")
    srt = transcribe.transcribe_script(
        audio_path=args.audio,
        script_text=script_text,
        language=args.language,
        model_name=args.model,
        device=args.device,
    )

    output_path = args.output if args.output else args.audio.with_suffix(".srt")
    output_path.write_text(srt, encoding="utf-8")
    block_count = srt.count("\n\n")
    _log(f"success: {output_path} ({block_count} blocks)")
    return output_path


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except subprocess.CalledProcessError as e:
        _log("error: subprocess failed")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1

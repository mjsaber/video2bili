"""video2yt-intro — compose a dynamic intro (Option A: single big card spotlight).

Wraps ``intro_compose.render``: a dimmed looped background, the 女老板 mascot
animated as the narrator, the currently-introduced card shown large top-center
and swapped in time with the SRT, a bottom-left subtitle, and a title band.

Card timing comes from a per-project cards file (``--cards``); see
``intro_compose.parse_cards_file`` for the format.
"""
import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import intro_compose, validate

_DEFAULT_MASCOT = Path("assets/cta/src/mascot_raw.png")
_DEFAULT_CARDS_DIR = Path("assets/cards")


def _log(msg: str) -> None:
    print(f"[video2yt-intro] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. Install with: brew install ffmpeg")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH (usually ships with ffmpeg)")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="video2yt-intro",
        description="Compose a dynamic intro: dancing mascot narrator + per-card spotlight.",
    )
    p.add_argument("--audio", type=Path, required=True, help="Intro voiceover (mp3/m4a/wav)")
    p.add_argument("--bg", type=Path, required=True, help="Background image (jpg/png)")
    p.add_argument("--srt", type=Path, required=True, help="Intro SRT subtitle")
    p.add_argument("--cards", type=Path, required=True,
                   help="Cards file: '<png> | <中文卡名> [| <start> <end>]' per line, display order")
    p.add_argument("--cards-dir", type=Path, default=_DEFAULT_CARDS_DIR,
                   help=f"Dir for card PNG basenames (default: {_DEFAULT_CARDS_DIR})")
    p.add_argument("--mascot", type=Path, default=_DEFAULT_MASCOT,
                   help=f"Mascot PNG with alpha (default: {_DEFAULT_MASCOT})")
    p.add_argument("--title", default="",
                   help="Optional title text in a top band; omit for no title")
    p.add_argument("--font-face", default="Hiragino Sans GB",
                   help="Subtitle font family (default: Hiragino Sans GB)")
    p.add_argument("-o", "--output", type=Path, required=True, help="Output MP4 path")
    return p.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()

    for label, path in (
        ("audio", args.audio), ("bg", args.bg), ("srt", args.srt),
        ("cards", args.cards), ("mascot", args.mascot),
    ):
        if not path.exists():
            raise FileNotFoundError(f"{label} file not found: {path}")

    audio_info = validate.probe(args.audio)
    if not audio_info.has_audio:
        raise ValueError(f"audio file has no audio stream: {args.audio}")
    _log(f"audio duration: {audio_info.duration:.2f}s")

    inputs = intro_compose.IntroInputs(
        audio=args.audio,
        bg=args.bg,
        srt=args.srt,
        cards_file=args.cards,
        mascot=args.mascot,
        title=args.title,
        cards_dir=args.cards_dir,
        font_face=args.font_face,
    )
    _log(f"composing {args.output.name}")
    intro_compose.render(inputs, args.output)

    _log("validating output")
    out = validate.probe(args.output)
    if not out.has_video or not out.has_audio:
        raise ValueError("output missing a video or audio stream")
    if out.vcodec != "h264":
        raise ValueError(f"output vcodec is {out.vcodec!r}, expected h264")
    if out.width != 1920 or out.height != 1080:
        raise ValueError(f"output resolution {out.width}x{out.height} != 1920x1080")
    if abs(out.duration - audio_info.duration) >= 1.0:
        raise ValueError(
            f"output duration {out.duration:.2f}s differs from audio "
            f"{audio_info.duration:.2f}s by more than 1 second"
        )

    _log(f"success: {args.output}")
    return args.output


def main(argv: list[str] | None = None) -> int:
    try:
        run(parse_args(argv))
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

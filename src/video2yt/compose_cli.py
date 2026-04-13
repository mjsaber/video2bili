import argparse
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import compose, validate
from video2yt.cli import _sanitize_title


def _log(msg: str) -> None:
    print(f"[video2yt-compose] {msg}", file=sys.stderr)


def preflight() -> None:
    """Fail fast if ffmpeg/ffprobe aren't available."""
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
        prog="video2yt-compose",
        description=(
            "Compose a 1080p MP4 from an audio file, a background image, "
            "and an SRT subtitle file."
        ),
    )
    parser.add_argument(
        "--audio", type=Path, required=True,
        help="Audio file (mp3/m4a/wav/flac/etc.)",
    )
    parser.add_argument(
        "--image", type=Path, required=True,
        help="Background image (jpg/png/webp)",
    )
    parser.add_argument(
        "--srt", type=Path, required=True,
        help="SRT subtitle file",
    )
    parser.add_argument(
        "--title", required=True,
        help="Title used for subfolder and output filename",
    )
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=Path("./output"),
        help="Directory for the final MP4 (default: ./output)",
    )
    parser.add_argument(
        "--font-face", default="Hiragino Sans GB",
        help="Subtitle font family (default: Hiragino Sans GB)",
    )
    parser.add_argument(
        "--font-size", type=int, default=None,
        help=(
            "Subtitle font size in pixels "
            "(default: auto - 72 for center, 42 for bottom/top)"
        ),
    )
    parser.add_argument(
        "--position", choices=["bottom", "center", "top"], default="center",
        help="Subtitle vertical position (default: center)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()

    # 1. Validate inputs exist
    if not args.audio.exists():
        raise FileNotFoundError(f"audio file not found: {args.audio}")
    if not args.image.exists():
        raise FileNotFoundError(f"image file not found: {args.image}")
    if not args.srt.exists():
        raise FileNotFoundError(f"SRT file not found: {args.srt}")

    # 2. Probe audio, check it has an audio stream
    _log("probing audio file")
    audio_info = validate.probe(args.audio)
    if not audio_info.has_audio:
        raise ValueError(f"audio file has no audio stream: {args.audio}")
    _log(f"audio duration: {audio_info.duration:.2f}s")

    # 3. Validate SRT
    n_subs = compose.check_srt(args.srt)
    _log(f"detected {n_subs} subtitle blocks")

    # 4. Build output path
    safe_title = _sanitize_title(args.title)
    output_subdir = args.output_dir / safe_title
    output_subdir.mkdir(parents=True, exist_ok=True)
    output_path = output_subdir / f"{safe_title}.mp4"

    # 5. Compose
    if args.font_size is not None:
        font_size = args.font_size
    elif args.position == "center":
        font_size = 72
    else:
        font_size = 42
    inputs = compose.ComposeInputs(
        audio_path=args.audio,
        image_path=args.image,
        srt_path=args.srt,
        title=args.title,
        output_dir=args.output_dir,
        font_face=args.font_face,
        font_size=font_size,
        position=args.position,
    )
    _log(
        f"composing {output_path.name} "
        f"(font: {args.font_face!r} {font_size}px, position: {args.position})"
    )
    compose.render(inputs, output_path)

    # 6. Validate output
    _log("validating output")
    output_info = validate.probe(output_path)
    if not output_info.has_video:
        raise ValueError("output has no video stream")
    if not output_info.has_audio:
        raise ValueError("output has no audio stream")
    if output_info.vcodec != "h264":
        raise ValueError(
            f"output vcodec is {output_info.vcodec!r}, expected h264"
        )
    if output_info.width != 1920 or output_info.height != 1080:
        raise ValueError(
            f"output resolution {output_info.width}x{output_info.height} "
            f"!= 1920x1080"
        )
    if abs(output_info.duration - audio_info.duration) >= 1.0:
        raise ValueError(
            f"output duration {output_info.duration:.2f}s differs from audio "
            f"{audio_info.duration:.2f}s by more than 1 second"
        )

    _log(f"success: {output_path}")
    return output_path


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

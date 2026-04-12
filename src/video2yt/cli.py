import argparse
import importlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import burn, download, validate

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")


def extract_bv_id(url: str) -> str:
    """Extract the BV id from a Bilibili video URL."""
    m = BV_PATTERN.search(url)
    if not m:
        raise ValueError(
            f"URL does not contain a BV id: {url!r}\n"
            f"expected format: https://www.bilibili.com/video/BV..."
        )
    return m.group(1)


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
    try:
        mod = importlib.import_module("biliass")
        if mod is None:
            raise ImportError("biliass is None")
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp-danmaku / biliass not available. Install with: "
            "uv add yt-dlp-danmaku"
        ) from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt",
        description="Download a Bilibili video and burn danmaku into the output MP4",
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=Path("./output"),
        help="Directory for the final MP4 (default: ./output)",
    )
    parser.add_argument(
        "-t", "--temp-dir", type=Path, default=Path("./temp"),
        help="Directory for intermediate files (default: ./temp)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=1080, choices=[1080, 720, 480],
        help="Max video quality (default: 1080)",
    )
    parser.add_argument(
        "-b", "--browser", default="chrome",
        help="Browser to read cookies from (default: chrome)",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="Keep intermediate files after success",
    )
    parser.add_argument(
        "--font-face", default="PingFang SC",
        help="Font family for rendered danmaku (default: PingFang SC — macOS CJK)",
    )
    parser.add_argument(
        "--font-size", type=int, default=40,
        help="Font size in pixels for rendered danmaku (default: 40)",
    )
    return parser.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[video2yt] {msg}", file=sys.stderr)


def run(args: argparse.Namespace) -> Path:
    preflight()
    bv_id = extract_bv_id(args.url)
    args.temp_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    _log(f"downloading {bv_id} (quality<={args.quality}, browser={args.browser})")
    video_path, ass_path = download.fetch(
        url=args.url,
        temp_dir=args.temp_dir,
        quality=args.quality,
        browser=args.browser,
        bv_id=bv_id,
        font_face=args.font_face,
        font_size=args.font_size,
    )

    _log("probing source video")
    source_info = validate.probe(video_path)
    for w in validate.check_source(source_info, args.quality):
        _log(f"warning: {w}")

    n_danmaku = validate.check_ass(ass_path)
    _log(f"detected {n_danmaku} danmaku lines")

    output_path = args.output_dir / f"{bv_id}_with_danmaku.mp4"
    _log(f"burning danmaku into {output_path.name}")
    burn.render(video_path, ass_path, output_path)

    _log("validating output")
    output_info = validate.probe(output_path)
    for w in validate.check_output(source_info, output_info):
        _log(f"warning: {w}")

    if not args.keep_temp:
        _log("cleaning up temp files")
        video_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)

    return output_path


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        output_path = run(args)
        _log(f"success: {output_path}")
        return 0
    except KeyboardInterrupt:
        _log("cancelled; temp files kept for debugging")
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

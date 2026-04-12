import argparse
import importlib
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from video2yt import burn, download, validate

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")

# Bilibili's native danmaku scaling: the web/client player renders a standard
# (nominal size=25) danmaku at ``player_height * 25 / 540`` pixels. This
# matches what a user sees on bilibili.com, so computing font_size from the
# real video height reproduces the same on-screen size.
REFERENCE_PLAYER_HEIGHT = 540
REFERENCE_STANDARD_SIZE = 25

MAX_TITLE_DIR_LENGTH = 60
UPLOADER_PREFIX_LENGTH = 4
UPLOADER_TITLE_SEPARATOR = "："  # U+FF1A fullwidth colon (safe on all filesystems)


def _build_dir_name(
    metadata: dict,
    bv_id: str,
    uploader_prefix_length: int = UPLOADER_PREFIX_LENGTH,
) -> str:
    """Build the per-video subfolder name: ``<uploader_prefix>：<title>``, sanitized.

    Falls back to just the title if uploader is missing or empty. Falls back
    to the BV id if title is also missing.
    """
    uploader = metadata.get("uploader") or metadata.get("channel") or ""
    uploader_prefix = uploader[:uploader_prefix_length]
    title = metadata.get("title") or bv_id
    if uploader_prefix:
        combined = f"{uploader_prefix}{UPLOADER_TITLE_SEPARATOR}{title}"
    else:
        combined = title
    return _sanitize_title(combined)


def _sanitize_title(title: str, max_length: int = MAX_TITLE_DIR_LENGTH) -> str:
    """Sanitize a video title for use as a directory name.

    - Replace filesystem-unsafe characters with ``_``
    - Collapse whitespace
    - Strip leading/trailing whitespace and dots
    - Truncate to ``max_length`` characters
    - Return ``"unnamed"`` if result would be empty

    The max_length is in characters, not bytes. On macOS and Linux the
    per-component byte limit is 255; at max_length=60 even all-CJK
    titles (3 bytes per char in UTF-8) fit in 180 bytes, leaving safe
    headroom.
    """
    # Replace characters disallowed on common filesystems (Windows-safe set):
    #   < > : " / \ | ? *  and control chars 0x00-0x1f
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title)
    # Collapse whitespace (including newlines, tabs) to a single space
    cleaned = re.sub(r'\s+', ' ', cleaned)
    # Collapse runs of underscores produced by the replace above
    cleaned = re.sub(r'_+', '_', cleaned)
    # Strip leading/trailing whitespace, dots, and underscores
    cleaned = cleaned.strip(' ._')
    # Truncate to max_length characters (not bytes)
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(' ._')
    return cleaned or "unnamed"


def compute_font_size(video_height: int) -> int:
    """Compute danmaku font size using Bilibili's native scaling formula."""
    return round(video_height * REFERENCE_STANDARD_SIZE / REFERENCE_PLAYER_HEIGHT)


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
        "--font-face", default="Hiragino Sans GB",
        help=(
            "Font family for rendered danmaku (default: Hiragino Sans GB). "
            "This font is preinstalled on macOS and visible to Homebrew "
            "fontconfig, so libass can actually find it. PingFang SC lives "
            "inside a SIP-protected .ttc that libass cannot open."
        ),
    )
    parser.add_argument(
        "--font-size", type=int, default=None,
        help=(
            "Font size in pixels for standard (size=25) danmaku. "
            "Default: auto — computed from video height using Bilibili's "
            "native formula video_height * 25 / 540."
        ),
    )
    parser.add_argument(
        "--codec", default="h264", choices=["h264", "h265", "auto"],
        help=(
            "Video codec preference (default: h264 — most compatible, "
            "preferred by YouTube). 'h265' for smaller files on modern players. "
            "'auto' lets yt-dlp decide by its own sort rules."
        ),
    )
    parser.add_argument(
        "--preview-seconds", type=int, default=None,
        help=(
            "If set, burn only the first N seconds of the video (passed to "
            "ffmpeg as -t N). Useful for quickly previewing style/codec choices "
            "without re-encoding the whole video."
        ),
    )
    return parser.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[video2yt] {msg}", file=sys.stderr)


def run(args: argparse.Namespace) -> Path:
    timings: dict[str, float] = {}
    t_start = time.monotonic()

    preflight()
    bv_id = extract_bv_id(args.url)

    # Metadata + subfolder setup BEFORE creating any temp files
    t0 = time.monotonic()
    _log(f"fetching metadata for {bv_id}")
    metadata = download.get_metadata(args.url, args.browser)
    title = metadata.get("title") or bv_id
    uploader = metadata.get("uploader") or metadata.get("channel") or ""
    safe_title = _build_dir_name(metadata, bv_id)
    _log(
        f"title: {title!r} uploader: {uploader!r} -> subfolder: {safe_title!r}"
    )
    timings["metadata"] = time.monotonic() - t0

    temp_subdir = args.temp_dir / safe_title
    output_subdir = args.output_dir / safe_title
    temp_subdir.mkdir(parents=True, exist_ok=True)
    output_subdir.mkdir(parents=True, exist_ok=True)

    _log(
        f"downloading {bv_id} (quality<={args.quality}, "
        f"codec={args.codec}, browser={args.browser})"
    )
    t0 = time.monotonic()
    video_path, xml_path = download.fetch(
        url=args.url,
        temp_dir=temp_subdir,
        quality=args.quality,
        browser=args.browser,
        bv_id=bv_id,
        codec=args.codec,
    )
    timings["download"] = time.monotonic() - t0

    _log("probing source video")
    t0 = time.monotonic()
    source_info = validate.probe(video_path)
    for w in validate.check_source(source_info, args.quality):
        _log(f"warning: {w}")
    timings["probe_source"] = time.monotonic() - t0

    font_size = (
        args.font_size if args.font_size is not None
        else compute_font_size(source_info.height)
    )
    _log(
        f"danmaku font: face={args.font_face!r} size={font_size}px "
        f"(video is {source_info.width}x{source_info.height}, "
        f"codec={source_info.vcodec})"
    )

    t0 = time.monotonic()
    ass_path = temp_subdir / f"{bv_id}.danmaku.ass"
    download.generate_ass(
        xml_path=xml_path,
        ass_path=ass_path,
        width=source_info.width,
        height=source_info.height,
        font_face=args.font_face,
        font_size=font_size,
    )

    n_danmaku = validate.check_ass(ass_path)
    _log(f"detected {n_danmaku} danmaku lines")
    timings["generate_ass"] = time.monotonic() - t0

    output_path = output_subdir / f"{bv_id}_with_danmaku.mp4"
    preview_tag = (
        f" (preview first {args.preview_seconds}s)"
        if args.preview_seconds else ""
    )
    _log(f"burning danmaku into {output_path.name}{preview_tag}")
    t0 = time.monotonic()
    burn.render(video_path, ass_path, output_path, max_duration=args.preview_seconds)
    timings["burn"] = time.monotonic() - t0

    _log("validating output")
    t0 = time.monotonic()
    output_info = validate.probe(output_path)
    expected_duration = (
        float(args.preview_seconds)
        if args.preview_seconds is not None
        else source_info.duration
    )
    for w in validate.check_output(
        source_info, output_info, expected_duration=expected_duration
    ):
        _log(f"warning: {w}")
    timings["validate_output"] = time.monotonic() - t0

    if not args.keep_temp:
        _log("cleaning up temp files")
        video_path.unlink(missing_ok=True)
        xml_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)
        # Best-effort: remove the subdir if empty
        try:
            temp_subdir.rmdir()
        except OSError:
            pass  # subdir not empty or doesn't exist

    total = time.monotonic() - t_start
    _log(
        f"timings: metadata={timings['metadata']:.2f}s "
        f"download={timings['download']:.1f}s "
        f"probe_src={timings['probe_source']:.2f}s "
        f"gen_ass={timings['generate_ass']:.2f}s "
        f"burn={timings['burn']:.1f}s "
        f"validate_out={timings['validate_output']:.2f}s "
        f"total={total:.1f}s"
    )
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

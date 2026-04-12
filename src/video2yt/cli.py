import importlib
import re
import shutil

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

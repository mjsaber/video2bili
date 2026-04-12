import re
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class ComposeInputs:
    audio_path: Path
    image_path: Path
    srt_path: Path
    title: str
    output_dir: Path
    font_face: str = "Hiragino Sans GB"
    font_size: int = 42


_TIMECODE_PATTERN = re.compile(
    r"^\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{1,3}",
    re.MULTILINE,
)


def check_srt(srt_path: Path) -> int:
    """Validate the SRT file and return the number of subtitle blocks.

    Raises ValueError on: missing file, unreadable encoding, or no subtitle
    blocks. A subtitle block is counted via its timecode line
    (``00:00:00,000 --> 00:00:00,000``); this is the cheapest proxy and
    tolerates various SRT dialects (``.`` instead of ``,``, 1-2 digit hours,
    1-3 digit milliseconds).
    """
    if not srt_path.exists():
        raise ValueError(f"SRT file not found: {srt_path}")
    try:
        text = srt_path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        try:
            text = srt_path.read_text(encoding="gbk")
        except UnicodeDecodeError as e:
            raise ValueError(
                f"SRT file is not valid UTF-8 or GBK: {srt_path}"
            ) from e

    n = len(_TIMECODE_PATTERN.findall(text))
    if n == 0:
        raise ValueError(
            f"SRT file has no subtitle blocks (no timecode lines found): {srt_path}"
        )
    return n


def _build_subtitles_filter(srt_filename: str, font_face: str, font_size: int) -> str:
    """Build the ffmpeg ``subtitles=...`` filter expression.

    Uses the ``f='...'`` escaping pattern from ``burn.py``. The ``force_style``
    values are hard-coded except for ``font_face`` and ``font_size``.
    """
    style = (
        f"FontName={font_face},"
        f"FontSize={font_size},"
        f"PrimaryColour=&HFFFFFF,"
        f"OutlineColour=&H000000,"
        f"Outline=2,"
        f"MarginV=80,"
        f"Alignment=2"  # ASS alignment 2 = centered bottom
    )
    return f"subtitles=f='{srt_filename}':force_style='{style}'"


def _build_filter_complex(srt_filename: str, font_face: str, font_size: int) -> str:
    """Build the full filter_complex string: scale/pad to 1080p then subtitles."""
    subtitles = _build_subtitles_filter(srt_filename, font_face, font_size)
    return (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black[bg];"
        f"[bg]{subtitles}[outv]"
    )


def render(inputs: ComposeInputs, output_path: Path) -> Path:
    """Compose the final MP4 via ffmpeg.

    Runs ffmpeg with ``cwd=<srt.parent>`` so the ``subtitles`` filter can
    reference the SRT by basename (the same escaping trick used in
    ``burn.py``). The ``-i`` image and audio inputs are passed as absolute
    paths since ``-i`` does not go through filter_complex.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = inputs.srt_path.parent
    srt_name = inputs.srt_path.name

    filter_complex = _build_filter_complex(
        srt_filename=srt_name,
        font_face=inputs.font_face,
        font_size=inputs.font_size,
    )

    cmd = [
        "ffmpeg", "-y",
        "-loop", "1",
        "-i", str(inputs.image_path.resolve()),
        "-i", str(inputs.audio_path.resolve()),
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "1:a",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-tune", "stillimage",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path.resolve()),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=work_dir)
    return output_path

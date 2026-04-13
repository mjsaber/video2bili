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


_SRT_TIME_RE = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)")


def _srt_time_to_ass_time(srt_time: str) -> str:
    """Convert SRT time (HH:MM:SS,mmm) to ASS time (H:MM:SS.cc).

    Accepts both ``,`` and ``.`` as the millisecond separator. Milliseconds
    are rounded to the nearest centisecond; if rounding produces 100, the
    extra second carries over cleanly.
    """
    m = _SRT_TIME_RE.match(srt_time.strip())
    if not m:
        raise ValueError(f"invalid SRT time: {srt_time!r}")
    h, mm, s, ms_str = m.groups()
    ms_str = ms_str.ljust(3, "0")[:3]
    ms = int(ms_str)
    cs = round(ms / 10)
    s_int = int(s)
    if cs >= 100:
        cs = 0
        s_int += 1
    return f"{int(h)}:{int(mm):02d}:{s_int:02d}.{cs:02d}"


def _ass_escape_text(text: str) -> str:
    """Escape literal text for use inside an ASS Dialogue line.

    Latin and CJK text pass through unchanged. ASS override tags are
    delimited by ``{`` and ``}``; SRT content is not expected to contain
    these in practice, so we do not escape them here.
    """
    return text


def srt_to_ass(
    srt_text: str,
    video_width: int,
    video_height: int,
    font_face: str,
    font_size: int,
) -> str:
    """Convert SRT text to ASS text with pixel-accurate script resolution.

    Sets ``PlayResX=video_width`` and ``PlayResY=video_height`` so ASS
    ``FontSize`` units equal display pixels exactly. Produces a single
    ``Default`` style with the given font and size, white primary colour,
    black outline (2px), alignment 2 (centred bottom), MarginV=80.

    Raises ``ValueError`` if no parseable dialogue blocks are found.
    """
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    dialogue_lines: list[str] = []
    for block in blocks:
        lines = block.strip().splitlines()
        if len(lines) < 2:
            continue
        start_idx = 0
        if lines[0].strip().isdigit():
            start_idx = 1
        if start_idx >= len(lines):
            continue
        time_line = lines[start_idx]
        tm = re.match(r"(\S+)\s*-->\s*(\S+)", time_line)
        if not tm:
            continue
        try:
            start = _srt_time_to_ass_time(tm.group(1))
            end = _srt_time_to_ass_time(tm.group(2))
        except ValueError:
            continue
        text_lines = lines[start_idx + 1:]
        if not text_lines:
            continue
        text = "\\N".join(_ass_escape_text(ln) for ln in text_lines)
        dialogue_lines.append(
            f"Dialogue: 0,{start},{end},Default,,0,0,0,,{text}"
        )
    if not dialogue_lines:
        raise ValueError("SRT contains no parseable dialogue blocks")

    header = (
        "[Script Info]\n"
        "ScriptType: v4.00+\n"
        f"PlayResX: {video_width}\n"
        f"PlayResY: {video_height}\n"
        "ScaledBorderAndShadow: yes\n"
        "WrapStyle: 0\n"
        "\n"
        "[V4+ Styles]\n"
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, "
        "OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, "
        "ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, "
        "Alignment, MarginL, MarginR, MarginV, Encoding\n"
        f"Style: Default,{font_face},{font_size},"
        "&H00FFFFFF,&H000000FF,&H00000000,&H00000000,"
        "0,0,0,0,100,100,0,0,1,2,0,2,10,10,80,1\n"
        "\n"
        "[Events]\n"
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, "
        "MarginV, Effect, Text\n"
    )
    return header + "\n".join(dialogue_lines) + "\n"


def render(inputs: ComposeInputs, output_path: Path) -> Path:
    """Compose the final MP4 via ffmpeg.

    Converts the SRT to an ASS file with explicit ``PlayResX``/``PlayResY``
    matching the 1920x1080 output so that ``FontSize`` units equal display
    pixels. The intermediate ASS is written next to the SRT (as
    ``<srt_stem>.compose.ass``) and is deliberately left on disk for
    debugging. ffmpeg still runs with ``cwd=<srt.parent>`` so the
    ``subtitles`` filter can reference the ASS file by basename (the same
    escaping trick used in ``burn.py``).
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    work_dir = inputs.srt_path.parent

    srt_text = inputs.srt_path.read_text(encoding="utf-8")
    ass_text = srt_to_ass(
        srt_text=srt_text,
        video_width=1920,
        video_height=1080,
        font_face=inputs.font_face,
        font_size=inputs.font_size,
    )
    ass_path = inputs.srt_path.with_suffix(".compose.ass")
    ass_path.write_text(ass_text, encoding="utf-8")

    filter_complex = (
        "[0:v]scale=1920:1080:force_original_aspect_ratio=decrease,"
        "pad=1920:1080:(ow-iw)/2:(oh-ih)/2:color=black[bg];"
        f"[bg]subtitles=f='{ass_path.name}'[outv]"
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

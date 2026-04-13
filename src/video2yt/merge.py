"""Concatenate multiple MP4 segments into a single video with a static progress
bar, per-segment audio loudness normalization, and a YouTube chapters file.

The progress bar is a static PNG rendered by Pillow (base bar + per-segment
fills and labels). The active-segment highlight is painted at merge time by
ffmpeg via a chain of ``drawbox`` filters with ``enable='between(t,S,E)'``.
"""

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

# Progress bar visual constants
_BAR_MARGIN_LR = 80                   # pixels on each side
_BAR_MARGIN_BOTTOM = 20               # distance from bottom of frame to bottom of bar
_BAR_HEIGHT = 12                      # bar thickness in pixels (slim to avoid subtitle overlap)
_LABEL_GAP_ABOVE_BAR = 8              # px between label baseline and bar top
_LABEL_FONT_SIZE = 20
_LABEL_FONT_FACE = "Hiragino Sans GB"

_BAR_BG = (30, 30, 30, 220)           # dark gray near-opaque
_BAR_SEGMENT_FILL = (150, 150, 150, 220)  # medium gray
_BAR_DIVIDER = (255, 255, 255, 230)   # white
_BAR_HIGHLIGHT = (255, 200, 0, 220)   # amber/yellow for current segment (passed to drawbox)
_LABEL_FILL = (255, 255, 255, 230)    # white
_LABEL_OUTLINE = (0, 0, 0, 200)       # black outline for readability


@dataclass
class Segment:
    """One input segment."""
    path: Path
    label: str
    duration: float = 0.0  # filled in by validate_segments_strict


@dataclass
class MergeInputs:
    segments: list[Segment]
    title: str
    label_font_face: str = _LABEL_FONT_FACE
    label_font_size: int = _LABEL_FONT_SIZE


def validate_segments_strict(segments: list[Segment]) -> None:
    """ffprobe each segment; fail if any isn't 1920x1080 30fps h264 with audio.

    Fills in each segment's ``duration`` field as a side effect.
    Raises ValueError with a summary of ALL violations (not just the first).
    """
    import json
    violations: list[str] = []
    for seg in segments:
        if not seg.path.exists():
            violations.append(f"{seg.path}: file not found")
            continue
        result = subprocess.run(
            [
                "ffprobe", "-v", "error",
                "-print_format", "json",
                "-show_format", "-show_streams",
                str(seg.path),
            ],
            check=True, capture_output=True, text=True,
        )
        data = json.loads(result.stdout)
        streams = data.get("streams", [])
        video_streams = [s for s in streams if s.get("codec_type") == "video"]
        audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
        fmt = data.get("format", {})

        if not video_streams:
            violations.append(f"{seg.path}: no video stream")
            continue
        v = video_streams[0]
        width = int(v.get("width", 0))
        height = int(v.get("height", 0))
        vcodec = v.get("codec_name", "")
        fps_str = v.get("r_frame_rate", "0/1")
        try:
            num, den = fps_str.split("/")
            fps = float(num) / float(den) if float(den) > 0 else 0.0
        except Exception:
            fps = 0.0

        if width != 1920 or height != 1080:
            violations.append(
                f"{seg.path}: resolution {width}x{height} != 1920x1080"
            )
        if vcodec != "h264":
            violations.append(f"{seg.path}: vcodec {vcodec!r} != h264")
        if abs(fps - 30.0) > 0.5:
            violations.append(f"{seg.path}: fps {fps:.2f} != 30")
        if not audio_streams:
            violations.append(f"{seg.path}: no audio stream")

        duration_raw = fmt.get("duration")
        if duration_raw is None:
            violations.append(f"{seg.path}: could not determine duration")
            continue
        seg.duration = float(duration_raw)

    if violations:
        raise ValueError(
            "strict input validation failed:\n  - " + "\n  - ".join(violations)
        )


def _load_font(face: str, size: int) -> ImageFont.FreeTypeFont:
    """Load a font by family name, with graceful fallback.

    Tries macOS system font paths first, then fontconfig via fc-match,
    then Pillow's default font. Returns a usable ImageFont object.
    """
    candidates = [
        f"/System/Library/Fonts/{face}.ttc",
        f"/System/Library/Fonts/{face}.ttf",
        f"/System/Library/Fonts/Supplemental/{face}.ttc",
        f"/System/Library/Fonts/Supplemental/{face}.ttf",
        f"/Library/Fonts/{face}.ttc",
        f"/Library/Fonts/{face}.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    # Try fc-match as a fallback
    try:
        result = subprocess.run(
            ["fc-match", "-f", "%{file}", face],
            capture_output=True, text=True, check=True, timeout=5,
        )
        font_path = result.stdout.strip()
        if font_path:
            return ImageFont.truetype(font_path, size)
    except (subprocess.SubprocessError, FileNotFoundError):
        pass
    # Absolute fallback
    return ImageFont.load_default()


def _fit_label_to_width(
    text: str,
    font: ImageFont.FreeTypeFont,
    max_width: float,
    draw: ImageDraw.ImageDraw,
) -> str:
    """Return ``text`` truncated with ``…`` if it exceeds max_width pixels."""
    if max_width <= 0:
        return ""
    bbox = draw.textbbox((0, 0), text, font=font)
    w = bbox[2] - bbox[0]
    if w <= max_width:
        return text
    ellipsis = "…"
    lo, hi = 0, len(text)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        candidate = text[:mid] + ellipsis
        bbox = draw.textbbox((0, 0), candidate, font=font)
        if (bbox[2] - bbox[0]) <= max_width:
            lo = mid
        else:
            hi = mid - 1
    return (text[:lo] + ellipsis) if lo > 0 else ""


def _draw_text_with_outline(
    draw: ImageDraw.ImageDraw,
    xy: tuple[float, float],
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple[int, int, int, int],
    outline: tuple[int, int, int, int],
    outline_width: int = 1,
) -> None:
    """Draw text with a 1-pixel outline for readability over any background."""
    x, y = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx == 0 and dy == 0:
                continue
            draw.text((x + dx, y + dy), text, font=font, fill=outline)
    draw.text((x, y), text, font=font, fill=fill)


def generate_progress_bar_png(
    segments: list[Segment],
    output_path: Path,
    video_width: int = 1920,
    video_height: int = 1080,
    font_face: str = _LABEL_FONT_FACE,
    font_size: int = _LABEL_FONT_SIZE,
) -> None:
    """Render a 1920x1080 transparent PNG with the base progress bar + labels.

    The PNG is static — it does NOT contain the per-segment highlight overlay,
    which is added via ffmpeg's drawbox filter at merge time (see
    ``_build_filter_complex``).
    """
    total_duration = sum(s.duration for s in segments)
    if total_duration <= 0:
        raise ValueError("total segment duration must be positive")

    img = Image.new("RGBA", (video_width, video_height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    bar_x = _BAR_MARGIN_LR
    bar_y = video_height - _BAR_MARGIN_BOTTOM - _BAR_HEIGHT
    bar_w = video_width - 2 * _BAR_MARGIN_LR
    bar_h = _BAR_HEIGHT

    # Base bar background
    draw.rectangle([bar_x, bar_y, bar_x + bar_w, bar_y + bar_h], fill=_BAR_BG)

    # Segment fills (neutral gray for all)
    cumulative = 0.0
    segment_rects: list[tuple[float, float]] = []  # (seg_x0, seg_x1) for each
    for seg in segments:
        start_frac = cumulative / total_duration
        end_frac = (cumulative + seg.duration) / total_duration
        seg_x0 = bar_x + start_frac * bar_w
        seg_x1 = bar_x + end_frac * bar_w
        segment_rects.append((seg_x0, seg_x1))
        draw.rectangle([seg_x0, bar_y, seg_x1, bar_y + bar_h], fill=_BAR_SEGMENT_FILL)
        cumulative += seg.duration

    # Dividers between segments (not at ends)
    for i in range(len(segments) - 1):
        _, seg_x1 = segment_rects[i]
        draw.line(
            [(seg_x1, bar_y), (seg_x1, bar_y + bar_h)],
            fill=_BAR_DIVIDER,
            width=2,
        )

    # Labels above each segment. Labels are drawn at their natural width and
    # centred on each segment's center; they are ALLOWED to extend beyond
    # the segment's own x range (useful for very short segments whose bar
    # width is too narrow for the label). We only clamp to the frame's left
    # and right edges so nothing falls off-screen, and truncate with "…"
    # only as a last resort when the label is wider than the entire frame.
    font = _load_font(font_face, font_size)
    label_y_bottom = bar_y - _LABEL_GAP_ABOVE_BAR
    frame_label_min_x = 10  # leave a 10 px edge margin
    frame_label_max_x = video_width - 10
    frame_label_avail = frame_label_max_x - frame_label_min_x
    for seg, (seg_x0, seg_x1) in zip(segments, segment_rects):
        seg_center_x = (seg_x0 + seg_x1) / 2
        # Measure the full label. Only truncate if it's wider than the frame.
        bbox = draw.textbbox((0, 0), seg.label, font=font)
        text_w = bbox[2] - bbox[0]
        text_h = bbox[3] - bbox[1]
        if text_w > frame_label_avail:
            fitted = _fit_label_to_width(
                seg.label, font, max_width=frame_label_avail, draw=draw,
            )
            if not fitted:
                continue
            bbox = draw.textbbox((0, 0), fitted, font=font)
            text_w = bbox[2] - bbox[0]
            text_h = bbox[3] - bbox[1]
            label = fitted
        else:
            label = seg.label
        # Centre on segment, then clamp to frame edges.
        text_x = seg_center_x - text_w / 2
        if text_x < frame_label_min_x:
            text_x = frame_label_min_x
        elif text_x + text_w > frame_label_max_x:
            text_x = frame_label_max_x - text_w
        text_y = label_y_bottom - text_h
        _draw_text_with_outline(
            draw, (text_x, text_y), label, font,
            fill=_LABEL_FILL, outline=_LABEL_OUTLINE,
        )

    img.save(output_path)


def _format_chapter_time(seconds: float) -> str:
    """Format seconds as MM:SS or HH:MM:SS for YouTube chapters."""
    total = int(seconds)
    hh = total // 3600
    mm = (total % 3600) // 60
    ss = total % 60
    if hh > 0:
        return f"{hh:02d}:{mm:02d}:{ss:02d}"
    return f"{mm:02d}:{ss:02d}"


def generate_chapters_text(segments: list[Segment]) -> str:
    """Produce a YouTube-compatible chapters.txt. First chapter must start at 00:00."""
    lines = []
    cumulative = 0.0
    for seg in segments:
        lines.append(f"{_format_chapter_time(cumulative)} {seg.label}")
        cumulative += seg.duration
    return "\n".join(lines) + "\n"


def _build_filter_complex(
    segments: list[Segment],
    progress_bar_input_idx: int,
) -> str:
    """Build the ffmpeg filter_complex for concat + loudnorm + overlay + highlight.

    Inputs (by index, in the ffmpeg command line order):
    - 0..N-1: each segment (``-i seg0.mp4 -i seg1.mp4 ...``)
    - N (= progress_bar_input_idx): the static progress bar PNG (``-loop 1 -i bar.png``)

    Output labels:
    - ``[outv]``: final video with overlay + highlights
    - ``[outa]``: final audio after per-segment loudnorm + concat

    Highlight technique: after concat+overlay, chain one drawbox per segment,
    each with ``enable='between(t,segment_start,segment_end)'``. Only the active
    segment's drawbox draws during its time range.
    """
    n = len(segments)
    parts: list[str] = []

    # Per-segment audio: resample to 48k, loudnorm to -14 LUFS
    for i in range(n):
        parts.append(
            f"[{i}:a]aresample=48000,loudnorm=I=-14:TP=-1:LRA=11[a{i}n]"
        )

    # Concat: interleave video + audio streams
    concat_inputs = "".join(f"[{i}:v][a{i}n]" for i in range(n))
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[cv][outa]")

    # Overlay the static progress bar PNG
    parts.append(f"[cv][{progress_bar_input_idx}:v]overlay=0:0[base]")

    # Highlight filters: one drawbox per segment, active during its time range.
    # Bar geometry (mirrors generate_progress_bar_png constants):
    total_duration = sum(s.duration for s in segments)
    video_width = 1920
    video_height = 1080
    bar_x = _BAR_MARGIN_LR
    bar_y = video_height - _BAR_MARGIN_BOTTOM - _BAR_HEIGHT
    bar_w = video_width - 2 * _BAR_MARGIN_LR
    bar_h = _BAR_HEIGHT

    highlight_r, highlight_g, highlight_b, highlight_a = _BAR_HIGHLIGHT
    highlight_alpha = highlight_a / 255.0
    # ffmpeg drawbox color format: "0xRRGGBB@alpha"
    highlight_color = (
        f"0x{highlight_r:02x}{highlight_g:02x}{highlight_b:02x}@{highlight_alpha:.2f}"
    )

    cumulative = 0.0
    prev_label = "base"
    for i, seg in enumerate(segments):
        start = cumulative
        end = cumulative + seg.duration
        start_frac = start / total_duration
        end_frac = end / total_duration
        seg_x = bar_x + int(round(start_frac * bar_w))
        seg_w = int(round((end_frac - start_frac) * bar_w))
        next_label = f"hl{i}" if i < n - 1 else "outv"
        parts.append(
            f"[{prev_label}]drawbox="
            f"x={seg_x}:y={bar_y}:w={seg_w}:h={bar_h}:"
            f"color={highlight_color}:t=fill:"
            f"enable='between(t,{start:.3f},{end:.3f})'"
            f"[{next_label}]"
        )
        prev_label = next_label
        cumulative += seg.duration

    return ";".join(parts)


def render(inputs: MergeInputs, output_path: Path) -> Path:
    """Run the full merge pipeline: validate, generate bar PNG, ffmpeg, write chapters."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Generate the progress bar PNG in the same directory as the output
    bar_png_path = output_path.parent / f"{output_path.stem}_progress_bar.png"
    generate_progress_bar_png(
        inputs.segments,
        bar_png_path,
        font_face=inputs.label_font_face,
        font_size=inputs.label_font_size,
    )

    # Build ffmpeg command
    cmd: list[str] = ["ffmpeg", "-y"]
    for seg in inputs.segments:
        cmd.extend(["-i", str(seg.path.resolve())])
    # Progress bar is the last input, looped
    cmd.extend(["-loop", "1", "-i", str(bar_png_path.resolve())])

    filter_complex = _build_filter_complex(
        segments=inputs.segments,
        progress_bar_input_idx=len(inputs.segments),
    )
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        "-c:a", "aac",
        "-b:a", "192k",
        "-shortest",
        str(output_path.resolve()),
    ])

    subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Write chapters file alongside
    chapters_path = output_path.parent / f"{output_path.stem}_chapters.txt"
    chapters_path.write_text(generate_chapters_text(inputs.segments), encoding="utf-8")

    return output_path

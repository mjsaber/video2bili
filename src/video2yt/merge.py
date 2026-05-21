"""Concatenate multiple MP4 segments into a single video with per-segment audio
loudness normalization, MP4 chapter markers, and a YouTube chapters text file.

Segmentation is delivered through chapter markers. There is no longer a
burned-in progress bar overlay.

YouTube's officially-documented chapter source is the **video description**:
the description must contain ≥3 ascending timestamps starting at 0:00, with
each chapter ≥10s. ``render`` writes ``<title>_chapters.txt`` for the
description paste. ``render`` also embeds the same chapters into the output
MP4 via an ffmetadata input + ``-map_metadata``/``-map_chapters``; YouTube
does not officially document reading these embedded atoms, so this is a
best-effort addition, NOT a substitute for the description block.
"""

import subprocess
from dataclasses import dataclass
from pathlib import Path


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
        if seg.duration < 10.0:
            violations.append(
                f"{seg.path}: duration {seg.duration:.2f}s < 10s "
                "(YouTube requires each chapter to be at least 10 seconds, "
                "otherwise the whole chapter list is discarded)"
            )

    if violations:
        raise ValueError(
            "strict input validation failed:\n  - " + "\n  - ".join(violations)
        )


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


def generate_ffmetadata(segments: list[Segment]) -> str:
    """Produce an ffmetadata file with one ``[CHAPTER]`` block per segment.

    ``render`` feeds this to ffmpeg via ``-map_metadata`` / ``-map_chapters`` so
    the chapter markers are baked into the output MP4. YouTube's official
    chapter source is the description text (see ``generate_chapters_text``);
    embedded MP4 chapters are not officially documented as supported, so this
    is a best-effort addition rather than a guaranteed fallback.
    """
    lines = [";FFMETADATA1"]
    cumulative = 0.0
    for seg in segments:
        start_ms = round(cumulative * 1000)
        end_ms = round((cumulative + seg.duration) * 1000)
        lines.append("[CHAPTER]")
        lines.append("TIMEBASE=1/1000")
        lines.append(f"START={start_ms}")
        lines.append(f"END={end_ms}")
        lines.append(f"title={seg.label}")
        cumulative += seg.duration
    return "\n".join(lines) + "\n"


def _build_filter_complex(segments: list[Segment]) -> str:
    """Build the ffmpeg filter_complex for per-segment loudnorm + concat.

    Inputs (by index, in the ffmpeg command line order):
    - 0..N-1: each segment (``-i seg0.mp4 -i seg1.mp4 ...``)

    Output labels:
    - ``[outv]``: concatenated video
    - ``[outa]``: concatenated audio after per-segment loudnorm
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
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")

    return ";".join(parts)


def render(inputs: MergeInputs, output_path: Path) -> Path:
    """Run the full merge pipeline: concat + loudnorm via ffmpeg, embed chapters,
    write the chapters text file."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Write the ffmetadata file (embedded MP4 chapter markers) alongside the output
    ffmeta_path = output_path.parent / f"{output_path.stem}_ffmeta.txt"
    ffmeta_path.write_text(generate_ffmetadata(inputs.segments), encoding="utf-8")

    # Build ffmpeg command
    cmd: list[str] = ["ffmpeg", "-y"]
    for seg in inputs.segments:
        cmd.extend(["-i", str(seg.path.resolve())])
    # The ffmetadata file is the trailing input.
    cmd.extend(["-i", str(ffmeta_path.resolve())])
    ffmeta_input_idx = len(inputs.segments)

    filter_complex = _build_filter_complex(inputs.segments)
    cmd.extend([
        "-filter_complex", filter_complex,
        "-map", "[outv]",
        "-map", "[outa]",
        "-map_metadata", str(ffmeta_input_idx),
        "-map_chapters", str(ffmeta_input_idx),
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

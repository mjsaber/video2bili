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

import math
import re
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
class Chapter:
    """A chapter start on the final video's timeline, in whole seconds."""
    start_seconds: int
    label: str


@dataclass
class MergeInputs:
    segments: list[Segment]
    title: str
    chapters: list[Chapter] | None = None  # None = automatic segment chapters
    no_chapters: bool = False


def validate_segments_strict(segments: list[Segment]) -> None:
    """ffprobe each segment; fail if any isn't 1920x1080 30fps h264 with audio.

    Fills in each segment's ``duration`` field as a side effect.
    Raises ValueError with a summary of ALL violations (not just the first).
    """
    import json
    if not segments:
        raise ValueError("at least 1 segment is required to merge")
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
        try:
            seg.duration = float(duration_raw)
        except (TypeError, ValueError):
            seg.duration = float("nan")
        if not math.isfinite(seg.duration) or seg.duration <= 0:
            violations.append(
                f"{seg.path}: duration must be a positive finite number of seconds"
            )

    if violations:
        raise ValueError(
            "strict input validation failed:\n  - " + "\n  - ".join(violations)
        )


def validate_chapters(chapters: list[Chapter], total_duration: float) -> None:
    """Require a complete YouTube chapter list independent of media boundaries."""
    if not math.isfinite(total_duration) or total_duration <= 0:
        raise ValueError("chapter timeline duration must be positive and finite")
    if len(chapters) < 3:
        raise ValueError("at least 3 chapters are required")
    if any(isinstance(c.start_seconds, bool) or not isinstance(c.start_seconds, int)
           or c.start_seconds < 0 for c in chapters):
        raise ValueError("chapter starts must be nonnegative whole seconds")
    if chapters[0].start_seconds != 0:
        raise ValueError("first chapter must start at 00:00")
    for i, chapter in enumerate(chapters):
        if not chapter.label.strip() or "\n" in chapter.label or "\r" in chapter.label:
            raise ValueError("chapter labels must be nonempty single lines")
        end = chapters[i + 1].start_seconds if i + 1 < len(chapters) else total_duration
        if chapter.start_seconds >= total_duration or end > total_duration:
            raise ValueError("chapter timestamps must be within the video duration")
        if end - chapter.start_seconds < 10:
            raise ValueError("chapters must be ordered and each last at least 10 seconds")


def parse_chapters_text(text: str, total_duration: float) -> list[Chapter]:
    """Parse lines of ``MM:SS Label`` or ``HH:MM:SS Label`` and validate them."""
    chapters = []
    for lineno, raw in enumerate(text.splitlines(), 1):
        line = raw.strip()
        if not line:
            continue
        match = re.fullmatch(r"([0-9]+:[0-9]{2}(?::[0-9]{2})?)\s+(.+)", line)
        if not match:
            raise ValueError(f"chapter line {lineno}: expected MM:SS or HH:MM:SS and a label")
        parts = [int(part) for part in match[1].split(":")]
        if parts[-1] >= 60 or (len(parts) == 3 and parts[-2] >= 60):
            raise ValueError(f"chapter line {lineno}: invalid timestamp")
        seconds = parts[-2] * 60 + parts[-1]
        if len(parts) == 3:
            seconds += parts[0] * 3600
        chapters.append(Chapter(seconds, match[2].strip()))
    validate_chapters(chapters, total_duration)
    return chapters


def resolve_chapters(inputs: MergeInputs) -> list[Chapter]:
    """Use explicit chapters or valid automatic boundaries; otherwise omit them."""
    if not inputs.segments:
        raise ValueError("at least 1 segment is required to merge")
    if any(not math.isfinite(s.duration) or s.duration <= 0 for s in inputs.segments):
        raise ValueError("segment duration must be a positive finite number of seconds")
    if inputs.no_chapters:
        if inputs.chapters is not None:
            raise ValueError("explicit chapters cannot be combined with no_chapters")
        return []
    total = sum(s.duration for s in inputs.segments)
    if inputs.chapters is not None:
        validate_chapters(inputs.chapters, total)
        return inputs.chapters
    chapters = []
    cumulative = 0.0
    for segment in inputs.segments:
        chapters.append(Chapter(int(cumulative), segment.label))
        cumulative += segment.duration
    try:
        validate_chapters(chapters, total)
    except ValueError:
        return []
    return chapters


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
        label = re.sub(r"([\\=;#\n])", r"\\\1", seg.label)
        lines.append(f"title={label}")
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

    # Per-segment VIDEO: force CFR 30fps + rebase PTS to 0 BEFORE concat.
    # The concat filter silently drops frames from any input with PTS
    # discontinuities (e.g. a stream-copy-concatenated `_cta` segment whose
    # internal join leaves a timestamp gap) — that cost ~23s on needle_duel.
    # `fps=30` resamples each input to a continuous CFR stream (a no-op on
    # already-clean 30fps CFR segments) and `setpts=PTS-STARTPTS` zeroes the
    # start, so concat sees gap-free inputs and keeps every frame.
    for i in range(n):
        parts.append(f"[{i}:v]fps=30,setpts=PTS-STARTPTS[v{i}n]")

    # Per-segment audio: resample to 48k, loudnorm to -14 LUFS
    for i in range(n):
        parts.append(
            f"[{i}:a]aresample=48000,loudnorm=I=-14:TP=-1:LRA=11[a{i}n]"
        )

    # Concat: interleave the normalized video + loudnorm'd audio streams
    concat_inputs = "".join(f"[v{i}n][a{i}n]" for i in range(n))
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[outv][outa]")

    return ";".join(parts)


def render(inputs: MergeInputs, output_path: Path) -> Path:
    """Concat and normalize media, optionally writing validated chapter markers."""
    chapters = resolve_chapters(inputs)
    total = sum(s.duration for s in inputs.segments)
    # Reuse the chapter serializers with durations derived from the one shared
    # final-video timeline. Explicit chapters may start inside any input segment.
    chapter_segments = [
        Segment(output_path, chapter.label,
                (chapters[i + 1].start_seconds if i + 1 < len(chapters) else total)
                - chapter.start_seconds)
        for i, chapter in enumerate(chapters)
    ]
    output_path.parent.mkdir(parents=True, exist_ok=True)

    ffmeta_path = output_path.parent / f"{output_path.stem}_ffmeta.txt"
    chapters_path = output_path.parent / f"{output_path.stem}_chapters.txt"
    if chapters:
        ffmeta_path.write_text(generate_ffmetadata(chapter_segments), encoding="utf-8")
    else:
        ffmeta_path.unlink(missing_ok=True)
        chapters_path.unlink(missing_ok=True)

    # Build ffmpeg command
    cmd: list[str] = ["ffmpeg", "-y"]
    for seg in inputs.segments:
        cmd.extend(["-i", str(seg.path.resolve())])
    # Disable inherited input chapters when there is no valid chapter list.
    ffmeta_input_idx = -1
    if chapters:
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

    if chapters:
        chapters_path.write_text(generate_chapters_text(chapter_segments), encoding="utf-8")

    return output_path

import subprocess
from pathlib import Path


def _build_filter_complex(
    keep_ranges: list[tuple[float, float]] | None,
    ass_filename: str,
    speed: float = 1.0,
) -> str:
    """Build an ffmpeg filter_complex string for cut and/or speed-modified output.

    The graph always emits the final labels ``[outv]`` and ``[outa]`` so
    callers can uniformly pass ``-map "[outv]" -map "[outa]"``.

    Stages:
      1. Cut stage -> ``[cv]``, ``[ca]``. When ``keep_ranges`` is non-empty,
         per-range ``trim``/``atrim`` + ``concat`` is used. Otherwise a
         ``null``/``anull`` passthrough keeps the graph shape uniform.
      2. Subtitle burn on the (possibly cut) video -> ``[sv]``.
      3. Speed stage -> ``[outv]``, ``[outa]``. When ``speed != 1.0`` the
         video is sped via ``setpts=PTS/<speed>`` and the audio via
         ``atempo=<speed>`` (pitch preserved). When ``speed == 1.0`` a
         ``null``/``anull`` passthrough keeps the final labels consistent.

    Subtitles are always burned BEFORE the speed stage so the danmaku
    timeline matches the original video timeline; setpts then scales the
    already-burned-in pixels, so danmaku naturally play faster/slower
    together with the rest of the frame.
    """
    parts: list[str] = []

    # Stage 1: cut or passthrough -> [cv], [ca]
    if keep_ranges and len(keep_ranges) > 0:
        for i, (start, end) in enumerate(keep_ranges):
            parts.append(
                f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]"
            )
            parts.append(
                f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
            )
        n = len(keep_ranges)
        concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
        parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[cv][ca]")
    else:
        parts.append("[0:v]null[cv]")
        parts.append("[0:a]anull[ca]")

    # Stage 2: subtitles on video -> [sv]
    parts.append(f"[cv]subtitles=f='{ass_filename}'[sv]")

    # Stage 3: speed or passthrough -> [outv], [outa]
    if speed != 1.0:
        parts.append(f"[sv]setpts=PTS/{speed}[outv]")
        parts.append(f"[ca]atempo={speed}[outa]")
    else:
        parts.append("[sv]null[outv]")
        parts.append("[ca]anull[outa]")

    return ";".join(parts)


def render(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    max_duration: int | None = None,
    keep_ranges: list[tuple[float, float]] | None = None,
    speed: float = 1.0,
) -> Path:
    """Burn an ASS subtitle into a video via ffmpeg.

    Two branches:

    - **Simple** (no cuts and ``speed == 1.0``): use ``-vf "subtitles=f='...'"``
      with ``-c:a copy``. Fastest; no audio re-encode.

    - **Complex** (``keep_ranges`` non-empty OR ``speed != 1.0``): use
      ``-filter_complex`` via :func:`_build_filter_complex`. Audio must be
      re-encoded (``-c:a aac -b:a 160k``) because ``atrim`` and ``atempo``
      both produce a new audio stream incompatible with ``-c:a copy``.

    ffmpeg's ``subtitles=`` filter is hostile to absolute paths (escaping
    hell), so we cwd into the temp directory and pass basenames for ``-i``
    and the subtitle filter. The output path stays absolute because
    ffmpeg output args do not go through filters.

    If ``max_duration`` is set, ffmpeg is invoked with ``-t N`` as an output
    option (placed after ``-i`` and before the encoding/filter args) to cap
    the burned output to the first N seconds — useful for fast preview
    iteration.

    ``speed`` is a playback multiplier in ``[0.5, 2.0]`` (validation lives
    in ``cli.run``). ``speed=1.0`` is the identity, routes through the
    simple path when no cuts are set. Non-identity speed forces the
    filter_complex branch because atempo cannot coexist with ``-c:a copy``.
    """
    if video_path.parent != ass_path.parent:
        raise ValueError(
            f"video and ASS must live in the same directory "
            f"(got {video_path.parent} and {ass_path.parent})"
        )
    temp_dir = video_path.parent
    output_path.parent.mkdir(parents=True, exist_ok=True)

    needs_complex = (
        (keep_ranges is not None and len(keep_ranges) > 0) or speed != 1.0
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.name,
    ]
    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])

    if needs_complex:
        filter_complex = _build_filter_complex(
            keep_ranges, ass_path.name, speed=speed
        )
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[outa]",
            "-c:a", "aac",
            "-b:a", "160k",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            str(output_path.resolve()),
        ])
    else:
        cmd.extend([
            "-vf", f"subtitles=f='{ass_path.name}'",
            "-c:a", "copy",
            "-c:v", "libx264",
            "-preset", "medium",
            "-crf", "20",
            str(output_path.resolve()),
        ])

    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=temp_dir)
    return output_path

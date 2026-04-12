import subprocess
from pathlib import Path


def _build_filter_complex(
    keep_ranges: list[tuple[float, float]], ass_filename: str
) -> str:
    """Build an ffmpeg filter_complex string that trims+concats the keep ranges
    and then burns an ASS subtitle onto the concatenated video.

    Output labels:
      - ``[outv]`` — final burned video stream
      - ``[ca]``   — concatenated audio stream

    Expected to be invoked with ``-map "[outv]" -map "[ca]"``.
    """
    if not keep_ranges:
        raise ValueError("keep_ranges must be non-empty")

    parts: list[str] = []
    for i, (start, end) in enumerate(keep_ranges):
        parts.append(
            f"[0:v]trim=start={start}:end={end},setpts=PTS-STARTPTS[v{i}]"
        )
    for i, (start, end) in enumerate(keep_ranges):
        parts.append(
            f"[0:a]atrim=start={start}:end={end},asetpts=PTS-STARTPTS[a{i}]"
        )

    n = len(keep_ranges)
    concat_inputs = "".join(f"[v{i}][a{i}]" for i in range(n))
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=1[cv][ca]")
    parts.append(f"[cv]subtitles=f='{ass_filename}'[outv]")

    return ";".join(parts)


def render(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    max_duration: int | None = None,
    keep_ranges: list[tuple[float, float]] | None = None,
) -> Path:
    """Burn an ASS subtitle into a video via ffmpeg.

    Two branches:

    - **Simple** (``keep_ranges`` is ``None`` or empty): use ``-vf "subtitles=f='...'"``
      with ``-c:a copy``. Fastest; no audio re-encode.

    - **Cut** (``keep_ranges`` is non-empty): use ``-filter_complex`` with
      ``trim``/``atrim``/``concat`` for each keep range, then burn subtitles
      onto the concatenated video. Audio must be re-encoded (``-c:a aac
      -b:a 160k``) because ``atrim`` produces a new audio stream.

    ffmpeg's ``subtitles=`` filter is hostile to absolute paths (escaping
    hell), so we cwd into the temp directory and pass basenames for ``-i``
    and the subtitle filter. The output path stays absolute because
    ffmpeg output args do not go through filters.

    If ``max_duration`` is set, ffmpeg is invoked with ``-t N`` as an output
    option (after ``-i``, before the encoding/filter args) to cap the burned
    output to the first N seconds — useful for fast preview iteration.
    """
    if video_path.parent != ass_path.parent:
        raise ValueError(
            f"video and ASS must live in the same directory "
            f"(got {video_path.parent} and {ass_path.parent})"
        )
    temp_dir = video_path.parent
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.name,
    ]
    if max_duration is not None:
        cmd.extend(["-t", str(max_duration)])

    if keep_ranges:
        filter_complex = _build_filter_complex(keep_ranges, ass_path.name)
        cmd.extend([
            "-filter_complex", filter_complex,
            "-map", "[outv]",
            "-map", "[ca]",
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

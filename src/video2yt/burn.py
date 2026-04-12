import subprocess
from pathlib import Path


def render(
    video_path: Path,
    ass_path: Path,
    output_path: Path,
    max_duration: int | None = None,
) -> Path:
    """Burn an ASS subtitle into a video via ffmpeg.

    ffmpeg's `subtitles=` filter is hostile to absolute paths (escaping hell),
    so we cwd into the temp directory and pass basenames for -i and -vf.
    The output path stays absolute because ffmpeg output args do not go
    through filters.

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

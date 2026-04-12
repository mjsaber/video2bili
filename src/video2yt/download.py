import subprocess
from pathlib import Path


def fetch(
    url: str,
    temp_dir: Path,
    quality: int,
    browser: str,
    bv_id: str,
    font_face: str = "Hiragino Sans GB",
    font_size: int = 40,
) -> tuple[Path, Path]:
    """Download video + danmaku ASS via yt-dlp + yt-dlp-danmaku plugin.

    Returns (video_path, ass_path).
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(temp_dir / f"{bv_id}.%(ext)s")
    format_spec = f"bv*[height<={quality}]+ba/b[height<={quality}]/b"

    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "-f", format_spec,
        "--write-subs",
        "--use-postprocessor", f"danmaku:font_face={font_face};font_size={font_size}",
        "--output", output_template,
        url,
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)

    # Find the actual video file (yt-dlp may choose mp4 or mkv)
    video_candidates = (
        sorted(temp_dir.glob(f"{bv_id}.mp4"))
        + sorted(temp_dir.glob(f"{bv_id}.mkv"))
        + sorted(temp_dir.glob(f"{bv_id}.webm"))
    )
    if not video_candidates:
        raise FileNotFoundError(
            f"yt-dlp did not produce a video file for {bv_id} in {temp_dir}"
        )
    video_path = video_candidates[0]

    # Find the ASS file (plugin decides exact suffix; usually .danmaku.ass)
    ass_candidates = sorted(temp_dir.glob(f"{bv_id}*.ass"))
    if not ass_candidates:
        raise FileNotFoundError(
            f"yt-dlp-danmaku did not produce an ASS file for {bv_id} in {temp_dir}"
        )
    ass_path = ass_candidates[0]

    return video_path, ass_path

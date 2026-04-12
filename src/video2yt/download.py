import subprocess
from pathlib import Path

import biliass


def fetch(
    url: str,
    temp_dir: Path,
    quality: int,
    browser: str,
    bv_id: str,
) -> tuple[Path, Path]:
    """Download video and raw danmaku XML via yt-dlp.

    Returns (video_path, xml_path). The ASS conversion happens separately in
    ``generate_ass`` so we can supply the real video dimensions (which aren't
    known until we probe the downloaded file) to biliass.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(temp_dir / f"{bv_id}.%(ext)s")
    format_spec = f"bv*[height<={quality}]+ba/b[height<={quality}]/b"

    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "-f", format_spec,
        "--write-subs",
        "--sub-langs", "danmaku",
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

    # Raw danmaku XML written by --write-subs (typically BV.danmaku.xml)
    xml_candidates = sorted(temp_dir.glob(f"{bv_id}*.xml"))
    if not xml_candidates:
        raise FileNotFoundError(
            f"yt-dlp did not produce a danmaku XML file for {bv_id} in {temp_dir}"
        )
    xml_path = xml_candidates[0]

    return video_path, xml_path


def generate_ass(
    xml_path: Path,
    ass_path: Path,
    width: int,
    height: int,
    font_face: str,
    font_size: int,
) -> Path:
    """Convert Bilibili danmaku XML to ASS via biliass.

    The ``font_size`` parameter is what biliass renders a standard
    (nominal size=25) danmaku as — biliass itself scales non-standard danmaku
    proportionally.
    """
    xml_bytes = xml_path.read_bytes()
    ass_text = biliass.convert_to_ass(
        xml_bytes,
        stage_width=width,
        stage_height=height,
        font_face=font_face,
        font_size=font_size,
    )
    ass_path.write_text(ass_text, encoding="utf-8")
    return ass_path

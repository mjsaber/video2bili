"""Place a brief contextual CTA over gameplay, preserving its timeline and audio."""
from __future__ import annotations

import math
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unicodedata

from video2yt.intro_compose import resolve_font
from video2yt.merge import Segment, validate_segments_strict


def render(
    video: Path,
    text: str,
    at: float,
    output: Path,
    *,
    duration: float = 4.0,
    position: str = "top",
    font: Path | None = None,
    overwrite: bool = False,
) -> Path:
    """Overlay 1–40 characters on an already merge-compatible gameplay MP4.

    Input must be 1080p/30fps H.264 with audio. Video is encoded once; audio
    packets are copied, without cuts or volume changes. Only a validated render
    replaces the destination, and only when overwriting was explicitly enabled.
    """
    if not text.strip() or len(text) > 40 or any(
        unicodedata.category(char).startswith("C") or char in "\n\r\t\u2028\u2029"
        for char in text
    ):
        raise ValueError("CTA text must be one line of 1–40 characters, without control characters")
    if not math.isfinite(at) or at < 0:
        raise ValueError("CTA time must be finite and >= 0")
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError("CTA duration must be finite and > 0")
    if position not in {"top", "bottom"}:
        raise ValueError("CTA position must be top or bottom")
    source_path = video.resolve()
    output_path = output.absolute()
    if source_path == output_path.resolve() or (
        source_path.exists() and output_path.exists() and source_path.samefile(output_path)
    ):
        raise ValueError("CTA output must differ from input video")
    if output_path.exists() and not overwrite:
        raise FileExistsError(f"output exists; pass --overwrite to replace: {output}")
    if output_path.suffix.lower() != ".mp4":
        raise ValueError("CTA output must be an .mp4 file")
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} not found in PATH")
    source = Segment(source_path, "gameplay")
    validate_segments_strict([source])
    if at + duration > source.duration:
        raise ValueError(f"CTA window must lie within the clip duration ({source.duration:.3f}s)")
    font_path = Path(font or resolve_font()).resolve()
    if not font_path.is_file():
        raise FileNotFoundError(f"font not found: {font_path}")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cta-", dir=output_path.parent) as work_dir:
        work = Path(work_dir)
        (work / "cta.txt").write_text(text, encoding="utf-8")
        # Literal local basenames avoid ffmpeg filter escaping for any user path.
        shutil.copyfile(font_path, work / "font.ttf")
        staged = work / "rendered.mp4"
        y = "64" if position == "top" else "h-text_h-64"
        vf = ("drawtext=fontfile=font.ttf:textfile=cta.txt:expansion=none:"
              "fontsize=42:fontcolor=white:box=1:boxcolor=black@0.80:boxborderw=20:"
              f"x=(w-text_w)/2:y={y}:enable='gte(t,{at:.9f})*lt(t,{at + duration:.9f})'")
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-nostdin", "-n",
             "-i", str(source_path), "-map", "0:v:0", "-map", "0:a",
             "-map_metadata", "0", "-map_chapters", "0", "-vf", vf,
             "-c:v", "libx264", "-preset", "fast", "-crf", "18",
             "-pix_fmt", "yuv420p", "-r", "30", "-c:a", "copy",
             "-movflags", "+faststart", str(staged)],
            cwd=work, check=True, capture_output=True, text=True,
        )
        result = Segment(staged, "CTA output")
        validate_segments_strict([result])
        # Allow container/frame rounding, never seconds of truncation.
        if abs(result.duration - source.duration) > 0.1:
            raise ValueError(f"CTA output duration changed: {source.duration:.3f}s -> {result.duration:.3f}s")
        if overwrite:
            os.replace(staged, output_path)
        else:
            # Exclusive publication also refuses an output created during render.
            os.link(staged, output_path)
    return output

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class MediaInfo:
    duration: float
    width: int
    height: int
    has_video: bool
    has_audio: bool
    vcodec: str
    acodec: str | None
    size_bytes: int


def probe(path: Path) -> MediaInfo:
    if not path.exists():
        raise FileNotFoundError(f"file not found: {path}")
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_format", "-show_streams",
            str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    fmt = data.get("format", {})
    duration_raw = fmt.get("duration")
    duration = float(duration_raw) if duration_raw is not None else 0.0
    width = int(video_streams[0].get("width", 0)) if video_streams else 0
    height = int(video_streams[0].get("height", 0)) if video_streams else 0
    vcodec = video_streams[0].get("codec_name", "") if video_streams else ""
    acodec = audio_streams[0].get("codec_name") if audio_streams else None
    return MediaInfo(
        duration=duration,
        width=width,
        height=height,
        has_video=bool(video_streams),
        has_audio=bool(audio_streams),
        vcodec=vcodec,
        acodec=acodec,
        size_bytes=path.stat().st_size,
    )

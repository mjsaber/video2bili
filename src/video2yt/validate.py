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


def check_source(info: MediaInfo, requested_quality: int) -> list[str]:
    """Validate a downloaded source video. Raises on hard failures; returns warnings."""
    if not info.has_video:
        raise ValueError("source has no video stream")
    if info.duration <= 0:
        raise ValueError(f"source has zero or unknown duration ({info.duration})")
    warnings: list[str] = []
    if not info.has_audio:
        warnings.append("source has no audio stream (uncommon but allowed)")
    if info.height < requested_quality:
        warnings.append(
            f"source resolution {info.width}x{info.height} is lower than "
            f"requested {requested_quality}p — cookie may not be working "
            f"or this video has no higher-quality variant"
        )
    return warnings


def check_ass(path: Path) -> int:
    """Validate an ASS subtitle file. Returns Dialogue line count."""
    if not path.exists():
        raise ValueError(f"ASS file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8")
    except UnicodeDecodeError as e:
        raise ValueError(f"ASS file is not valid UTF-8: {path}") from e
    if "[Events]" not in text:
        raise ValueError(f"ASS file missing [Events] section: {path}")
    dialogue_count = sum(
        1 for line in text.splitlines() if line.startswith("Dialogue:")
    )
    if dialogue_count == 0:
        raise ValueError(
            f"ASS file has no Dialogue lines (no danmaku available): {path}"
        )
    return dialogue_count

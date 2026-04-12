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


def check_output(
    source: MediaInfo,
    output: MediaInfo,
    expected_duration: float | None = None,
) -> list[str]:
    """Validate burned output against source. Raises on hard failures; returns warnings.

    expected_duration overrides the source duration for the +/-1s duration check.
    Pass the preview duration (seconds) when using preview mode, otherwise leave
    as None to compare against source duration.
    """
    if output.size_bytes == 0:
        raise ValueError("output file is empty")
    if not output.has_video:
        raise ValueError("output has no video stream")
    if source.has_audio and not output.has_audio:
        raise ValueError("source had audio but output lost it")
    if output.vcodec != "h264":
        raise ValueError(
            f"output vcodec is {output.vcodec!r}, expected 'h264' "
            f"(libx264 encode params did not take effect)"
        )
    expected = expected_duration if expected_duration is not None else source.duration
    if abs(output.duration - expected) >= 1.0:
        raise ValueError(
            f"output duration {output.duration:.2f}s differs from expected "
            f"{expected:.2f}s by more than 1 second (possible truncation)"
        )
    if output.width != source.width or output.height != source.height:
        raise ValueError(
            f"output resolution {output.width}x{output.height} differs from "
            f"source {source.width}x{source.height}"
        )
    warnings: list[str] = []
    if source.size_bytes > 0:
        if expected_duration is not None and source.duration > 0:
            # Scale expected size proportionally to preview duration
            duration_ratio = expected_duration / source.duration
            expected_size = source.size_bytes * duration_ratio
        else:
            expected_size = float(source.size_bytes)
        ratio = output.size_bytes / expected_size if expected_size > 0 else 1.0
        if ratio < 0.3 or ratio > 5.0:
            warnings.append(
                f"output size is {ratio:.2f}x expected ({output.size_bytes} vs "
                f"{int(expected_size)} bytes); may indicate encoding issue"
            )
    return warnings

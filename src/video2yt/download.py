"""Thin yt-dlp subprocess wrapper. The biliass invocation lives in fetch.py."""

import json
import subprocess
from pathlib import Path


class TruncatedDownloadError(RuntimeError):
    """yt-dlp merger hiccup: a fresh download's video/audio stream
    durations disagree (BV1UodgBJEXj-style). Subclass of RuntimeError so
    existing `except RuntimeError` callers are unaffected; a dedicated type
    lets video2yt-prefetch distinguish retryable truncation from other
    failures.
    """


def get_metadata(url: str, browser: str) -> dict:
    """Fetch video metadata via `yt-dlp --dump-json --skip-download`.

    Returns the parsed JSON dict (title, duration, uploader, etc.).
    Fast operation — only metadata, no video bytes transferred.
    """
    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "--dump-json",
        "--skip-download",
        url,
    ]
    result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return json.loads(result.stdout)


def _stream_durations(path: Path) -> tuple[float, float]:
    """Return ``(video_duration, audio_duration)`` in seconds for ``path``.

    Either may be ``0.0`` if the stream is missing. Used by :func:`fetch` to
    detect cached/downloaded files where yt-dlp's merger truncated audio
    (BV1UodgBJEXj from 2026-05-23 muxed only 220s of a 1147s segment because
    of a transient merger hiccup; the cache then served the broken file
    forever on subsequent runs).
    """
    result = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-print_format", "json",
            "-show_streams",
            str(path),
        ],
        check=True, capture_output=True, text=True,
    )
    data = json.loads(result.stdout)
    v_dur = 0.0
    a_dur = 0.0
    for s in data.get("streams", []):
        if s.get("codec_type") == "video" and v_dur == 0.0:
            v_dur = float(s.get("duration") or 0.0)
        elif s.get("codec_type") == "audio" and a_dur == 0.0:
            a_dur = float(s.get("duration") or 0.0)
    return v_dur, a_dur


DURATION_MISMATCH_TOLERANCE_SECONDS = 2.0


def _is_av_duration_consistent(path: Path) -> bool:
    """True if the file's audio stream duration is within tolerance of video.

    Files with no audio stream pass (audio duration of 0.0 just means
    audio-less video, not a broken download).
    """
    v_dur, a_dur = _stream_durations(path)
    if a_dur == 0.0:
        return True
    return abs(v_dur - a_dur) <= DURATION_MISMATCH_TOLERANCE_SECONDS


def _build_format_spec(quality: int, codec: str) -> str:
    """Build yt-dlp format selector with quality cap and codec preference.

    Layers:
      1. bv*[height<=Q][vcodec^=CODEC] + ba — split streams, codec-filtered
      2. b[height<=Q][vcodec^=CODEC] — pre-muxed with codec filter
      3. b[vcodec^=CODEC] — any codec-matching file
      4. b — absolute fallback (should be rare)
    """
    h = f"[height<={quality}]"
    if codec == "h264":
        cv = "[vcodec^=avc1]"
    elif codec == "h265":
        cv = "[vcodec^=hev1]"
    else:  # auto
        cv = ""
    if cv == "":
        return f"bv*{h}+ba/b{h}/b"
    return f"bv*{h}{cv}+ba/b{h}{cv}/b{cv}/b"


def fetch(
    url: str,
    temp_dir: Path,
    quality: int,
    browser: str,
    bv_id: str,
    codec: str = "h264",
) -> tuple[Path, Path, bool]:
    """Download video and raw danmaku XML via yt-dlp.

    Returns ``(video_path, xml_path, from_cache)``. If both the video file
    and danmaku XML for this ``bv_id`` already exist in ``temp_dir``, skip
    the yt-dlp invocation entirely and return the cached paths with
    ``from_cache=True``. Otherwise run yt-dlp (which will overwrite any
    partial artifacts) and return ``from_cache=False``.

    The ASS conversion happens separately in ``fetch.generate_ass`` so we
    can supply the real video dimensions (known only after probing the
    downloaded file) to biliass.
    """
    temp_dir.mkdir(parents=True, exist_ok=True)

    # Cache probe: both raw files already present -> skip yt-dlp entirely.
    cached_video_candidates = (
        sorted(temp_dir.glob(f"{bv_id}.mp4"))
        + sorted(temp_dir.glob(f"{bv_id}.mkv"))
        + sorted(temp_dir.glob(f"{bv_id}.webm"))
    )
    cached_xml_candidates = sorted(temp_dir.glob(f"{bv_id}*.xml"))
    if cached_video_candidates and cached_xml_candidates:
        cached_video = cached_video_candidates[0]
        if _is_av_duration_consistent(cached_video):
            return cached_video, cached_xml_candidates[0], True
        # Audio stream duration disagrees with video — yt-dlp's previous
        # merge truncated audio. Quarantine the bad files and fall through
        # to a fresh download.
        cached_video.rename(cached_video.with_suffix(cached_video.suffix + ".broken"))
        for xml in cached_xml_candidates:
            xml.rename(xml.with_suffix(xml.suffix + ".broken"))

    # Cache miss — invoke yt-dlp.
    output_template = str(temp_dir / f"{bv_id}.%(ext)s")
    format_spec = _build_format_spec(quality, codec)

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

    if not _is_av_duration_consistent(video_path):
        v_dur, a_dur = _stream_durations(video_path)
        raise TruncatedDownloadError(
            f"yt-dlp produced {video_path.name} with truncated audio "
            f"(video {v_dur:.1f}s vs audio {a_dur:.1f}s). This is the "
            f"BV1UodgBJEXj-style merger hiccup — re-run to download again, "
            f"or run yt-dlp manually to inspect."
        )

    return video_path, xml_path, False

"""Stage 1 of the per-segment pipeline: yt-dlp + biliass orchestration.

Carved out of the old monolithic ``cli.run`` chain so that Step 6 can run
fetch independently of the rest of the pipeline (stems / subtitle / mix /
burn). The spec is ``docs/superpowers/specs/2026-05-24-step6-restructure.md``
§4 Stage 1 + §7 ``video2yt-fetch``.

Contract: takes a Bilibili URL + a parent temp dir, returns a ``FetchResult``
with the raw mp4, raw danmaku XML, and the un-cut biliass ASS — does NOT
apply any ``--cut`` rewrite (that is Stage 5's job; cuts come from
orchestrator-level flags that are not known to this stage).
"""

import re
import time
from dataclasses import dataclass
from pathlib import Path

import biliass

from video2yt import download, validate

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")

# Bilibili's native danmaku scaling: the web/client player renders a standard
# (nominal size=25) danmaku at ``player_height * 25 / 540`` pixels.
REFERENCE_PLAYER_HEIGHT = 540
REFERENCE_STANDARD_SIZE = 25

# Subfolder name conventions (kept identical to the old cli.py constants).
MAX_TITLE_DIR_LENGTH = 60
UPLOADER_PREFIX_LENGTH = 4
UPLOADER_TITLE_SEPARATOR = "："  # U+FF1A fullwidth colon


@dataclass
class FetchResult:
    bv_id: str
    raw_video: Path                 # <dir>/<bv>.mp4 (or .mkv/.webm)
    danmaku_xml: Path               # <dir>/<bv>.danmaku.xml
    danmaku_ass: Path               # <dir>/<bv>.danmaku.ass (un-cut)
    metadata: dict                  # yt-dlp dump-json output
    info: validate.MediaInfo        # ffprobe of raw_video
    from_cache: bool
    n_danmaku: int
    temp_subdir: Path
    elapsed: float


def extract_bv_id(url: str) -> str:
    m = BV_PATTERN.search(url)
    if not m:
        raise ValueError(
            f"URL does not contain a BV id: {url!r}\n"
            f"expected format: https://www.bilibili.com/video/BV..."
        )
    return m.group(1)


def compute_font_size(video_height: int) -> int:
    """Bilibili native scaling: standard (size=25) danmaku = height * 25/540 px."""
    return round(video_height * REFERENCE_STANDARD_SIZE / REFERENCE_PLAYER_HEIGHT)


def _sanitize_title(title: str, max_length: int = MAX_TITLE_DIR_LENGTH) -> str:
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', '_', title)
    cleaned = re.sub(r'\s+', ' ', cleaned)
    cleaned = re.sub(r'_+', '_', cleaned)
    cleaned = cleaned.strip(' ._')
    if len(cleaned) > max_length:
        cleaned = cleaned[:max_length].rstrip(' ._')
    return cleaned or "unnamed"


def _build_dir_name(
    metadata: dict,
    bv_id: str,
    uploader_prefix_length: int = UPLOADER_PREFIX_LENGTH,
) -> str:
    """Build the ``<uploader_prefix>：<title>`` per-segment subfolder name."""
    uploader = metadata.get("uploader") or metadata.get("channel") or ""
    uploader_prefix = uploader[:uploader_prefix_length]
    title = metadata.get("title") or bv_id
    if uploader_prefix:
        combined = f"{uploader_prefix}{UPLOADER_TITLE_SEPARATOR}{title}"
    else:
        combined = title
    return _sanitize_title(combined)


def generate_ass(
    xml_path: Path,
    ass_path: Path,
    width: int,
    height: int,
    font_face: str,
    font_size: int,
) -> Path:
    """Convert Bilibili danmaku XML to ASS via biliass."""
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


def fetch_and_build(
    url: str,
    temp_dir: Path,
    quality: int = 1080,
    codec: str = "h264",
    browser: str = "chrome",
    font_face: str = "Hiragino Sans GB",
    font_size: int | None = None,
) -> FetchResult:
    """Stage 1: download raw mp4 + danmaku XML, generate the un-cut danmaku ASS.

    Steps:
      1. Extract BV id from URL.
      2. yt-dlp metadata → per-segment subfolder name.
      3. yt-dlp download (cache-aware — see ``download.fetch``).
      4. ffprobe the downloaded video for width/height/duration.
      5. biliass XML → ASS at ``<bv>.danmaku.ass``. Skipped if the ASS
         file already exists (cheap warm-cache path).

    Does NOT call ``cuts.rewrite_ass_for_cuts``. That responsibility lives
    in Stage 5 (burn) so the cut flags do not need to flow through fetch.
    """
    t_start = time.monotonic()

    bv_id = extract_bv_id(url)
    metadata = download.get_metadata(url, browser)
    dir_name = _build_dir_name(metadata, bv_id)
    temp_subdir = temp_dir / dir_name
    temp_subdir.mkdir(parents=True, exist_ok=True)

    raw_video, danmaku_xml, from_cache = download.fetch(
        url=url,
        temp_dir=temp_subdir,
        quality=quality,
        browser=browser,
        bv_id=bv_id,
        codec=codec,
    )

    info = validate.probe(raw_video)

    resolved_font_size = (
        font_size if font_size is not None
        else compute_font_size(info.height)
    )

    danmaku_ass = temp_subdir / f"{bv_id}.danmaku.ass"
    # Always regenerate the ASS: it's sub-second on a typical 17-min segment,
    # and skipping based on file existence alone would silently serve stale
    # danmaku styling whenever the user changes --font-size or --font-face
    # (codex T2 review 2026-05-24). If this becomes expensive, switch to a
    # meta-sidecar keyed on (font_face, font_size, stage_w, stage_h).
    generate_ass(
        xml_path=danmaku_xml,
        ass_path=danmaku_ass,
        width=info.width,
        height=info.height,
        font_face=font_face,
        font_size=resolved_font_size,
    )

    n_danmaku = validate.check_ass(danmaku_ass)
    elapsed = time.monotonic() - t_start

    return FetchResult(
        bv_id=bv_id,
        raw_video=raw_video,
        danmaku_xml=danmaku_xml,
        danmaku_ass=danmaku_ass,
        metadata=metadata,
        info=info,
        from_cache=from_cache,
        n_danmaku=n_danmaku,
        temp_subdir=temp_subdir,
        elapsed=elapsed,
    )

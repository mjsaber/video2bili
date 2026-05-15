"""video2yt-subtitle — detection + ASR + cleanup + split + burn pipeline.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

import re
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml

# Bilibili's renderer convention for type=4 (bottom-fixed) danmaku display time.
# Source: spec §5.1 D. Changing this requires re-tuning danmaku detection thresholds.
BILIBILI_FIXED_DANMAKU_SECONDS = 5.0

# Subtitle entries shorter than this get extended forward (cascading; never overlap).
# Spec §5.1 C.
HARD_FLOOR_SECONDS = 0.8

# Codex CLI subprocess timeout per cleanup call. Spec §7 — failure here is
# downgraded to WARNING + raw-ASR fallback.
CLEANUP_TIMEOUT_SECONDS = 30

# Split-stage punctuation classes (spec §5.1 C).
SENTENCE_PUNCT = "。！？"
CLAUSE_PUNCT = "；，、"


@dataclass(frozen=True)
class Glossary:
    corrections: dict[str, str]
    canonical: list[str]


def load_glossary(path: Path | None) -> Glossary:
    """Load a glossary YAML. ``None`` → packaged default ``bg_glossary.yaml``."""
    if path is None:
        import importlib.resources
        text = (
            importlib.resources.files("video2yt.data")
            / "bg_glossary.yaml"
        ).read_text(encoding="utf-8")
    else:
        if not path.is_file():
            raise FileNotFoundError(f"glossary file not found: {path}")
        text = path.read_text(encoding="utf-8")
    data = yaml.safe_load(text) or {}
    corrections = data.get("corrections", {})
    canonical = data.get("canonical", [])
    if not isinstance(corrections, dict):
        raise ValueError(f"glossary 'corrections' must be a mapping, got {type(corrections).__name__}")
    if not isinstance(canonical, list):
        raise ValueError(f"glossary 'canonical' must be a list, got {type(canonical).__name__}")
    return Glossary(corrections=corrections, canonical=canonical)


@dataclass(frozen=True)
class DanmakuSignal:
    fixed_count: int
    coverage_seconds: float
    coverage_ratio: float
    hit: bool


def scan_danmaku(
    xml_path: Path,
    segment_duration: float,
    min_fixed: int = 10,
    min_coverage_ratio: float = 0.30,
) -> DanmakuSignal:
    """Scan a Bilibili danmaku XML for bottom-fixed (type=4) entries.

    Coverage = total length of UNION of [start_i, start_i + 5.0) intervals,
    clipped to [0, segment_duration]. See spec §5.1 D.
    """
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as e:
        raise ValueError(f"malformed danmaku XML: {xml_path}: {e}") from e

    intervals: list[tuple[float, float]] = []
    fixed_count = 0
    for d in root.findall("d"):
        p_attr = d.get("p", "")
        parts = p_attr.split(",")
        if len(parts) < 2:
            raise ValueError(
                f"malformed danmaku XML: <d p={p_attr!r}> has < 2 comma-separated fields"
            )
        try:
            start = float(parts[0])
            dtype = int(parts[1])
        except ValueError as e:
            raise ValueError(
                f"malformed danmaku XML: <d p={p_attr!r}> bad start/type: {e}"
            ) from e
        if dtype != 4:
            continue
        fixed_count += 1
        end = min(start + BILIBILI_FIXED_DANMAKU_SECONDS, segment_duration)
        start = max(start, 0.0)
        if end > start:
            intervals.append((start, end))

    # Union of intervals
    intervals.sort()
    coverage = 0.0
    cur_start: float | None = None
    cur_end: float | None = None
    for s, e in intervals:
        if cur_start is None:
            cur_start, cur_end = s, e
        elif s <= cur_end:    # overlap
            cur_end = max(cur_end, e)
        else:
            coverage += cur_end - cur_start
            cur_start, cur_end = s, e
    if cur_start is not None:
        coverage += cur_end - cur_start

    ratio = coverage / segment_duration if segment_duration > 0 else 0.0
    hit = (fixed_count >= min_fixed) and (ratio >= min_coverage_ratio)
    return DanmakuSignal(
        fixed_count=fixed_count,
        coverage_seconds=coverage,
        coverage_ratio=ratio,
        hit=hit,
    )


@dataclass(frozen=True)
class OcrSignal:
    sampled_frames: int
    frames_with_stable_text: int
    stable_text_ratio: float
    hit: bool


@dataclass(frozen=True)
class Decision:
    add_subtitles: bool
    reason: str


def decide(
    force: str | None,
    danmaku: DanmakuSignal | None,
    ocr: OcrSignal | None,
) -> Decision:
    """Short-circuit decision. Priority: force > danmaku > OCR.

    Any signal indicating "existing bottom subtitles present" → skip.
    """
    if force is not None:
        if force == "add":
            return Decision(True, "force=add (manual override)")
        if force == "skip":
            return Decision(False, "force=skip (manual override)")
        raise ValueError(
            f"invalid force value {force!r}; expected 'add', 'skip', or None"
        )
    if danmaku is not None and danmaku.hit:
        return Decision(
            False,
            f"danmaku scan: {danmaku.fixed_count} type=4 fixed, "
            f"{danmaku.coverage_ratio * 100:.1f}% coverage → SKIP",
        )
    if ocr is not None and ocr.hit:
        return Decision(
            False,
            f"OCR sample: {ocr.frames_with_stable_text}/{ocr.sampled_frames} frames "
            f"with stable bottom text ({ocr.stable_text_ratio * 100:.1f}%) → SKIP",
        )
    return Decision(True, "no existing-subtitle signal detected → ADD")


import logging
import subprocess

_log = logging.getLogger(__name__)


def _extract_frames(
    video_path: Path, interval_seconds: float, duration: float
) -> list[bytes]:
    """ffmpeg-extract one JPEG per ``interval_seconds`` of the video to memory.

    Returns a list of raw JPEG-encoded byte strings (one per sampled frame).
    Frames are scaled by 0.5 to keep memory low; OCR doesn't need full-res.
    """
    count = max(1, int(duration / interval_seconds))
    cmd = [
        "ffmpeg", "-v", "error",
        "-i", str(video_path.resolve()),
        "-vf", f"fps=1/{interval_seconds},scale=iw/2:ih/2",
        "-frames:v", str(count),
        "-f", "image2pipe", "-vcodec", "mjpeg",
        "-",
    ]
    result = subprocess.run(cmd, check=True, capture_output=True)
    return _split_mjpeg_stream(result.stdout)


def _split_mjpeg_stream(blob: bytes) -> list[bytes]:
    """Split a concatenated MJPEG byte stream into individual JPEGs by SOI/EOI markers."""
    SOI = b"\xff\xd8"
    EOI = b"\xff\xd9"
    frames = []
    i = 0
    while True:
        start = blob.find(SOI, i)
        if start == -1:
            break
        end = blob.find(EOI, start + 2)
        if end == -1:
            break
        frames.append(blob[start : end + 2])
        i = end + 2
    return frames


def _run_rapidocr(jpeg_bytes: bytes, crop_y_range: tuple[float, float]):
    """Run RapidOCR on the bottom band of one JPEG frame.

    Returns a list of (box, text, score) tuples for boxes whose vertical centroid
    falls inside ``crop_y_range`` (fractions of frame height, e.g. (0.82, 0.98)).
    Lazy import; the real engine lives in the optional ``subtitle`` extra.
    """
    from rapidocr_onnxruntime import RapidOCR
    import numpy as np
    from PIL import Image
    import io
    img = np.array(Image.open(io.BytesIO(jpeg_bytes)))
    h = img.shape[0]
    y_lo = int(h * crop_y_range[0])
    y_hi = int(h * crop_y_range[1])
    crop = img[y_lo:y_hi]
    engine = RapidOCR()
    raw, _ = engine(crop)
    if not raw:
        return []
    # Translate box y-coords back into full-frame coords for cluster stability check.
    boxes = []
    for box, text, score in raw:
        translated = tuple((x, y + y_lo) for x, y in box)
        boxes.append((translated, text, score))
    return boxes


def sample_ocr(
    video_path: Path,
    segment_duration: float,
    interval_seconds: float = 5.0,
    min_stable_ratio: float = 0.30,
    crop_y_range: tuple[float, float] = (0.82, 0.98),
    cluster_y_tolerance: int = 40,
) -> OcrSignal:
    """Sample frames + OCR the bottom band + check if a y-position cluster is stable.

    "Stable" = the same vertical position (within ``cluster_y_tolerance`` pixels)
    has detected text in at least ``min_stable_ratio`` of sampled frames. This
    distinguishes burned-in subtitles (stable position) from floating danmaku
    (drifting position) per spec §5.1 / OCR detection.

    Fail-open: any internal failure returns a no-hit signal rather than raising.
    """
    try:
        frames = _extract_frames(video_path, interval_seconds, segment_duration)
    except Exception as e:
        _log.warning("ffmpeg frame extract failed: %s; treating as no-text-detected", e)
        return OcrSignal(0, 0, 0.0, hit=False)

    if not frames:
        return OcrSignal(0, 0, 0.0, hit=False)

    # For each frame, run OCR and record the y-centroids of detected boxes.
    per_frame_y_centroids: list[list[int]] = []
    for f in frames:
        try:
            boxes = _run_rapidocr(f, crop_y_range)
        except Exception as e:
            _log.warning("rapidocr failed on a frame: %s; skipping that frame", e)
            per_frame_y_centroids.append([])
            continue
        ys = []
        for box, _text, _score in boxes:
            y_centroid = sum(p[1] for p in box) // len(box)
            ys.append(y_centroid)
        per_frame_y_centroids.append(ys)

    # Cluster y-centroids across frames; pick the largest cluster.
    all_ys = [y for ys in per_frame_y_centroids for y in ys]
    if not all_ys:
        return OcrSignal(len(frames), 0, 0.0, hit=False)

    # Greedy 1D clustering by tolerance. A cluster's allowed span is anchored
    # at its first (min) y: a new y joins only if it's within tolerance of the
    # cluster's anchor, NOT of its last appended element. This prevents drifting
    # boxes (each within tolerance of the previous one but spanning a wide
    # range overall) from chaining into one cluster.
    sorted_ys = sorted(all_ys)
    clusters: list[list[int]] = [[sorted_ys[0]]]
    for y in sorted_ys[1:]:
        if y - clusters[-1][0] <= cluster_y_tolerance:
            clusters[-1].append(y)
        else:
            clusters.append([y])

    # Each cluster has a representative range; how many frames contributed?
    best_frame_support = 0
    for cl in clusters:
        lo, hi = min(cl), max(cl)
        support = sum(
            1
            for ys in per_frame_y_centroids
            if any(lo <= y <= hi for y in ys)
        )
        best_frame_support = max(best_frame_support, support)

    n = len(frames)
    ratio = best_frame_support / n
    return OcrSignal(
        sampled_frames=n,
        frames_with_stable_text=best_frame_support,
        stable_text_ratio=ratio,
        hit=ratio >= min_stable_ratio,
    )


@dataclass(frozen=True)
class FunASRSegment:
    start: float
    end: float
    text: str


def _extract_wav(video_path: Path, dest_dir: Path) -> Path:
    """Extract a mono 16kHz wav using ffmpeg into ``dest_dir/audio.wav``."""
    out = dest_dir / "audio.wav"
    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(video_path.resolve()),
        "-ac", "1", "-ar", "16000",
        "-vn",
        str(out.resolve()),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return out


def _run_funasr(wav_path: Path) -> list[tuple[float, float, str]]:
    """Run SenseVoice-Small on a wav file. Lazy import from the optional extra.

    Returns list of (start_seconds, end_seconds, text). Each tuple is one
    FunASR segment (sentence-level by default for SenseVoiceSmall).
    """
    from funasr import AutoModel
    model = AutoModel(
        model="iic/SenseVoiceSmall",
        vad_model="fsmn-vad",
        vad_kwargs={"max_single_segment_time": 15000},
        trust_remote_code=True,
    )
    res = model.generate(input=str(wav_path), batch_size_s=60)
    out: list[tuple[float, float, str]] = []
    for item in res:
        # FunASR returns dicts with 'timestamp' (ms pairs) and 'text' per segment
        for seg in item.get("sentence_info", []) or []:
            start_ms = seg.get("start", 0)
            end_ms = seg.get("end", start_ms)
            text = seg.get("text", "").strip()
            if text:
                out.append((start_ms / 1000.0, end_ms / 1000.0, text))
    return out


def transcribe(video_path: Path) -> list[FunASRSegment]:
    """Run SenseVoice on the segment's audio. Returns FunASR-level segments."""
    with tempfile.TemporaryDirectory() as td:
        wav = _extract_wav(video_path, Path(td))
        raw = _run_funasr(wav)
    return [FunASRSegment(start, end, text.strip()) for (start, end, text) in raw]


def _format_srt_time(seconds: float) -> str:
    total_ms = int(round(seconds * 1000))
    hh = total_ms // 3_600_000
    mm = (total_ms % 3_600_000) // 60_000
    ss = (total_ms % 60_000) // 1000
    ms = total_ms % 1000
    return f"{hh:02d}:{mm:02d}:{ss:02d},{ms:03d}"


def _parse_srt_time(text: str) -> float:
    m = re.match(r"(\d{2}):(\d{2}):(\d{2}),(\d{3})", text.strip())
    if not m:
        raise ValueError(f"invalid SRT timestamp: {text!r}")
    hh, mm, ss, ms = (int(g) for g in m.groups())
    return hh * 3600 + mm * 60 + ss + ms / 1000.0


def segments_to_srt(segments: list[FunASRSegment]) -> str:
    """Serialize FunASR segments as a standard SRT (one entry per segment)."""
    lines = []
    for i, seg in enumerate(segments, start=1):
        lines.append(str(i))
        lines.append(f"{_format_srt_time(seg.start)} --> {_format_srt_time(seg.end)}")
        lines.append(seg.text)
        lines.append("")
    return "\n".join(lines) + "\n"


def parse_srt_to_segments(srt_text: str) -> list[FunASRSegment]:
    """Parse a standard SRT (one entry per FunASR segment) back into segments.

    Multi-line text bodies are joined with '\n'; the format we WRITE always uses
    one line, but we tolerate hand-edited cache files.
    """
    blocks = re.split(r"\n\s*\n", srt_text.strip())
    segs: list[FunASRSegment] = []
    for block in blocks:
        lines = [ln for ln in block.splitlines() if ln.strip()]
        if len(lines) < 2:
            continue
        # Optional numeric index
        start_idx = 1 if lines[0].strip().isdigit() else 0
        if start_idx >= len(lines):
            continue
        m = re.match(r"(\S+)\s*-->\s*(\S+)", lines[start_idx])
        if not m:
            continue
        start = _parse_srt_time(m.group(1))
        end = _parse_srt_time(m.group(2))
        text = "\n".join(lines[start_idx + 1 :]).strip()
        if not text:
            continue
        segs.append(FunASRSegment(start, end, text))
    return segs

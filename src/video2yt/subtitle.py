"""video2yt-subtitle — detection + ASR + cleanup + split + burn pipeline.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

import re
import shutil
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import yaml

from video2yt.compose import srt_to_ass

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


@dataclass(frozen=True)
class SrtEntry:
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


def _run_asr(wav_path: Path, model_name: str = "large-v3") -> list[tuple[float, float, str]]:
    """Run whisperx free transcription on a wav file. Lazy import to keep
    subtitle.py importable without whisperx installed (matches transcribe.py
    pattern). Returns list of (start_s, end_s, text) per whisper segment.

    Hallucination guardrails:
    - no_speech_threshold raised slightly above default
    - compression_ratio_threshold default
    - whisperx's built-in VAD pre-filtering kills most music-only chunks
    """
    import whisperx

    audio = whisperx.load_audio(str(wav_path))
    model = whisperx.load_model(
        model_name, device="cpu", compute_type="int8", language="zh",
        asr_options={
            "no_speech_threshold": 0.7,        # stricter — drop music-only segments
            "compression_ratio_threshold": 2.4, # whisper default; drops loopy hallucinations
        },
    )
    result = model.transcribe(audio, language="zh")
    out: list[tuple[float, float, str]] = []
    for seg in result.get("segments", []):
        start = seg.get("start")
        end = seg.get("end")
        text = (seg.get("text") or "").strip()
        if start is not None and end is not None and text:
            out.append((float(start), float(end), text))
    return out


def transcribe(video_path: Path) -> list[FunASRSegment]:
    """Run whisperx ASR on the segment's audio. Returns whisper-segment-level segments.

    The ``FunASRSegment`` name is preserved for downstream compatibility despite
    the engine swap (SenseVoice → whisperx, 2026-05-15).
    """
    with tempfile.TemporaryDirectory() as td:
        wav = _extract_wav(video_path, Path(td))
        raw = _run_asr(wav)
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


from video2yt.transcribe import _count_effective_chars


def _build_cleanup_prompt(segments: list[FunASRSegment], glossary: Glossary) -> str:
    correction_lines = "\n".join(f"  {k} → {v}" for k, v in glossary.corrections.items())
    canonical_lines = "\n".join(f"  - {term}" for term in glossary.canonical)
    numbered = "\n".join(f"{i + 1}. {seg.text}" for i, seg in enumerate(segments))
    return (
        "以下是繁體中文爐石戰記戰棋實況解說的 STT 轉寫，每行一句。\n"
        "只修正錯字、術語、人名；\n"
        "每行修正後的字數必須與原文相差不超過 ±20%；\n"
        "不改寫語意、不增刪句子、不合併或分割行。\n"
        "\n"
        "術語對應表（左 → 右為錯誤 → 正確）：\n"
        f"{correction_lines}\n"
        "\n"
        "首選用詞（若有歧義請偏向以下形式）：\n"
        f"{canonical_lines}\n"
        "\n"
        f"輸入（共 {len(segments)} 行，已編號）：\n"
        f"{numbered}\n"
        "\n"
        f"輸出：請只輸出 {len(segments)} 行修正結果，順序與輸入對應，不要編號、不要說明、不要空行。"
    )


def _invoke_codex(prompt: str, timeout: int = CLEANUP_TIMEOUT_SECONDS) -> str:
    """Run the codex CLI non-interactively. Returns the raw stdout text.

    Uses ``codex exec`` (the non-interactive subcommand). Stdin is unused;
    prompt is passed as the positional argument.
    """
    result = subprocess.run(
        ["codex", "exec", "--skip-git-repo-check", prompt],
        check=True, capture_output=True, text=True, timeout=timeout,
    )
    return result.stdout


def cleanup_with_codex(
    segments: list[FunASRSegment],
    glossary: Glossary,
    timeout: int = CLEANUP_TIMEOUT_SECONDS,
) -> list[FunASRSegment]:
    """Run Codex terminology cleanup. On ANY failure, return ``segments`` unchanged.

    Sanity checks (spec §5.1 B):
    - line count out == line count in
    - per-line: 0.8 ≤ len_eff(clean) / max(len_eff(raw), 1) ≤ 1.2
    """
    if not segments:
        return segments
    prompt = _build_cleanup_prompt(segments, glossary)
    try:
        raw_output = _invoke_codex(prompt, timeout=timeout)
    except subprocess.TimeoutExpired:
        _log.warning("codex cleanup timeout after %ds; using raw ASR", timeout)
        return segments
    except subprocess.CalledProcessError as e:
        _log.warning("codex cleanup failed (exit %d); using raw ASR", e.returncode)
        return segments
    except FileNotFoundError:
        _log.warning("codex CLI not found; using raw ASR")
        return segments

    cleaned_lines = [ln.strip() for ln in raw_output.splitlines() if ln.strip()]
    if len(cleaned_lines) != len(segments):
        _log.warning(
            "codex output line count %d != input %d; using raw ASR",
            len(cleaned_lines), len(segments),
        )
        return segments

    for i, (raw_seg, clean_text) in enumerate(zip(segments, cleaned_lines)):
        raw_eff = max(_count_effective_chars(raw_seg.text), 1)
        clean_eff = _count_effective_chars(clean_text)
        ratio = clean_eff / raw_eff
        if not (0.8 <= ratio <= 1.2):
            _log.warning(
                "codex line %d length ratio %.2f outside [0.8, 1.2]; using raw ASR",
                i + 1, ratio,
            )
            return segments

    return [
        FunASRSegment(raw.start, raw.end, clean)
        for raw, clean in zip(segments, cleaned_lines)
    ]


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


def _is_useful_split(pieces: list[str] | None, parent: str) -> bool:
    """A punctuation split is 'useful' iff it produced >=2 non-empty pieces
    AND each is strictly shorter than the parent text. Termination invariant
    for ``split_segments`` (spec §5.1 C)."""
    if not pieces or len(pieces) < 2:
        return False
    parent_len = len(parent)
    return all(0 < len(p) < parent_len for p in pieces)


def _split_by_punctuation(text: str, punct_class: str) -> list[str]:
    """Split text after each occurrence of any char in ``punct_class``,
    keeping the punctuation glued to the preceding piece. Empty trailing
    pieces are dropped."""
    pieces: list[str] = []
    buf: list[str] = []
    for ch in text:
        buf.append(ch)
        if ch in punct_class:
            pieces.append("".join(buf))
            buf = []
    if buf:
        pieces.append("".join(buf))
    return [p for p in pieces if p]


def _split_at_effective_midpoint(text: str) -> list[str]:
    """Split into exactly two non-empty pieces at the char index closest to len//2.
    Pre: len(text) >= 2. Pass 3 of spec §5.1 C."""
    n = len(text)
    mid = n // 2
    if mid == 0:
        mid = 1
    return [text[:mid], text[mid:]]


def _allocate_time_proportionally(
    start: float, end: float, pieces: list[str]
) -> list[tuple[float, float, str]]:
    """Allocate ``(end - start)`` across ``pieces`` weighted by effective-CJK-char count."""
    duration = end - start
    weights = [max(_count_effective_chars(p), 1) for p in pieces]  # min 1 prevents zero-weight
    total = sum(weights)
    timed: list[tuple[float, float, str]] = []
    cum = 0
    for p, w in zip(pieces, weights):
        new_cum = cum + w
        s = start + (cum / total) * duration
        e = start + (new_cum / total) * duration
        timed.append((s, e, p))
        cum = new_cum
    return timed


def _apply_hard_floor(entries: list[SrtEntry]) -> list[SrtEntry]:
    """Walk left-to-right; for any entry shorter than HARD_FLOOR_SECONDS, extend
    its ``end`` forward. The next entry's ``start`` is pushed forward to match,
    so the cascade never introduces overlap.

    Hard invariants (always satisfied):
    1. ``start <= end`` for every emitted entry (no inverted ranges).
    2. ``entries[i].start >= entries[i-1].end`` (no overlaps).
    3. ``entries[-1].end <= original_overall_end`` (don't overrun the segment).

    Soft goal (yields to hard invariants):
    - Each emitted entry's duration ``>= HARD_FLOOR_SECONDS``.

    Spec §5.1 C: if extending would push past the segment's overall end, the
    cascade stops at the segment boundary and the final entry is emitted with
    whatever duration remains (may still be < floor, possibly zero — rare;
    only happens when the segment itself is too short to fit floor-padded
    pieces, in which case the splitter shouldn't have been invoked anyway).
    """
    if not entries:
        return entries
    overall_end = entries[-1].end
    out: list[SrtEntry] = []
    for e in entries:
        # Hard rule 2: never start before the previous entry's end.
        prev_end = out[-1].end if out else e.start
        start = max(e.start, prev_end)
        # Hard rule 3: never start past the overall end.
        if start > overall_end:
            start = overall_end
        # Hard rule 1: end must never precede start.
        end = max(e.end, start)
        # Soft rule: try to extend to floor, but cap at overall_end.
        floor_end = start + HARD_FLOOR_SECONDS
        if floor_end > end:
            end = min(floor_end, overall_end)
        # Belt-and-suspenders: clamp end into [start, overall_end].
        if end < start:
            end = start
        if end > overall_end:
            end = overall_end
        out.append(SrtEntry(start, end, e.text))
    return out


def _split_one_recursive(
    start: float, end: float, text: str, max_line_chars: int
) -> list[SrtEntry]:
    """Recursive splitter for a single FunASR segment. Spec §5.1 C algorithm."""
    if _count_effective_chars(text) <= max_line_chars:
        return [SrtEntry(start, end, text)]
    # Pass 1
    pieces = _split_by_punctuation(text, SENTENCE_PUNCT)
    if not _is_useful_split(pieces, text):
        # Pass 2
        pieces = _split_by_punctuation(text, CLAUSE_PUNCT)
    if not _is_useful_split(pieces, text):
        # Pass 3 — always useful
        pieces = _split_at_effective_midpoint(text)
    timed = _allocate_time_proportionally(start, end, pieces)
    out: list[SrtEntry] = []
    for s, e, t in timed:
        out.extend(_split_one_recursive(s, e, t, max_line_chars))
    return out


def split_segments(
    segments: list[FunASRSegment], max_line_chars: int
) -> list[SrtEntry]:
    """Style-dependent split of FunASR-segment-granularity segments into final SRT
    entries. Spec §5.1 C — char-oversize is the SOLE trigger; duration alone never
    triggers split. Hard floor applied PER FunASR segment so cascade overflow from
    one segment cannot bleed into the next segment's audio time slot."""
    out: list[SrtEntry] = []
    for seg in segments:
        seg_entries = _split_one_recursive(seg.start, seg.end, seg.text, max_line_chars)
        out.extend(_apply_hard_floor(seg_entries))
    return out


def burn_subtitles(
    input_video: Path,
    entries: list[SrtEntry],
    output_video: Path,
    *,
    font_face: str,
    font_size: int,
    outline_px: int,
    shadow_px: int,
    video_width: int,
    video_height: int,
) -> None:
    """Burn ``entries`` into ``input_video``, write to ``output_video``.

    Reuses ``compose.srt_to_ass`` for ASS templating. ffmpeg is invoked with
    ``cwd=input_video.parent`` and the ASS path referenced by basename to dodge
    the ``subtitles=`` filter's path-escape issues (same trick as ``burn.py``).

    Same-file safeguard: refuse if ``output_video`` and ``input_video`` refer
    to the same on-disk file by ANY mechanism (same path string, case-fold
    alias on case-insensitive filesystems, Unicode normalization alias, or
    hardlink). Two reasons:

    1. If they're the same directory entry (same path, case-fold, unicode),
       unlinking output destroys the input.
    2. Even in the hardlink case (output is a separate directory entry but
       same inode), trying to be clever with ``st_nlink`` to decide whether
       unlink is "safe" relies on a TOCTOU-racy invariant and on filesystems
       (NFS, etc.) accurately reporting nlink. Refusing is unambiguously safe.

    Callers that legitimately want to overwrite a passthrough hardlink should
    explicitly ``output.unlink()`` first; the CLI's ``run()`` does this in the
    post-passthrough-then-burn workflow. ``burn_subtitles`` itself just refuses.

    If the safeguards pass, we still ``output.unlink()`` before invoking
    ffmpeg — this breaks any incidental shared inode (which would be impossible
    given the samefile refusal, but defense in depth) and ensures ffmpeg's
    ``-y`` opens a brand-new inode rather than truncating in place.
    """
    output_video.parent.mkdir(parents=True, exist_ok=True)

    if output_video.resolve() == input_video.resolve():
        raise ValueError(
            f"output_video and input_video resolve to the same path "
            f"({input_video.resolve()}); use a different output path"
        )
    if output_video.exists() and output_video.samefile(input_video):
        raise ValueError(
            f"output_video refers to the same on-disk file as input_video "
            f"({output_video}); the caller must explicitly unlink the output "
            "first (this guard refuses to do it automatically because the "
            "decision depends on workflow knowledge — was the output a "
            "passthrough leftover or did the user mean to overwrite?)"
        )
    if output_video.exists():
        output_video.unlink()

    # Serialize entries as SRT so we can reuse compose.srt_to_ass.
    srt_segs = [FunASRSegment(e.start, e.end, e.text) for e in entries]
    srt_text = segments_to_srt(srt_segs)

    ass_text = srt_to_ass(
        srt_text, video_width, video_height, font_face, font_size,
        position="bottom", outline_px=outline_px, shadow_px=shadow_px,
    )

    ass_path = input_video.parent / f"{input_video.stem}.subbed.ass"
    ass_path.write_text(ass_text, encoding="utf-8")
    ass_basename = ass_path.name

    cmd = [
        "ffmpeg", "-y", "-v", "error",
        "-i", str(input_video.resolve()),
        "-vf", f"subtitles=f='{ass_basename}'",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        "-pix_fmt", "yuv420p",
        "-r", "30",
        str(output_video.resolve()),
    ]
    subprocess.run(
        cmd, check=True, capture_output=True, text=True,
        cwd=str(input_video.parent),
    )


def passthrough(src: Path, dst: Path) -> None:
    """Copy ``src`` to ``dst`` (always copy; not hardlink).

    Originally this used ``os.link`` with an EXDEV-copy fallback to save disk
    space on the common same-filesystem case. But a hardlink at the output
    path turned out to be a foot-gun: a subsequent ``video2yt-subtitle`` run on
    the same input (with a different decision producing the ADD path) would
    invoke ffmpeg with ``-y output.mp4`` and silently truncate the shared inode,
    destroying the input. Defensive guards in ``burn_subtitles`` now refuse
    same-file inputs, but a refusal is a UX regression: the user is forced to
    manually clean up state between runs.

    A full copy costs a few seconds per 600MB segment — negligible against the
    multi-minute ASR + cleanup + burn pipeline that runs immediately after. The
    cost is well worth eliminating the entire hardlink-leftover bug class.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    shutil.copy2(src, dst)

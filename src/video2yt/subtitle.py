"""video2yt-subtitle — detection + ASR + cleanup + split + burn pipeline.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

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

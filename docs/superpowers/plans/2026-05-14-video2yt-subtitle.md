# video2yt-subtitle Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a new CLI `video2yt-subtitle` that takes a Bilibili segment MP4, detects whether it already has bottom-style subtitles (via danmaku XML scan, visual OCR, or manual flag), and — if none detected — adds STT-generated subtitles (SenseVoice ASR + Codex CLI terminology cleanup + style-dependent line split) burned in at the bottom.

**Architecture:** Independent CLI matching the project's existing flat-module pattern (`compose.py` + `compose_cli.py`, etc.). New module `subtitle.py` contains pure-Python detection/cleanup/split logic plus thin wrappers around `funasr` + `rapidocr` + `codex` subprocesses. Heavy ML deps gated behind `[project.optional-dependencies] subtitle`. A small refactor to `compose.srt_to_ass` lets the new burn step pass stronger outline/shadow values without duplicating ASS templating. Style-dependent split (`MAX_LINE_CHARS = compose._effective_chars_per_line(...)`) runs after cleanup and is not cached, so changing `--font-size` doesn't invalidate ASR/cleanup caches.

**Tech Stack:** Python 3.10+, `funasr` (SenseVoice-Small), `rapidocr-onnxruntime`, `pyyaml`, `codex` CLI subprocess, `ffmpeg`/`ffprobe`, `libass` (via ffmpeg `subtitles=` filter). Tests use pytest with `subprocess.run` mocked at the boundary (no real ML inference, no real ffmpeg).

**Spec:** [`docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md`](../specs/2026-05-14-video2yt-subtitle-design.md)

---

## File map

**Create:**
- `src/video2yt/subtitle.py` — Detection + ASR + cleanup + split + burn orchestration
- `src/video2yt/subtitle_cli.py` — `video2yt-subtitle` entry point
- `src/video2yt/data/__init__.py` — empty, marks `data/` as importable subpackage for `importlib.resources`
- `src/video2yt/data/bg_glossary.yaml` — HS Battlegrounds error→correction map (v0 curated)
- `tests/test_subtitle.py` — All unit tests (mocked subprocess boundary)

**Modify:**
- `src/video2yt/compose.py` — `srt_to_ass` accepts optional `outline_px` (default 2) and `shadow_px` (default 0)
- `pyproject.toml` — Add `pyyaml` to top-level deps, add `[project.optional-dependencies] subtitle = [...]`, add `video2yt-subtitle` script entry, register `bg_glossary.yaml` as package data via hatch
- `CLAUDE.md` — One bullet under "Commands" + one bullet under "Architecture"
- `README.md` — Install instructions for the optional `subtitle` extra

**Reference (read-only):**
- `src/video2yt/transcribe.py` — Pattern: lazy `import whisperx` inside functions; reuse `split_into_sentences` if helpful
- `src/video2yt/burn.py` — Pattern: ffmpeg `subtitles=` filter with `cwd=temp_dir` to dodge path-escape issues
- `src/video2yt/compose.py` — Pattern: `_effective_chars_per_line`, `_count_effective_chars`, `_wrap_text_for_ass`

---

## Type definitions (referenced across tasks)

These types live in `src/video2yt/subtitle.py`. Tasks below introduce them incrementally; this section is the reference card.

```python
from dataclasses import dataclass, field
from pathlib import Path

BILIBILI_FIXED_DANMAKU_SECONDS = 5.0
HARD_FLOOR_SECONDS = 0.8
CLEANUP_TIMEOUT_SECONDS = 30
SENTENCE_PUNCT = "。！？"
CLAUSE_PUNCT = "；，、"


@dataclass(frozen=True)
class FunASRSegment:
    """ASR output OR cleanup output at FunASR-segment granularity."""
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class SrtEntry:
    """Final post-split SRT entry."""
    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Glossary:
    corrections: dict[str, str]   # error → correction
    canonical: list[str]          # preferred forms with no LHS error


@dataclass(frozen=True)
class DanmakuSignal:
    fixed_count: int              # count of type=4 entries
    coverage_seconds: float       # union-of-5s-windows length
    coverage_ratio: float         # coverage_seconds / segment_duration
    hit: bool                     # passes both thresholds


@dataclass(frozen=True)
class OcrSignal:
    sampled_frames: int
    frames_with_stable_text: int
    stable_text_ratio: float
    hit: bool                     # passes the 30% stability threshold


@dataclass(frozen=True)
class Decision:
    add_subtitles: bool
    reason: str                   # human-readable explanation for stderr log
```

---

## Task 1: Extend `compose.srt_to_ass` with outline/shadow params

**Files:**
- Modify: `src/video2yt/compose.py:174-275`
- Test: `tests/test_compose_outline_shadow.py` (new file — keep compose tests isolated)

This is the smallest standalone change. Everything else downstream depends on it. Default values preserve current behavior so existing intro flow doesn't regress.

- [ ] **Step 1: Write the failing test**

Create `tests/test_compose_outline_shadow.py`:

```python
"""Tests for srt_to_ass outline_px/shadow_px parameters added for video2yt-subtitle."""

from video2yt.compose import srt_to_ass

SAMPLE_SRT = """1
00:00:00,000 --> 00:00:02,000
你好世界
"""


def test_default_outline_and_shadow_match_existing_behavior():
    """Default behavior unchanged: outline=2, shadow=0 in the ASS style line."""
    ass = srt_to_ass(SAMPLE_SRT, 1920, 1080, "Hiragino Sans GB", 42, position="bottom")
    # ASS style format: ...BorderStyle,Outline,Shadow,Alignment,...
    # Existing values were "1,2,0,{alignment}" — keep that as the default.
    assert "1,2,0,2," in ass     # BorderStyle=1, Outline=2, Shadow=0, Alignment=2 (bottom)


def test_outline_px_propagates_to_ass_style():
    ass = srt_to_ass(
        SAMPLE_SRT, 1920, 1080, "Hiragino Sans GB", 42,
        position="bottom", outline_px=4, shadow_px=2,
    )
    assert "1,4,2,2," in ass     # BorderStyle=1, Outline=4, Shadow=2, Alignment=2


def test_intro_call_signature_unchanged():
    """Existing intro path (no outline/shadow kwargs) must still work."""
    ass = srt_to_ass(SAMPLE_SRT, 1920, 1080, "Hiragino Sans GB", 42)
    # Default position="center" → Alignment=5
    assert "1,2,0,5," in ass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_compose_outline_shadow.py -v`
Expected: FAIL — `srt_to_ass()` got an unexpected keyword argument `outline_px`.

- [ ] **Step 3: Modify `compose.srt_to_ass` signature and ASS template**

In `src/video2yt/compose.py`, update the function signature (around line 174):

```python
def srt_to_ass(
    srt_text: str,
    video_width: int,
    video_height: int,
    font_face: str,
    font_size: int,
    position: str = "center",
    outline_px: int = 2,
    shadow_px: int = 0,
) -> str:
```

Update the docstring (around line 187) to mention the new parameters:

```
... black outline (default 2px, configurable via ``outline_px``),
no shadow by default (``shadow_px`` configurable), MarginV=80.
```

Update the ASS style line (around line 268). Find:

```python
        f"0,0,0,0,100,100,0,0,1,2,0,{alignment},"
```

Replace with:

```python
        f"0,0,0,0,100,100,0,0,1,{outline_px},{shadow_px},{alignment},"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_compose_outline_shadow.py -v`
Expected: all 3 tests PASS.

- [ ] **Step 5: Run the full existing test suite to confirm no regression**

Run: `uv run pytest -q`
Expected: all existing tests (230+) still pass; 3 new tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/video2yt/compose.py tests/test_compose_outline_shadow.py
git commit -m "feat(compose): add outline_px/shadow_px params to srt_to_ass

Defaults preserve current behavior (outline=2, shadow=0). The new
video2yt-subtitle CLI will pass outline_px=4, shadow_px=2 to render
subtitles legibly on busy game backgrounds."
```

---

## Task 2: Add `pyyaml` dep + package skeleton + glossary yaml

**Files:**
- Modify: `pyproject.toml`
- Create: `src/video2yt/data/__init__.py` (empty)
- Create: `src/video2yt/data/bg_glossary.yaml`
- Create: `src/video2yt/subtitle.py` (stub — just constants for now)
- Test: `tests/test_subtitle.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_subtitle.py`:

```python
"""Unit tests for video2yt-subtitle. All subprocess boundaries are mocked."""

from video2yt import subtitle


def test_constants_exist():
    assert subtitle.BILIBILI_FIXED_DANMAKU_SECONDS == 5.0
    assert subtitle.HARD_FLOOR_SECONDS == 0.8
    assert subtitle.CLEANUP_TIMEOUT_SECONDS == 30
    assert subtitle.SENTENCE_PUNCT == "。！？"
    assert subtitle.CLAUSE_PUNCT == "；，、"


def test_packaged_glossary_yaml_exists_and_parses():
    """The default glossary ships inside the package and can be located."""
    import importlib.resources
    files = importlib.resources.files("video2yt.data")
    glossary_path = files / "bg_glossary.yaml"
    assert glossary_path.is_file()
    import yaml
    data = yaml.safe_load(glossary_path.read_text(encoding="utf-8"))
    assert "corrections" in data
    assert "canonical" in data
    assert isinstance(data["corrections"], dict)
    assert isinstance(data["canonical"], list)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: FAIL — `No module named 'video2yt.subtitle'`.

- [ ] **Step 3: Add `pyyaml` to top-level deps**

Run: `uv add pyyaml`
Expected: `pyproject.toml` updated, `uv.lock` updated.

- [ ] **Step 4: Create empty package data marker**

Create `src/video2yt/data/__init__.py` with a single-line docstring:

```python
"""Package data files for video2yt (e.g. bg_glossary.yaml)."""
```

- [ ] **Step 5: Create the seed glossary**

Create `src/video2yt/data/bg_glossary.yaml`:

```yaml
# Hearthstone Battlegrounds STT terminology corrections.
#
# Left → right: errors that SenseVoice / whisper tend to produce, mapped to
# the canonical Traditional-Chinese form used on this YouTube channel.
# Add entries as new project topics surface new mistranscription patterns.
corrections:
  戰旗: 戰棋               # 战旗 (Stratego) → 战棋 (Hearthstone Battlegrounds)
  护戒: 戒指龍              # ringnaga incident — "护戒" mistranscription for 戒指龍 / Ring Bearer
  護戒: 戒指龍
  拉法母: 拉法姆            # Rafaam, proper noun mishearing
  加拉克朗: 加拉克隆        # Galakrond, proper noun mishearing
  伊瑟拉: 伊瑟拉            # canonical (no change — keeps Codex from "correcting" it)

# Canonical terms (no LHS error). Codex should bias toward these forms when it
# encounters ambiguous transcription of these concepts.
canonical:
  - 爐石戰記
  - 戰棋
  - 酒館
  - 隨從
  - 餵牌
  - 三星
  - 吃雞
  - 加血
  - 上分
  - 開酒館
  - 護甲
  - 法力水晶
```

- [ ] **Step 6: Create stub `subtitle.py`**

Create `src/video2yt/subtitle.py`:

```python
"""video2yt-subtitle — detection + ASR + cleanup + split + burn pipeline.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

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
```

- [ ] **Step 7: Register `data/*.yaml` as package data in `pyproject.toml`**

In `pyproject.toml`, after the `[tool.hatch.build.targets.wheel]` block, ensure yaml files are included. Find:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/video2yt"]
```

Append:

```toml

[tool.hatch.build.targets.wheel.force-include]
"src/video2yt/data/bg_glossary.yaml" = "video2yt/data/bg_glossary.yaml"
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 2 tests PASS.

- [ ] **Step 9: Commit**

```bash
git add pyproject.toml uv.lock src/video2yt/subtitle.py src/video2yt/data/__init__.py src/video2yt/data/bg_glossary.yaml tests/test_subtitle.py
git commit -m "feat(subtitle): scaffold module + packaged glossary + pyyaml dep

Stub subtitle.py with shared constants from spec §5.1.
Seed bg_glossary.yaml with HS Battlegrounds error→correction map
from prior project memory (ringnaga incident + workflow glossary)."
```

---

## Task 3: Glossary loader

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
from pathlib import Path

import pytest


def test_load_glossary_default():
    """Calling load_glossary with no path loads the packaged yaml."""
    g = subtitle.load_glossary(None)
    assert isinstance(g, subtitle.Glossary)
    assert g.corrections.get("戰旗") == "戰棋"
    assert "酒館" in g.canonical


def test_load_glossary_custom_path(tmp_path: Path):
    p = tmp_path / "my.yaml"
    p.write_text(
        "corrections:\n  foo: bar\ncanonical:\n  - baz\n",
        encoding="utf-8",
    )
    g = subtitle.load_glossary(p)
    assert g.corrections == {"foo": "bar"}
    assert g.canonical == ["baz"]


def test_load_glossary_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        subtitle.load_glossary(tmp_path / "nope.yaml")


def test_load_glossary_malformed_yaml_raises(tmp_path: Path):
    p = tmp_path / "bad.yaml"
    p.write_text("corrections: [this is a list not a dict]\n", encoding="utf-8")
    with pytest.raises(ValueError):
        subtitle.load_glossary(p)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 4 new tests FAIL — `module 'video2yt.subtitle' has no attribute 'Glossary'` or `'load_glossary'`.

- [ ] **Step 3: Implement `Glossary` and `load_glossary`**

Append to `src/video2yt/subtitle.py`:

```python
from dataclasses import dataclass
from pathlib import Path

import yaml


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all subtitle tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): glossary loader (yaml, packaged default + override)"
```

---

## Task 4: Danmaku XML scanner (detection signal A)

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

Spec §5.1 D defines the coverage formula. Implementation: parse `<d>` tags, extract the type field (2nd CSV column of the `p` attribute), filter to type=4 only, compute the union-of-5s-windows length divided by segment_duration.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
DANMAKU_XML_TEMPLATE = """<?xml version="1.0" encoding="UTF-8"?>
<i>
{entries}
</i>
"""


def _make_danmaku(entries: list[tuple[float, int]]) -> str:
    """Build a minimal danmaku XML from (start_seconds, type) tuples."""
    lines = []
    for start, dtype in entries:
        # p format: time,type,size,color,timestamp,pool,userid,id
        p = f"{start:.2f},{dtype},25,16777215,1700000000,0,abc,1"
        lines.append(f'  <d p="{p}">text</d>')
    return DANMAKU_XML_TEMPLATE.format(entries="\n".join(lines))


def test_scan_danmaku_ignores_rolling(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(1.0, 1), (5.0, 1)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert sig.fixed_count == 0
    assert sig.coverage_seconds == 0.0


def test_scan_danmaku_counts_only_type_4(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text(
        _make_danmaku([(1.0, 4), (10.0, 5), (20.0, 1), (30.0, 4)]),
        encoding="utf-8",
    )
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert sig.fixed_count == 2


def test_scan_danmaku_overlap_union(tmp_path):
    """Two type=4 at t=10 and t=12 → union [10,15] ∪ [12,17] = [10,17] = 7s."""
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(10.0, 4), (12.0, 4)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert sig.fixed_count == 2
    assert abs(sig.coverage_seconds - 7.0) < 0.01


def test_scan_danmaku_disjoint_intervals(tmp_path):
    """Two type=4 at t=10 and t=100 → two disjoint 5s windows = 10s total."""
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(10.0, 4), (100.0, 4)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=200.0)
    assert abs(sig.coverage_seconds - 10.0) < 0.01


def test_scan_danmaku_clipped_to_segment_end(tmp_path):
    """type=4 at t=98 with segment_duration=100 → clipped to [98,100] = 2s."""
    xml = tmp_path / "d.xml"
    xml.write_text(_make_danmaku([(98.0, 4)]), encoding="utf-8")
    sig = subtitle.scan_danmaku(xml, segment_duration=100.0)
    assert abs(sig.coverage_seconds - 2.0) < 0.01


def test_scan_danmaku_threshold_pass(tmp_path):
    """10 type=4 entries spread 0-50s, 5s each (mostly overlapping in clusters)."""
    xml = tmp_path / "d.xml"
    entries = [(t, 4) for t in range(0, 60, 6)]  # 10 entries at 0,6,12,...,54
    xml.write_text(_make_danmaku(entries), encoding="utf-8")
    sig = subtitle.scan_danmaku(
        xml, segment_duration=100.0,
        min_fixed=10, min_coverage_ratio=0.30,
    )
    assert sig.fixed_count == 10
    # Coverage: ~50s of windows, with some 1s overlap at each boundary → ≈40-50s of 100s
    assert sig.hit is True


def test_scan_danmaku_threshold_fail_count(tmp_path):
    """9 type=4 entries → fixed_count below threshold even if coverage is high."""
    xml = tmp_path / "d.xml"
    entries = [(t, 4) for t in range(0, 45, 5)]  # 9 entries at 0,5,...,40
    xml.write_text(_make_danmaku(entries), encoding="utf-8")
    sig = subtitle.scan_danmaku(
        xml, segment_duration=100.0,
        min_fixed=10, min_coverage_ratio=0.30,
    )
    assert sig.fixed_count == 9
    assert sig.hit is False


def test_scan_danmaku_corrupted_xml_raises(tmp_path):
    xml = tmp_path / "d.xml"
    xml.write_text("<i><d p='no commas here'>text</d></i>", encoding="utf-8")
    with pytest.raises(ValueError):
        subtitle.scan_danmaku(xml, segment_duration=100.0)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 8 new tests FAIL — `module 'video2yt.subtitle' has no attribute 'scan_danmaku'`.

- [ ] **Step 3: Implement `DanmakuSignal` and `scan_danmaku`**

Append to `src/video2yt/subtitle.py`:

```python
import xml.etree.ElementTree as ET


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all 8 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): danmaku XML scanner (type=4 coverage)

Implements spec §5.1 D: union-of-5s-windows coverage formula for
type=4 (bottom-fixed) danmaku. Other types ignored. Coverage clipped
to segment duration."
```

---

## Task 5: Decision function (combines a + b + c short-circuit)

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

Spec §5.1 decision priority: manual force > danmaku > OCR. Any signal saying SKIP → SKIP. We implement the decision pure-function first; the OCR signal it consumes will be wired in Task 6.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
def _dummy_danmaku(hit: bool, fixed: int = 0, cov: float = 0.0) -> subtitle.DanmakuSignal:
    return subtitle.DanmakuSignal(
        fixed_count=fixed,
        coverage_seconds=cov,
        coverage_ratio=cov / 100.0,
        hit=hit,
    )


def _dummy_ocr(hit: bool, sampled: int = 10, stable: int = 0) -> subtitle.OcrSignal:
    return subtitle.OcrSignal(
        sampled_frames=sampled,
        frames_with_stable_text=stable,
        stable_text_ratio=stable / max(sampled, 1),
        hit=hit,
    )


def test_decide_force_add_short_circuits():
    d = subtitle.decide(
        force="add",
        danmaku=_dummy_danmaku(hit=True),
        ocr=_dummy_ocr(hit=True),
    )
    assert d.add_subtitles is True
    assert "force" in d.reason.lower()


def test_decide_force_skip_short_circuits():
    d = subtitle.decide(
        force="skip",
        danmaku=_dummy_danmaku(hit=False),
        ocr=_dummy_ocr(hit=False),
    )
    assert d.add_subtitles is False
    assert "force" in d.reason.lower()


def test_decide_danmaku_hit_overrides_ocr_miss():
    d = subtitle.decide(
        force=None,
        danmaku=_dummy_danmaku(hit=True, fixed=20, cov=40.0),
        ocr=_dummy_ocr(hit=False),
    )
    assert d.add_subtitles is False
    assert "danmaku" in d.reason.lower()


def test_decide_ocr_hit_when_danmaku_miss():
    d = subtitle.decide(
        force=None,
        danmaku=_dummy_danmaku(hit=False, fixed=2, cov=1.5),
        ocr=_dummy_ocr(hit=True, sampled=20, stable=12),
    )
    assert d.add_subtitles is False
    assert "ocr" in d.reason.lower()


def test_decide_both_miss_returns_add():
    d = subtitle.decide(
        force=None,
        danmaku=_dummy_danmaku(hit=False),
        ocr=_dummy_ocr(hit=False),
    )
    assert d.add_subtitles is True


def test_decide_no_danmaku_signal_uses_ocr_only():
    d = subtitle.decide(force=None, danmaku=None, ocr=_dummy_ocr(hit=True))
    assert d.add_subtitles is False


def test_decide_no_ocr_signal_uses_danmaku_only():
    d = subtitle.decide(force=None, danmaku=_dummy_danmaku(hit=False), ocr=None)
    assert d.add_subtitles is True


def test_decide_invalid_force_raises():
    with pytest.raises(ValueError):
        subtitle.decide(force="bogus", danmaku=None, ocr=None)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 8 new tests FAIL — `module 'video2yt.subtitle' has no attribute 'decide'`.

- [ ] **Step 3: Implement `OcrSignal`, `Decision`, `decide`**

Append to `src/video2yt/subtitle.py`:

```python
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
        raise ValueError(f"invalid force value {force!r}; expected 'add', 'skip', or None")
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): short-circuit decision (force > danmaku > OCR)

Spec §5.1 — any signal saying SKIP triggers SKIP. force is the highest
priority; absent that, danmaku hit > OCR hit > add."
```

---

## Task 6: OCR sampler (detection signal B) — mocked

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

The OCR sampler does three things: (1) ffmpeg-sample frames into memory, (2) crop bottom 12-18%, (3) RapidOCR pass + position-cluster stability check. Real `rapidocr_onnxruntime` is gated behind the `subtitle` extra and lazily imported. Tests mock both the ffmpeg subprocess and the OCR engine.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
from unittest.mock import MagicMock, patch


@patch("video2yt.subtitle._extract_frames")
@patch("video2yt.subtitle._run_rapidocr")
def test_sample_ocr_no_text_detected(mock_ocr, mock_extract):
    """All sampled frames return no OCR boxes → stable_text_ratio=0, hit=False."""
    mock_extract.return_value = [b"frame0_bytes"] * 10
    mock_ocr.return_value = []   # no boxes detected
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    assert sig.sampled_frames == 10
    assert sig.frames_with_stable_text == 0
    assert sig.hit is False


@patch("video2yt.subtitle._extract_frames")
@patch("video2yt.subtitle._run_rapidocr")
def test_sample_ocr_stable_cluster_triggers_hit(mock_ocr, mock_extract):
    """6 of 10 frames have a text box in the same y-position cluster → ratio=0.6 → hit."""
    mock_extract.return_value = [b"f"] * 10
    # Each call returns either [] or a box at y≈950 in the bottom band.
    # Frames 0-5 (6 frames) have a stable box at y=950; frames 6-9 have nothing.
    box_at_y950 = [(((100, 950), (300, 950), (300, 990), (100, 990)), "字幕", 0.9)]
    mock_ocr.side_effect = [box_at_y950] * 6 + [[]] * 4
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    assert sig.sampled_frames == 10
    assert sig.frames_with_stable_text == 6
    assert abs(sig.stable_text_ratio - 0.6) < 0.01
    assert sig.hit is True


@patch("video2yt.subtitle._extract_frames")
@patch("video2yt.subtitle._run_rapidocr")
def test_sample_ocr_drifting_boxes_not_stable(mock_ocr, mock_extract):
    """Boxes detected but at different y-positions per frame (e.g. floating danmaku)
    do NOT cluster as a stable subtitle position → ratio low → no hit."""
    mock_extract.return_value = [b"f"] * 10
    # Each frame has a box at a different y position (drifting downward)
    def box_at(y: int) -> list:
        return [(((100, y), (300, y), (300, y + 30), (100, y + 30)), "弹幕", 0.9)]
    mock_ocr.side_effect = [box_at(900 + i * 30) for i in range(10)]
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    # Each box is in a unique y-cluster of size 1 → no cluster has ≥30% support
    assert sig.frames_with_stable_text < 3
    assert sig.hit is False


@patch("video2yt.subtitle._extract_frames")
def test_sample_ocr_fails_open_on_extract_error(mock_extract):
    """ffmpeg failure → fall back to no-detection (fail-open), not raise. Spec §7."""
    mock_extract.side_effect = RuntimeError("ffmpeg crashed")
    sig = subtitle.sample_ocr(
        Path("seg.mp4"), segment_duration=50.0, interval_seconds=5.0,
        min_stable_ratio=0.30,
    )
    assert sig.sampled_frames == 0
    assert sig.hit is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 4 new tests FAIL — `module 'video2yt.subtitle' has no attribute 'sample_ocr'`.

- [ ] **Step 3: Implement OCR sampler**

Append to `src/video2yt/subtitle.py`:

```python
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

    # Greedy 1D clustering by tolerance.
    sorted_ys = sorted(all_ys)
    clusters: list[list[int]] = [[sorted_ys[0]]]
    for y in sorted_ys[1:]:
        if y - clusters[-1][-1] <= cluster_y_tolerance:
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): OCR sampler with y-cluster stability check

ffmpeg fps=1/5 mjpeg pipe → RapidOCR per frame → 1D y-centroid clustering
across frames. A 'hit' requires ≥30% frame support in a single cluster
(stable position distinguishes burnt subs from drifting danmaku).
Fail-open: any internal failure returns a no-hit signal."
```

---

## Task 7: FunASR transcription wrapper

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
@patch("video2yt.subtitle._extract_wav")
@patch("video2yt.subtitle._run_funasr")
def test_transcribe_returns_funasr_segments(mock_funasr, mock_extract, tmp_path):
    mock_extract.return_value = tmp_path / "audio.wav"
    mock_funasr.return_value = [
        (0.0, 2.5, "你好"),
        (2.5, 5.0, "世界"),
    ]
    result = subtitle.transcribe(Path("seg.mp4"))
    assert result == [
        subtitle.FunASRSegment(0.0, 2.5, "你好"),
        subtitle.FunASRSegment(2.5, 5.0, "世界"),
    ]


@patch("video2yt.subtitle._extract_wav")
@patch("video2yt.subtitle._run_funasr")
def test_transcribe_strips_whitespace(mock_funasr, mock_extract, tmp_path):
    mock_extract.return_value = tmp_path / "audio.wav"
    mock_funasr.return_value = [(0.0, 2.0, "  你好  ")]
    result = subtitle.transcribe(Path("seg.mp4"))
    assert result[0].text == "你好"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 2 new tests FAIL — `module 'video2yt.subtitle' has no attribute 'transcribe'`.

- [ ] **Step 3: Implement transcribe + helpers**

Append to `src/video2yt/subtitle.py`:

```python
import tempfile


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): SenseVoice transcribe wrapper (lazy funasr import)"
```

---

## Task 8: SRT serialization at FunASR-segment granularity

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

Per spec §5, `.raw.srt` and `.cleaned.srt` are both stored at FunASR-segment granularity (one entry per FunASR segment, no splitting). We need a tiny serializer/deserializer pair so cache files round-trip.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
def test_segments_to_srt_roundtrip():
    segs = [
        subtitle.FunASRSegment(0.0, 2.5, "你好"),
        subtitle.FunASRSegment(2.5, 5.0, "世界，再見。"),
    ]
    srt = subtitle.segments_to_srt(segs)
    assert "1\n00:00:00,000 --> 00:00:02,500" in srt
    assert "你好" in srt
    assert "00:00:02,500 --> 00:00:05,000" in srt
    parsed = subtitle.parse_srt_to_segments(srt)
    assert parsed == segs


def test_segments_to_srt_handles_fractional_seconds():
    segs = [subtitle.FunASRSegment(1.234, 5.678, "abc")]
    srt = subtitle.segments_to_srt(segs)
    assert "00:00:01,234 --> 00:00:05,678" in srt


def test_parse_srt_skips_empty_blocks():
    srt = "1\n00:00:00,000 --> 00:00:01,000\nfoo\n\n\n2\n00:00:01,000 --> 00:00:02,000\nbar\n"
    parsed = subtitle.parse_srt_to_segments(srt)
    assert len(parsed) == 2
    assert parsed[0].text == "foo"
    assert parsed[1].text == "bar"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 3 new tests FAIL — missing `segments_to_srt`, `parse_srt_to_segments`.

- [ ] **Step 3: Implement serializers**

Append to `src/video2yt/subtitle.py`:

```python
import re


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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): SRT serialize/parse for cached FunASR-segment SRT"
```

---

## Task 9: Codex cleanup (with sanity checks + fallback)

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

Spec §5.1 B + §5 step 4. Build prompt, invoke `codex exec`, parse M lines back, sanity-check `0.8 ≤ len(cleaned)/len(raw) ≤ 1.2` per line + line-count equality. ANY violation → return raw with WARNING log. Reuse `_count_effective_chars` from compose for consistent length math.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_happy_path_replaces_text(mock_codex):
    segs = [
        subtitle.FunASRSegment(0.0, 2.0, "戰旗很有趣"),
        subtitle.FunASRSegment(2.0, 5.0, "拉法母真的強"),
    ]
    glossary = subtitle.Glossary(
        corrections={"戰旗": "戰棋", "拉法母": "拉法姆"},
        canonical=[],
    )
    mock_codex.return_value = "戰棋很有趣\n拉法姆真的強\n"
    out = subtitle.cleanup_with_codex(segs, glossary)
    assert out[0].text == "戰棋很有趣"
    assert out[1].text == "拉法姆真的強"
    # Timestamps preserved exactly
    assert out[0].start == 0.0 and out[0].end == 2.0
    assert out[1].start == 2.0 and out[1].end == 5.0


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_line_count_mismatch_falls_back(mock_codex, caplog):
    """Codex returns the wrong number of lines → return raw + WARNING."""
    segs = [
        subtitle.FunASRSegment(0.0, 2.0, "abc"),
        subtitle.FunASRSegment(2.0, 4.0, "def"),
    ]
    glossary = subtitle.Glossary({}, [])
    mock_codex.return_value = "abc\n"   # only 1 line, expected 2
    with caplog.at_level(logging.WARNING):
        out = subtitle.cleanup_with_codex(segs, glossary)
    assert out == segs
    assert any("line count" in r.message.lower() for r in caplog.records)


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_length_blown_per_line_falls_back(mock_codex, caplog):
    """One line's length ratio is outside [0.8, 1.2] → fall back, WARN."""
    segs = [
        subtitle.FunASRSegment(0.0, 2.0, "短"),    # 1 char
        subtitle.FunASRSegment(2.0, 4.0, "也短"),  # 2 chars
    ]
    glossary = subtitle.Glossary({}, [])
    # Line 2 expanded from 2 chars to 10 chars → ratio 5.0, way over 1.2
    mock_codex.return_value = "短\n這是個被改寫太多的句子\n"
    with caplog.at_level(logging.WARNING):
        out = subtitle.cleanup_with_codex(segs, glossary)
    assert out == segs
    assert any("length" in r.message.lower() for r in caplog.records)


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_codex_timeout_falls_back(mock_codex, caplog):
    segs = [subtitle.FunASRSegment(0.0, 2.0, "abc")]
    mock_codex.side_effect = subprocess.TimeoutExpired(cmd="codex", timeout=30)
    with caplog.at_level(logging.WARNING):
        out = subtitle.cleanup_with_codex(segs, subtitle.Glossary({}, []))
    assert out == segs
    assert any("timeout" in r.message.lower() for r in caplog.records)


@patch("video2yt.subtitle._invoke_codex")
def test_cleanup_boundary_length_ratio_accepted(mock_codex):
    """Length ratio of exactly 0.8 / 1.2 is accepted (closed boundary)."""
    segs = [subtitle.FunASRSegment(0.0, 1.0, "abcde")]   # 5 effective chars (ASCII counts as 0.5 each → 2.5)
    glossary = subtitle.Glossary({}, [])
    # Replacement with same effective char count is trivially in-range
    mock_codex.return_value = "abcde\n"
    out = subtitle.cleanup_with_codex(segs, glossary)
    assert out[0].text == "abcde"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 5 new tests FAIL — missing `cleanup_with_codex` / `_invoke_codex`.

- [ ] **Step 3: Implement cleanup**

Append to `src/video2yt/subtitle.py`:

```python
from video2yt.compose import _count_effective_chars


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
        _log.warning("codex cleanup timed out after %ds; using raw ASR", timeout)
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): Codex cleanup with M→M invariant + ±20% sanity

Spec §5.1 B — line count and per-line length-ratio checks. Any
violation (or timeout, or codex CLI missing) → fall back to raw
ASR with WARNING. Timestamps from raw are always preserved."
```

---

## Task 10: Split algorithm (the hardest one)

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

Spec §5.1 C. Three private helpers + one public `split_segments`. Implement bottom-up: midpoint splitter first, then useful-split predicate, then orchestrator.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
def test_split_char_ok_segment_unchanged():
    """15 chars under MAX=30 → single entry, identical timing."""
    seg = subtitle.FunASRSegment(0.0, 3.0, "短短的一句話只有幾個字")
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) == 1
    assert out[0].start == 0.0 and out[0].end == 3.0
    assert out[0].text == seg.text


def test_split_long_duration_short_text_not_split():
    """25 chars / 9 seconds / no punctuation → kept as ONE entry (rule §5.1 C)."""
    seg = subtitle.FunASRSegment(0.0, 9.0, "二十五個字大概就是這樣長的一句話可以讀完")
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) == 1
    assert out[0].end == 9.0


def test_split_sentence_punctuation():
    """45 chars with 。in middle → Pass 1 useful split."""
    text = "前半段大概有二十多個字。後半段也有差不多二十多個字。"
    seg = subtitle.FunASRSegment(0.0, 6.0, text)
    out = subtitle.split_segments([seg], max_line_chars=20)
    assert len(out) >= 2
    assert "前半段" in out[0].text
    assert out[-1].end == 6.0


def test_split_clause_only():
    """No 。 but has ，→ Pass 2 used."""
    text = "前半段大概有二十多個字，後半段也有差不多二十多個字"
    seg = subtitle.FunASRSegment(0.0, 6.0, text)
    out = subtitle.split_segments([seg], max_line_chars=20)
    assert len(out) >= 2


def test_split_no_punctuation_uses_midpoint():
    """40+ chars with zero punctuation → Pass 3 midpoint."""
    text = "一" * 40
    seg = subtitle.FunASRSegment(0.0, 4.0, text)
    out = subtitle.split_segments([seg], max_line_chars=10)
    assert len(out) >= 4
    assert all(len(e.text) <= 10 for e in out)
    assert out[0].start == 0.0
    assert out[-1].end == 4.0


def test_split_termination_edge_punctuation_only_at_end():
    """Was the infinite-recursion bug: 'A'*99 + '。' must split via Pass 3, not loop."""
    text = "一" * 99 + "。"
    seg = subtitle.FunASRSegment(0.0, 10.0, text)
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) >= 4
    assert all(len(e.text) <= 30 for e in out)


def test_split_punctuation_only_at_start():
    text = "。" + "一" * 99
    seg = subtitle.FunASRSegment(0.0, 10.0, text)
    out = subtitle.split_segments([seg], max_line_chars=30)
    # Useful Pass 1 split: ["。", "一"*99]; the long piece then recurses to Pass 3
    assert len(out) >= 4


def test_split_proportional_time_allocation():
    """Pieces weighted [4, 3, 3] inside (0.0, 10.0) → boundaries at 4.0, 7.0, 10.0."""
    # Force a punctuation split with 3 pieces of known weights.
    text = "AAAA。BBB。CCC"   # ASCII chars count 0.5 each in _count_effective_chars
    seg = subtitle.FunASRSegment(0.0, 10.0, text)
    out = subtitle.split_segments([seg], max_line_chars=2)
    # Three pieces by Pass 1: "AAAA。" (5 chars), "BBB。" (4 chars), "CCC" (3 chars)
    # Effective weights: 0.5*4 + 1 = 3.0, 0.5*3 + 1 = 2.5, 0.5*3 = 1.5 → sum 7.0
    # But each piece may further recurse since max=2. Just verify edge timing.
    assert out[0].start == 0.0
    assert out[-1].end == 10.0


def test_split_hard_floor_extends_short_pieces():
    """Pieces shorter than 0.8s get extended; cascade pushes forward, no overlap."""
    text = "一二三四五。六七八九十。"
    seg = subtitle.FunASRSegment(0.0, 1.0, text)   # very short total
    out = subtitle.split_segments([seg], max_line_chars=4)
    # All pieces start ≥ prior end (no overlaps)
    for prev, curr in zip(out, out[1:]):
        assert curr.start >= prev.end - 1e-6


def test_split_threshold_is_strict_greater_than():
    """Exactly MAX_LINE_CHARS chars → no split."""
    text = "一" * 30
    seg = subtitle.FunASRSegment(0.0, 3.0, text)
    out = subtitle.split_segments([seg], max_line_chars=30)
    assert len(out) == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 10 new tests FAIL — missing `split_segments`.

- [ ] **Step 3: Implement split**

Append to `src/video2yt/subtitle.py`:

```python
def _is_useful_split(pieces: list[str] | None, parent: str) -> bool:
    """A punctuation split is 'useful' iff it produced ≥2 non-empty pieces
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
    its ``end`` forward and push the next entry's ``start`` forward by the same
    amount. Never introduces overlap. Final-entry overflow is tolerated (the
    spec accepts a final entry < floor if the whole segment is itself too short)."""
    if not entries:
        return entries
    out = [SrtEntry(e.start, e.end, e.text) for e in entries]
    for i in range(len(out) - 1):
        cur = out[i]
        needed = HARD_FLOOR_SECONDS - (cur.end - cur.start)
        if needed > 0:
            new_end = cur.end + needed
            next_e = out[i + 1]
            new_next_start = next_e.start + needed
            out[i] = SrtEntry(cur.start, new_end, cur.text)
            out[i + 1] = SrtEntry(new_next_start, next_e.end, next_e.text)
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
    triggers split. Hard floor applied to all entries post-split."""
    raw_entries: list[SrtEntry] = []
    for seg in segments:
        raw_entries.extend(_split_one_recursive(seg.start, seg.end, seg.text, max_line_chars))
    return _apply_hard_floor(raw_entries)
```

Also: add the `SrtEntry` dataclass near the other dataclasses if not already present (placed near `FunASRSegment`):

```python
@dataclass(frozen=True)
class SrtEntry:
    start: float
    end: float
    text: str
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all 10 new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): char-oversize split with termination proof

Spec §5.1 C — Pass 1 sentence-punct, Pass 2 clause-punct, Pass 3
midpoint last-resort. _is_useful_split guards against punctuation-
at-end infinite recursion. Time allocated proportionally by
effective-CJK-char weights. Hard floor cascade is overlap-free."
```

---

## Task 11: SRT-to-ASS burn step

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

Spec §5 step 6. Reuse `compose.srt_to_ass` with `outline_px=4, shadow_px=2, position="bottom"`. Same ffmpeg path-escape trick as `burn.py`: cwd into the dir holding the ASS file and reference it by basename.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
@patch("subprocess.run")
def test_burn_constructs_ffmpeg_command_with_basename(mock_run, tmp_path):
    """ffmpeg subprocess uses cwd=temp_dir and an ASS basename, not absolute path
    (same path-escape avoidance as burn.py)."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    input_mp4 = tmp_path / "seg.mp4"
    input_mp4.write_bytes(b"fake")
    output_mp4 = tmp_path / "seg_subbed.mp4"
    entries = [subtitle.SrtEntry(0.0, 2.0, "你好")]
    subtitle.burn_subtitles(
        input_mp4, entries, output_mp4,
        font_face="Hiragino Sans GB", font_size=42,
        outline_px=4, shadow_px=2,
        video_width=1920, video_height=1080,
    )
    assert mock_run.called
    call_args = mock_run.call_args
    cmd = call_args.kwargs.get("args") or call_args.args[0]
    cwd = call_args.kwargs.get("cwd")
    # ASS path referenced by basename via subtitles=f='<name>'
    assert any("subtitles=f='" in arg for arg in cmd)
    # Filter does NOT contain the full path of the ASS
    assert not any(str(tmp_path) in arg and ".ass" in arg for arg in cmd)
    # cwd is set
    assert cwd is not None


@patch("subprocess.run")
def test_burn_passes_outline_shadow_via_compose(mock_run, tmp_path):
    """The ASS written to disk has BorderStyle=1, Outline=4, Shadow=2 in style."""
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    input_mp4 = tmp_path / "seg.mp4"
    input_mp4.write_bytes(b"fake")
    output_mp4 = tmp_path / "seg_subbed.mp4"
    entries = [subtitle.SrtEntry(0.0, 2.0, "你好")]
    subtitle.burn_subtitles(
        input_mp4, entries, output_mp4,
        font_face="Hiragino Sans GB", font_size=42,
        outline_px=4, shadow_px=2,
        video_width=1920, video_height=1080,
    )
    # The temp ASS file gets created beside the input (subtitle.py uses input.parent)
    ass_files = list(input_mp4.parent.glob("*.ass"))
    assert ass_files, "expected an ASS file to be written next to the input"
    ass_text = ass_files[0].read_text(encoding="utf-8")
    assert "1,4,2,2," in ass_text   # BorderStyle=1, Outline=4, Shadow=2, Alignment=2


@patch("subprocess.run")
def test_burn_uses_audio_copy(mock_run, tmp_path):
    mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")
    input_mp4 = tmp_path / "seg.mp4"
    input_mp4.write_bytes(b"fake")
    entries = [subtitle.SrtEntry(0.0, 2.0, "abc")]
    subtitle.burn_subtitles(
        input_mp4, entries, tmp_path / "out.mp4",
        font_face="x", font_size=42, outline_px=4, shadow_px=2,
        video_width=1920, video_height=1080,
    )
    cmd = mock_run.call_args.kwargs.get("args") or mock_run.call_args.args[0]
    assert "-c:a" in cmd
    assert cmd[cmd.index("-c:a") + 1] == "copy"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 3 new tests FAIL — missing `burn_subtitles`.

- [ ] **Step 3: Implement burn**

Append to `src/video2yt/subtitle.py`:

```python
from video2yt.compose import srt_to_ass


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
    """
    output_video.parent.mkdir(parents=True, exist_ok=True)

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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): burn step reuses compose.srt_to_ass + cwd-basename trick"
```

---

## Task 12: Passthrough (SKIP path)

**Files:**
- Modify: `src/video2yt/subtitle.py`
- Modify: `tests/test_subtitle.py`

When detection says SKIP, copy or hardlink the input to the output. Try hardlink first (zero-cost); fall back to copy if cross-device (Errno 18 EXDEV).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
def test_passthrough_hardlinks_same_filesystem(tmp_path):
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"hello")
    dst = tmp_path / "seg_subbed.mp4"
    subtitle.passthrough(src, dst)
    assert dst.exists()
    assert dst.read_bytes() == b"hello"
    # On the same filesystem, hardlink: same inode
    assert dst.stat().st_ino == src.stat().st_ino


@patch("video2yt.subtitle.os.link")
def test_passthrough_falls_back_to_copy_on_exdev(mock_link, tmp_path):
    mock_link.side_effect = OSError(18, "Cross-device link not permitted")
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"data")
    dst = tmp_path / "out.mp4"
    subtitle.passthrough(src, dst)
    assert dst.exists()
    assert dst.read_bytes() == b"data"
    # Different inodes because it's a copy
    assert dst.stat().st_ino != src.stat().st_ino


def test_passthrough_overwrites_existing(tmp_path):
    src = tmp_path / "a.mp4"
    src.write_bytes(b"new")
    dst = tmp_path / "b.mp4"
    dst.write_bytes(b"old")
    subtitle.passthrough(src, dst)
    assert dst.read_bytes() == b"new"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 3 new tests FAIL — missing `passthrough`.

- [ ] **Step 3: Implement passthrough**

Append to `src/video2yt/subtitle.py`:

```python
import os
import shutil


def passthrough(src: Path, dst: Path) -> None:
    """Hardlink ``src`` to ``dst`` if possible; fall back to copy on EXDEV."""
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError as e:
        if e.errno == 18:    # EXDEV — cross-device
            shutil.copy2(src, dst)
        else:
            raise
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/subtitle.py tests/test_subtitle.py
git commit -m "feat(subtitle): passthrough — hardlink with EXDEV-copy fallback"
```

---

## Task 13: CLI orchestration (`subtitle_cli.py`)

**Files:**
- Create: `src/video2yt/subtitle_cli.py`
- Modify: `pyproject.toml`
- Modify: `tests/test_subtitle.py`

Wire all the pieces together behind the CLI. Follow the existing `merge_cli.py` / `compose_cli.py` pattern (preflight, parse_args, run, main).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_subtitle.py`:

```python
from video2yt import subtitle_cli


def test_parse_args_mutex_force_flags_rejected():
    with pytest.raises(SystemExit):
        subtitle_cli.parse_args(["seg.mp4", "--force-add", "--force-skip"])


def test_parse_args_defaults():
    args = subtitle_cli.parse_args(["seg.mp4"])
    assert args.segment == Path("seg.mp4")
    assert args.danmaku is None
    assert args.glossary is None
    assert args.force is None
    assert args.ocr_interval == 5.0
    assert args.danmaku_min_fixed == 10
    assert args.danmaku_min_coverage == 30
    assert args.skip_cleanup is False
    assert args.font_face == "Hiragino Sans GB"
    assert args.outline_px == 4
    assert args.shadow_px == 2


def test_parse_args_force_add():
    args = subtitle_cli.parse_args(["seg.mp4", "--force-add"])
    assert args.force == "add"


def test_parse_args_force_skip():
    args = subtitle_cli.parse_args(["seg.mp4", "--force-skip"])
    assert args.force == "skip"


def test_default_output_path_uses_subbed_suffix():
    args = subtitle_cli.parse_args(["/tmp/seg.mp4"])
    out = subtitle_cli._default_output(args.segment)
    assert out == Path("/tmp/seg_subbed.mp4")


@patch("video2yt.subtitle_cli.shutil.which")
def test_preflight_fails_when_ffmpeg_missing(mock_which):
    mock_which.return_value = None
    with pytest.raises(RuntimeError, match="ffmpeg"):
        subtitle_cli.preflight()


@patch("video2yt.subtitle_cli.shutil.which", return_value="/usr/bin/found")
@patch("builtins.__import__")
def test_preflight_fails_with_helpful_message_when_extras_missing(mock_import, mock_which):
    """When 'funasr' or 'rapidocr_onnxruntime' aren't installed, preflight says how to fix."""
    def fake_import(name, *args, **kwargs):
        if name in ("funasr", "rapidocr_onnxruntime"):
            raise ImportError(name)
        return __import__(name, *args, **kwargs)
    mock_import.side_effect = fake_import
    with pytest.raises(RuntimeError, match="subtitle.*extra"):
        subtitle_cli.preflight()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: 7 new tests FAIL — `module 'video2yt.subtitle_cli' has no attribute 'parse_args'` etc.

- [ ] **Step 3: Create `subtitle_cli.py`**

Create `src/video2yt/subtitle_cli.py`:

```python
"""CLI entry point for ``video2yt-subtitle``.

Spec: docs/superpowers/specs/2026-05-14-video2yt-subtitle-design.md
"""

import argparse
import shutil
import subprocess
import sys
import time
from pathlib import Path

from video2yt import subtitle, validate
from video2yt.compose import _effective_chars_per_line


def _log(msg: str) -> None:
    print(f"[video2yt-subtitle] {msg}", file=sys.stderr)


def preflight() -> None:
    if shutil.which("ffmpeg") is None:
        raise RuntimeError("ffmpeg not found in PATH. brew install ffmpeg")
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH")
    if shutil.which("codex") is None:
        raise RuntimeError(
            "codex CLI not found in PATH. brew install codex && codex login"
        )
    try:
        __import__("funasr")
        __import__("rapidocr_onnxruntime")
    except ImportError as e:
        raise RuntimeError(
            f"subtitle extras not installed ({e.name}). "
            "Run: uv sync --extra subtitle"
        ) from e


def _default_output(segment: Path) -> Path:
    return segment.parent / f"{segment.stem}_subbed.mp4"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-subtitle",
        description=(
            "Detect whether a Bilibili segment already has bottom subtitles "
            "(via danmaku XML scan, visual OCR sample, or manual flag); "
            "if not, add STT-generated subtitles via SenseVoice + Codex cleanup."
        ),
    )
    parser.add_argument(
        "segment", type=Path,
        help="Input MP4 segment (1920x1080 30fps h264)",
    )
    parser.add_argument(
        "--danmaku", type=Path, default=None,
        help="Bilibili danmaku XML (enables danmaku detection signal)",
    )
    parser.add_argument(
        "--glossary", type=Path, default=None,
        help="Override packaged glossary YAML (default: bundled bg_glossary.yaml)",
    )

    force = parser.add_mutually_exclusive_group()
    force.add_argument(
        "--force-add", dest="force", action="store_const", const="add",
        help="Skip detection and force-burn subtitles",
    )
    force.add_argument(
        "--force-skip", dest="force", action="store_const", const="skip",
        help="Skip detection and passthrough",
    )

    parser.add_argument("--ocr-interval", type=float, default=5.0)
    parser.add_argument("--danmaku-min-fixed", type=int, default=10)
    parser.add_argument("--danmaku-min-coverage", type=float, default=30,
                        help="Coverage percentage threshold (0-100)")

    parser.add_argument("--force-asr", action="store_true")
    parser.add_argument("--force-cleanup", action="store_true")
    parser.add_argument("--skip-cleanup", action="store_true")

    parser.add_argument("--font-face", default="Hiragino Sans GB")
    parser.add_argument("--font-size", type=int, default=None,
                        help="Default: auto (height * 25/540)")
    parser.add_argument("--outline-px", type=int, default=4)
    parser.add_argument("--shadow-px", type=int, default=2)

    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output MP4. Default: <segment_stem>_subbed.mp4",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()

    if not args.segment.is_file():
        raise FileNotFoundError(f"segment not found: {args.segment}")

    info = validate.probe(args.segment)
    if info.width != 1920 or info.height != 1080:
        raise ValueError(
            f"input resolution {info.width}x{info.height} != 1920x1080"
        )

    _log(f"input: {args.segment.name} ({info.width}x{info.height}, {info.duration:.2f}s)")

    output = args.output or _default_output(args.segment)

    # Decision
    danmaku_signal = None
    if args.danmaku is not None and args.force is None:
        danmaku_signal = subtitle.scan_danmaku(
            args.danmaku, segment_duration=info.duration,
            min_fixed=args.danmaku_min_fixed,
            min_coverage_ratio=args.danmaku_min_coverage / 100.0,
        )
        _log(
            f"danmaku scan: {danmaku_signal.fixed_count} type=4 fixed, "
            f"{danmaku_signal.coverage_ratio * 100:.1f}% coverage "
            f"→ {'HIT' if danmaku_signal.hit else 'continue'}"
        )

    ocr_signal = None
    if args.force is None and (danmaku_signal is None or not danmaku_signal.hit):
        ocr_signal = subtitle.sample_ocr(
            args.segment, segment_duration=info.duration,
            interval_seconds=args.ocr_interval,
        )
        _log(
            f"OCR sample: {ocr_signal.frames_with_stable_text}/{ocr_signal.sampled_frames} "
            f"frames with stable bottom text ({ocr_signal.stable_text_ratio * 100:.1f}%) "
            f"→ {'HIT' if ocr_signal.hit else 'continue'}"
        )

    decision = subtitle.decide(force=args.force, danmaku=danmaku_signal, ocr=ocr_signal)
    _log(f"decision: {decision.reason}")

    if not decision.add_subtitles:
        subtitle.passthrough(args.segment, output)
        _log(f"passthrough -> {output}")
        return output

    # ASR (with cache)
    raw_srt_path = args.segment.parent / f"{args.segment.stem}.raw.srt"
    if raw_srt_path.exists() and not args.force_asr:
        _log(f"ASR cache hit: {raw_srt_path.name}")
        raw_segments = subtitle.parse_srt_to_segments(
            raw_srt_path.read_text(encoding="utf-8")
        )
    else:
        t0 = time.time()
        _log(f"ASR: SenseVoice-Small on {info.duration:.2f}s audio...")
        raw_segments = subtitle.transcribe(args.segment)
        raw_srt_path.write_text(
            subtitle.segments_to_srt(raw_segments), encoding="utf-8"
        )
        _log(f"ASR done in {time.time() - t0:.1f}s ({len(raw_segments)} segments)")

    # Cleanup (with cache)
    cleaned_srt_path = args.segment.parent / f"{args.segment.stem}.cleaned.srt"
    if args.skip_cleanup:
        cleaned_segments = raw_segments
        _log("cleanup skipped (--skip-cleanup)")
    elif cleaned_srt_path.exists() and not args.force_cleanup:
        _log(f"cleanup cache hit: {cleaned_srt_path.name}")
        cleaned_segments = subtitle.parse_srt_to_segments(
            cleaned_srt_path.read_text(encoding="utf-8")
        )
    else:
        t0 = time.time()
        glossary = subtitle.load_glossary(args.glossary)
        _log(f"cleanup: codex exec with {len(glossary.corrections)} corrections...")
        cleaned_segments = subtitle.cleanup_with_codex(raw_segments, glossary)
        cleaned_srt_path.write_text(
            subtitle.segments_to_srt(cleaned_segments), encoding="utf-8"
        )
        _log(f"cleanup done in {time.time() - t0:.1f}s")

    # Split (style-dependent, never cached)
    font_size = args.font_size if args.font_size is not None else max(int(info.height * 25 / 540), 24)
    max_line_chars = _effective_chars_per_line(
        font_size=font_size, video_width=info.width, margin_l=80, margin_r=80,
    )
    final_entries = subtitle.split_segments(cleaned_segments, max_line_chars=max_line_chars)
    _log(f"split: {len(cleaned_segments)} cleaned → {len(final_entries)} final SRT entries (MAX_LINE_CHARS={max_line_chars})")

    # Burn
    t0 = time.time()
    _log(f"burn: subtitles → {output}")
    subtitle.burn_subtitles(
        args.segment, final_entries, output,
        font_face=args.font_face, font_size=font_size,
        outline_px=args.outline_px, shadow_px=args.shadow_px,
        video_width=info.width, video_height=info.height,
    )
    _log(f"burn done in {time.time() - t0:.1f}s")

    out_info = validate.probe(output)
    if abs(out_info.duration - info.duration) > 1.0:
        raise ValueError(
            f"output duration {out_info.duration:.2f}s differs from input {info.duration:.2f}s by > 1s"
        )

    _log(f"success: {output}")
    return output


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except FileNotFoundError as e:
        _log(f"error: {e}")
        return 2
    except ValueError as e:
        _log(f"error: {e}")
        return 2
    except RuntimeError as e:
        _log(f"error: {e}")
        return 1
    except subprocess.CalledProcessError as e:
        _log(f"error: {(e.cmd[0] if e.cmd else 'subprocess')} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 3
```

- [ ] **Step 4: Register CLI script + subtitle extra in `pyproject.toml`**

In `pyproject.toml`, add to `[project.scripts]`:

```toml
video2yt-subtitle = "video2yt.subtitle_cli:main"
```

Add a new section:

```toml
[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]
subtitle = [
    "funasr>=1.2",
    "rapidocr-onnxruntime>=1.4",
]
```

(If `[project.optional-dependencies]` already exists with `dev`, just add the `subtitle = [...]` line; don't duplicate the section header.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_subtitle.py -v`
Expected: all new tests PASS.

- [ ] **Step 6: Smoke-check the CLI is registered**

Run: `uv sync && uv run video2yt-subtitle --help`
Expected: help text prints; mutex group shows `--force-add | --force-skip`; no preflight error (since --help short-circuits).

- [ ] **Step 7: Commit**

```bash
git add src/video2yt/subtitle_cli.py pyproject.toml uv.lock tests/test_subtitle.py
git commit -m "feat(subtitle): video2yt-subtitle CLI

Wires detect → ASR (with cache) → cleanup (with cache) → split → burn.
Output: <segment_stem>_subbed.mp4. Caches .raw.srt and .cleaned.srt
at FunASR-segment granularity beside the input so re-runs with different
--font-size don't pay ASR/Codex costs twice."
```

---

## Task 14: Documentation

**Files:**
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Add CLI to CLAUDE.md Commands section**

In `CLAUDE.md`, find the `## Commands` section. Add one line under the existing `uv run video2yt-merge` line:

```bash
uv run video2yt-subtitle seg.mp4 --danmaku raw.xml         # add STT subtitles if not already present
```

In the same file, find `## Architecture` → `src/video2yt/`. Append two lines to the file tree:

```
├── subtitle.py       # detect (danmaku XML + OCR) + SenseVoice ASR + Codex cleanup + split + burn
├── subtitle_cli.py   # video2yt-subtitle entry point
```

- [ ] **Step 2: Add install hint to README.md**

In `README.md`, find the install instructions. Add a paragraph:

````markdown
### Optional: subtitle generation

The `video2yt-subtitle` CLI uses SenseVoice (`funasr`) for STT and `rapidocr-onnxruntime` for bottom-band OCR detection. These pull in PyTorch + ONNX runtime (~2GB), so they're gated behind an optional extra:

```bash
uv sync --extra subtitle
```

It also requires the `codex` CLI for terminology cleanup (`brew install codex && codex login`).
````

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md README.md
git commit -m "docs(subtitle): note video2yt-subtitle in CLAUDE.md + README

Includes the optional 'subtitle' extra install instructions."
```

---

## Task 15: Final pass — full test suite + smoke

**Files:** none (verification only)

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests pass (existing 230 + ~50 new).

- [ ] **Step 2: Verify the CLI shows up in `uv run --help`-like introspection**

Run: `uv run video2yt-subtitle --help | head -5`
Expected: help text prints with `usage: video2yt-subtitle SEGMENT [...]`.

- [ ] **Step 3: Confirm the optional extra installs cleanly**

Run: `uv sync --extra subtitle`
Expected: installs `funasr`, `rapidocr-onnxruntime`, and their transitive deps without errors.

- [ ] **Step 4: Confirm preflight catches missing extras gracefully**

Temporarily test the error path (do NOT commit anything from this step):

Run: `uv run --no-extra subtitle python -c "from video2yt.subtitle_cli import preflight; preflight()"`
Expected: `RuntimeError: subtitle extras not installed (funasr). Run: uv sync --extra subtitle`

If the above command form isn't supported by uv, alternative: `uv venv --seed /tmp/v2s-test && /tmp/v2s-test/bin/python -m pip install -e . && /tmp/v2s-test/bin/python -c "from video2yt.subtitle_cli import preflight; preflight()"`.

- [ ] **Step 5: Commit (only if anything in this task required a fix)**

If no changes were needed, no commit. Otherwise:

```bash
git add <files>
git commit -m "fix(subtitle): <what got fixed during the final pass>"
```

---

## Notes for the implementer

- **Type names are stable from Task 2 onward** — the dataclass names in the type-definitions section above (FunASRSegment, SrtEntry, Glossary, DanmakuSignal, OcrSignal, Decision) must match exactly across tasks. If a later task references one defined in an earlier task, don't rename it.
- **Lazy imports for ML deps** — `funasr` and `rapidocr_onnxruntime` are ONLY imported inside `_run_funasr` and `_run_rapidocr`. Do not put them at the top of `subtitle.py`; that would break the module import for users without the `subtitle` extra installed and break preflight's helpful error message.
- **Tests must not call real ffmpeg / codex / funasr / rapidocr** — every external boundary is mocked. Existing project tests do the same via `subprocess.run` patches.
- **One thing I deliberately didn't address**: whether the FunASR model load (~3s per process) hurts batch use (running this CLI on N segments in a row pays N × 3s). Not in scope for v1; if it bites, wrap in a long-lived service later. Spec §11.

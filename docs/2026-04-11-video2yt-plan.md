# video2yt Implementation Plan

> **For agentic workers:** Use checkbox (`- [ ]`) syntax below for tracking. Execute tasks in order. Each task is self-contained and ends with a commit.

**Goal:** Build a CLI tool that takes a Bilibili video URL and produces an MP4 with danmaku (bullet comments) burned into the video.

**Architecture:** Single Python package (`src/video2yt/`) orchestrating `yt-dlp` (with `yt-dlp-danmaku` plugin) for download and `ffmpeg` for burning. Four focused modules: `cli.py` (entry + flow), `download.py` (yt-dlp wrapper), `burn.py` (ffmpeg wrapper), `validate.py` (ffprobe + ASS checks).

**Tech Stack:** Python 3.10+, `uv` package manager, `yt-dlp`, `yt-dlp-danmaku` (uses `biliass`), `ffmpeg`/`ffprobe`, `pytest` (dev).

**Spec:** [`/Users/jun/code/video2yt/docs/2026-04-11-video2yt-design.md`](./2026-04-11-video2yt-design.md)

---

## File Structure

Files that will be created in this plan:

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv project metadata, deps, console script entry |
| `.python-version` | Python version pin |
| `.gitignore` | Ignore temp/, output/, __pycache__, .venv, uv.lock lives in repo |
| `CLAUDE.md` | Agent project context (commands, gotchas) |
| `README.md` | Human user docs (install, run, examples) |
| `src/video2yt/__init__.py` | Package marker |
| `src/video2yt/__main__.py` | Entry for `python -m video2yt` |
| `src/video2yt/cli.py` | Arg parsing, URL parsing, preflight, orchestration |
| `src/video2yt/download.py` | `yt-dlp` subprocess wrapper; returns (video_path, ass_path) |
| `src/video2yt/burn.py` | `ffmpeg` subprocess wrapper; burns ASS into video |
| `src/video2yt/validate.py` | `ffprobe` wrapper + source/ASS/output validators |
| `tests/test_smoke.py` | Unit tests (subprocess mocked throughout) |
| `docs/plan.md` | (Moved from root) Original plan.md |

---

## Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`, `CLAUDE.md`
- Create: `src/video2yt/__init__.py`, `src/video2yt/__main__.py`
- Create: `tests/__init__.py`
- Create: `docs/` (already exists)
- Move: `plan.md` → `docs/plan.md`

- [ ] **Step 1: Initialize git repo**

Run:
```bash
cd /Users/jun/code/video2yt
git init
git config init.defaultBranch main
```

- [ ] **Step 2: Initialize uv project** (creates `pyproject.toml`, `.python-version`, `.gitignore`, `README.md`)

Run:
```bash
cd /Users/jun/code/video2yt
uv init --package --name video2yt --lib
```

Note: `uv init --package --lib` creates a `src/video2yt/` layout. If uv version doesn't support `--lib`, fall back to `uv init --package --name video2yt` and manually move the created file to `src/video2yt/`.

- [ ] **Step 3: Overwrite `pyproject.toml` with project config**

Replace the generated `pyproject.toml` with this exact content:

```toml
[project]
name = "video2yt"
version = "0.1.0"
description = "Download a Bilibili video and burn danmaku into the output MP4"
requires-python = ">=3.10"
readme = "README.md"
dependencies = [
    "yt-dlp>=2025.1.1",
    "yt-dlp-danmaku>=0.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
]

[project.scripts]
video2yt = "video2yt.cli:main"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/video2yt"]
```

- [ ] **Step 4: Overwrite `.gitignore`**

Replace with:

```gitignore
# uv
.venv/
__pycache__/
*.pyc
.pytest_cache/
dist/
build/
*.egg-info/

# runtime
temp/
output/
logs/

# macOS
.DS_Store
```

- [ ] **Step 5: Write `.python-version`**

Content:
```
3.11
```

- [ ] **Step 6: Write `src/video2yt/__init__.py`** (empty file)

```python
```

- [ ] **Step 7: Write `src/video2yt/__main__.py`**

```python
from video2yt.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 8: Create `tests/__init__.py`** (empty file)

```python
```

- [ ] **Step 9: Write `README.md`**

```markdown
# video2yt

Download a Bilibili video and burn danmaku (bullet comments) into the output MP4.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` in PATH (macOS: `brew install ffmpeg`)
- Chrome browser installed (for cookie-based login to access 1080p content)

## Install

```bash
uv sync
```

## Usage

```bash
uv run video2yt "https://www.bilibili.com/video/BVxxxxxxxxxx/" --quality 1080
```

Options:

| Flag | Default | Description |
|---|---|---|
| `-o, --output-dir` | `./output` | Where the final MP4 goes |
| `-t, --temp-dir` | `./temp` | Intermediate files (deleted on success) |
| `-q, --quality` | `1080` | Max quality (1080 / 720 / 480) |
| `-b, --browser` | `chrome` | Browser to read cookies from |
| `--keep-temp` | off | Keep intermediate files after success |

## Development

```bash
uv run pytest
```
```

- [ ] **Step 10: Write `CLAUDE.md`**

```markdown
# CLAUDE.md

Project context for Claude agents working in this repo.

## Purpose

A local CLI that takes a Bilibili video URL and produces an MP4 with danmaku burned in. Pipeline: `yt-dlp` (with `yt-dlp-danmaku` plugin) → `.danmaku.ass` → `ffmpeg subtitles=` filter → output MP4.

## Commands

- Run: `uv run video2yt "<url>"`
- Run as module: `uv run python -m video2yt "<url>"`
- Test: `uv run pytest`
- Add a dep: `uv add <pkg>` (NEVER edit `pyproject.toml` dependencies by hand)

## External dependencies

- `ffmpeg` and `ffprobe` must be in PATH (system install, not Python package). Check with `shutil.which('ffmpeg')`.
- `yt-dlp-danmaku` is a yt-dlp postprocessor plugin. It is invoked via `yt-dlp --use-postprocessor danmaku`. Its runtime module is `biliass`; check installation with `import biliass`.

## Known gotchas

- **ffmpeg `subtitles=` filter path escaping**: The `subtitles=<path>` filter in `-vf` chokes on absolute paths containing spaces, colons, or parentheses. The project-wide workaround is in `burn.py`: run `subprocess` with `cwd=temp_dir` and pass the ASS filename as a basename (relative path). The `-i` input is also a basename. Only the output path is absolute (ffmpeg output args do not go through filters).
- **yt-dlp release cadence**: yt-dlp updates frequently because Bilibili's extractor rules shift. If downloads suddenly break, first try `uv lock --upgrade-package yt-dlp`.
- **Chrome cookie DB lock**: `--cookies-from-browser chrome` requires Chrome to not be holding the cookie database lock. If it fails, close Chrome first.

## Architecture

4 modules in `src/video2yt/`:

- `cli.py` — arg parsing, URL parsing (BV regex), dependency preflight, orchestration
- `download.py` — single public function `fetch(url, temp_dir, quality, browser, bv_id) -> (video_path, ass_path)`
- `burn.py` — single public function `render(video_path, ass_path, output_path) -> Path`
- `validate.py` — `MediaInfo` dataclass + `probe`, `check_source`, `check_ass`, `check_output`

Tests live in `tests/test_smoke.py`. Everything is mocked at the `subprocess.run` boundary — no network, no ffmpeg, no ffprobe is actually invoked in tests.
```

- [ ] **Step 11: Move `plan.md` into `docs/`**

Run:
```bash
mv /Users/jun/code/video2yt/plan.md /Users/jun/code/video2yt/docs/plan.md
```

- [ ] **Step 12: Install deps**

Run:
```bash
cd /Users/jun/code/video2yt
uv sync --extra dev
```

Expected: creates `.venv/`, installs yt-dlp, yt-dlp-danmaku, pytest, and transitively biliass. Exits 0.

- [ ] **Step 13: Smoke check that tooling works**

Run:
```bash
cd /Users/jun/code/video2yt
uv run python -c "import biliass; print('biliass ok')"
uv run python -c "import yt_dlp; print('yt-dlp ok')"
```

Expected: both print "ok". If `biliass` import fails, run `uv add yt-dlp-danmaku` and retry.

- [ ] **Step 14: Commit**

```bash
cd /Users/jun/code/video2yt
git add .python-version .gitignore pyproject.toml uv.lock README.md CLAUDE.md src tests docs
git rm plan.md 2>/dev/null || true  # if still tracked; usually not since first commit
git add docs/plan.md
git commit -m "chore: scaffold project structure with uv"
```

---

## Task 2: `validate.MediaInfo` + `validate.probe()`

**Files:**
- Create: `src/video2yt/validate.py`
- Create: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_smoke.py` with:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from video2yt import validate
from video2yt.validate import MediaInfo


def _make_ffprobe_output(duration=60.0, width=1920, height=1080, vcodec="h264", acodec="aac"):
    streams = []
    if vcodec:
        streams.append({"codec_type": "video", "codec_name": vcodec, "width": width, "height": height})
    if acodec:
        streams.append({"codec_type": "audio", "codec_name": acodec})
    return json.dumps({"streams": streams, "format": {"duration": str(duration)}})


def test_probe_parses_ffprobe_output(tmp_path, monkeypatch):
    fake_file = tmp_path / "test.mp4"
    fake_file.write_bytes(b"x" * 1000)

    def fake_run(cmd, **kwargs):
        assert cmd[0] == "ffprobe"
        assert str(fake_file) in cmd
        result = MagicMock()
        result.stdout = _make_ffprobe_output()
        result.returncode = 0
        return result

    monkeypatch.setattr("video2yt.validate.subprocess.run", fake_run)
    info = validate.probe(fake_file)

    assert info.duration == 60.0
    assert info.width == 1920
    assert info.height == 1080
    assert info.has_video is True
    assert info.has_audio is True
    assert info.vcodec == "h264"
    assert info.acodec == "aac"
    assert info.size_bytes == 1000


def test_probe_raises_on_missing_file(tmp_path):
    with pytest.raises(FileNotFoundError):
        validate.probe(tmp_path / "does_not_exist.mp4")
```

- [ ] **Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: FAIL with `ModuleNotFoundError: No module named 'video2yt.validate'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/video2yt/validate.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: 2 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/validate.py tests/test_smoke.py
git commit -m "feat(validate): MediaInfo + probe() via ffprobe"
```

---

## Task 3: `validate.check_source()`

**Files:**
- Modify: `src/video2yt/validate.py` (append)
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def _mk_info(**kw):
    defaults = dict(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac",
        size_bytes=10_000_000,
    )
    defaults.update(kw)
    return MediaInfo(**defaults)


def test_check_source_raises_without_video_stream():
    info = _mk_info(has_video=False, width=0, height=0, vcodec="")
    with pytest.raises(ValueError, match="no video stream"):
        validate.check_source(info, 1080)


def test_check_source_raises_on_zero_duration():
    info = _mk_info(duration=0)
    with pytest.raises(ValueError, match="duration"):
        validate.check_source(info, 1080)


def test_check_source_warns_on_missing_audio():
    info = _mk_info(has_audio=False, acodec=None)
    warnings = validate.check_source(info, 1080)
    assert any("audio" in w.lower() for w in warnings)


def test_check_source_warns_on_low_resolution():
    info = _mk_info(width=1280, height=720)
    warnings = validate.check_source(info, 1080)
    assert any("resolution" in w.lower() or "720" in w for w in warnings)


def test_check_source_no_warnings_for_exact_match():
    info = _mk_info()
    warnings = validate.check_source(info, 1080)
    assert warnings == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k check_source
```

Expected: FAIL with `AttributeError: module 'video2yt.validate' has no attribute 'check_source'`.

- [ ] **Step 3: Implement**

Append to `src/video2yt/validate.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all tests PASS (2 from previous task + 5 new = 7).

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/validate.py tests/test_smoke.py
git commit -m "feat(validate): check_source() for source video validation"
```

---

## Task 4: `validate.check_ass()`

**Files:**
- Modify: `src/video2yt/validate.py` (append)
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
def test_check_ass_raises_on_missing_file(tmp_path):
    with pytest.raises(ValueError, match="not found"):
        validate.check_ass(tmp_path / "missing.ass")


def test_check_ass_raises_without_events_section(tmp_path):
    f = tmp_path / "no_events.ass"
    f.write_text("[Script Info]\nTitle: foo\n", encoding="utf-8")
    with pytest.raises(ValueError, match=r"\[Events\]"):
        validate.check_ass(f)


def test_check_ass_raises_on_zero_dialogue(tmp_path):
    f = tmp_path / "empty.ass"
    f.write_text(
        "[Script Info]\n\n[Events]\nFormat: Layer, Start, End, Style, Text\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="Dialogue|danmaku"):
        validate.check_ass(f)


def test_check_ass_returns_dialogue_count(tmp_path):
    f = tmp_path / "ok.ass"
    f.write_text(
        "[Script Info]\n\n[Events]\n"
        "Format: Layer, Start, End, Style, Text\n"
        "Dialogue: 0,0:00:01.00,0:00:05.00,Default,hello\n"
        "Dialogue: 0,0:00:02.00,0:00:06.00,Default,world\n"
        "Dialogue: 0,0:00:03.00,0:00:07.00,Default,foo\n",
        encoding="utf-8",
    )
    assert validate.check_ass(f) == 3
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k check_ass
```

Expected: FAIL with `AttributeError: ... has no attribute 'check_ass'`.

- [ ] **Step 3: Implement**

Append to `src/video2yt/validate.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 11 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/validate.py tests/test_smoke.py
git commit -m "feat(validate): check_ass() for ASS structural validation"
```

---

## Task 5: `validate.check_output()`

**Files:**
- Modify: `src/video2yt/validate.py` (append)
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
def test_check_output_raises_on_empty_file():
    source = _mk_info()
    output = _mk_info(size_bytes=0)
    with pytest.raises(ValueError, match="empty"):
        validate.check_output(source, output)


def test_check_output_raises_on_missing_video_stream():
    source = _mk_info()
    output = _mk_info(has_video=False, vcodec="")
    with pytest.raises(ValueError, match="video stream"):
        validate.check_output(source, output)


def test_check_output_raises_when_audio_lost():
    source = _mk_info(has_audio=True)
    output = _mk_info(has_audio=False, acodec=None)
    with pytest.raises(ValueError, match="audio"):
        validate.check_output(source, output)


def test_check_output_raises_on_wrong_vcodec():
    source = _mk_info()
    output = _mk_info(vcodec="hevc")
    with pytest.raises(ValueError, match="vcodec|h264"):
        validate.check_output(source, output)


def test_check_output_raises_on_duration_mismatch():
    source = _mk_info(duration=60.0)
    output = _mk_info(duration=58.5)
    with pytest.raises(ValueError, match="duration"):
        validate.check_output(source, output)


def test_check_output_allows_small_duration_drift():
    source = _mk_info(duration=60.0)
    output = _mk_info(duration=60.3)
    warnings = validate.check_output(source, output)
    assert warnings == []


def test_check_output_raises_on_resolution_mismatch():
    source = _mk_info(width=1920, height=1080)
    output = _mk_info(width=1280, height=720)
    with pytest.raises(ValueError, match="resolution"):
        validate.check_output(source, output)


def test_check_output_warns_on_tiny_output():
    source = _mk_info(size_bytes=10_000_000)
    output = _mk_info(size_bytes=100_000)  # 0.01x
    warnings = validate.check_output(source, output)
    assert any("size" in w.lower() for w in warnings)


def test_check_output_warns_on_huge_output():
    source = _mk_info(size_bytes=10_000_000)
    output = _mk_info(size_bytes=100_000_000)  # 10x
    warnings = validate.check_output(source, output)
    assert any("size" in w.lower() for w in warnings)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k check_output
```

Expected: FAIL with `AttributeError: ... has no attribute 'check_output'`.

- [ ] **Step 3: Implement**

Append to `src/video2yt/validate.py`:

```python
def check_output(source: MediaInfo, output: MediaInfo) -> list[str]:
    """Validate burned output against source. Raises on hard failures; returns warnings."""
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
    if abs(output.duration - source.duration) >= 1.0:
        raise ValueError(
            f"output duration {output.duration:.2f}s differs from source "
            f"{source.duration:.2f}s by more than 1 second (possible truncation)"
        )
    if output.width != source.width or output.height != source.height:
        raise ValueError(
            f"output resolution {output.width}x{output.height} differs from "
            f"source {source.width}x{source.height}"
        )
    warnings: list[str] = []
    if source.size_bytes > 0:
        ratio = output.size_bytes / source.size_bytes
        if ratio < 0.3 or ratio > 5.0:
            warnings.append(
                f"output size is {ratio:.2f}x source "
                f"({output.size_bytes} vs {source.size_bytes} bytes); "
                f"may indicate encoding issue"
            )
    return warnings
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 20 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/validate.py tests/test_smoke.py
git commit -m "feat(validate): check_output() to compare source and output"
```

---

## Task 6: `download.fetch()`

**Files:**
- Create: `src/video2yt/download.py`
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
from video2yt import download


def test_fetch_builds_correct_yt_dlp_command(tmp_path, monkeypatch):
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        # Simulate yt-dlp producing the output files
        (tmp_path / "BV191DpBmE2t.mp4").write_bytes(b"fake video")
        (tmp_path / "BV191DpBmE2t.danmaku.ass").write_text(
            "[Events]\nDialogue: 0,0:00:01.00,0:00:05.00,Default,hi\n",
            encoding="utf-8",
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)

    video, ass = download.fetch(
        url="https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=x",
        temp_dir=tmp_path,
        quality=1080,
        browser="chrome",
        bv_id="BV191DpBmE2t",
    )

    cmd = captured["cmd"]
    assert cmd[0] == "yt-dlp"
    # cookies
    assert "--cookies-from-browser" in cmd
    assert "chrome" in cmd
    # format with quality
    fmt_idx = cmd.index("-f")
    assert "height<=1080" in cmd[fmt_idx + 1]
    assert cmd[fmt_idx + 1].endswith("/b")  # fallback sentinel
    # danmaku postprocessor
    assert "--use-postprocessor" in cmd
    pp_idx = cmd.index("--use-postprocessor")
    assert cmd[pp_idx + 1] == "danmaku"
    # write-subs present
    assert "--write-subs" in cmd
    # output template contains BV id and %(ext)s
    out_idx = cmd.index("--output")
    assert "BV191DpBmE2t" in cmd[out_idx + 1]
    assert "%(ext)s" in cmd[out_idx + 1]
    # URL at end
    assert cmd[-1] == "https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=x"

    assert video == tmp_path / "BV191DpBmE2t.mp4"
    assert ass == tmp_path / "BV191DpBmE2t.danmaku.ass"


def test_fetch_uses_quality_720(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        fmt_idx = cmd.index("-f")
        assert "height<=720" in cmd[fmt_idx + 1]
        (tmp_path / "BV.mp4").write_bytes(b"v")
        (tmp_path / "BV.danmaku.ass").write_text(
            "[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8",
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    download.fetch("https://x/video/BV", tmp_path, 720, "chrome", "BV")


def test_fetch_raises_when_video_file_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        # Only create the ASS file, skip the video
        (tmp_path / "BV.danmaku.ass").write_text(
            "[Events]\nDialogue: x\n", encoding="utf-8",
        )
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    with pytest.raises(FileNotFoundError, match="video"):
        download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV")


def test_fetch_raises_when_ass_file_missing(tmp_path, monkeypatch):
    def fake_run(cmd, **kwargs):
        (tmp_path / "BV.mp4").write_bytes(b"v")
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.download.subprocess.run", fake_run)
    with pytest.raises(FileNotFoundError, match="ASS|ass"):
        download.fetch("https://x/video/BV", tmp_path, 1080, "chrome", "BV")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k fetch
```

Expected: FAIL with `ModuleNotFoundError: No module named 'video2yt.download'`.

- [ ] **Step 3: Implement**

Create `src/video2yt/download.py`:

```python
import subprocess
from pathlib import Path


def fetch(
    url: str,
    temp_dir: Path,
    quality: int,
    browser: str,
    bv_id: str,
) -> tuple[Path, Path]:
    """Download video + danmaku ASS via yt-dlp + yt-dlp-danmaku plugin.

    Returns (video_path, ass_path).
    """
    temp_dir.mkdir(parents=True, exist_ok=True)
    output_template = str(temp_dir / f"{bv_id}.%(ext)s")
    format_spec = f"bv*[height<={quality}]+ba/b[height<={quality}]/b"

    cmd = [
        "yt-dlp",
        "--cookies-from-browser", browser,
        "-f", format_spec,
        "--write-subs",
        "--use-postprocessor", "danmaku",
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

    # Find the ASS file (plugin decides exact suffix; usually .danmaku.ass)
    ass_candidates = sorted(temp_dir.glob(f"{bv_id}*.ass"))
    if not ass_candidates:
        raise FileNotFoundError(
            f"yt-dlp-danmaku did not produce an ASS file for {bv_id} in {temp_dir}"
        )
    ass_path = ass_candidates[0]

    return video_path, ass_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 24 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/download.py tests/test_smoke.py
git commit -m "feat(download): fetch() wraps yt-dlp + yt-dlp-danmaku plugin"
```

---

## Task 7: `burn.render()`

**Files:**
- Create: `src/video2yt/burn.py`
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
from video2yt import burn


def test_render_uses_cwd_and_relative_paths(tmp_path, monkeypatch):
    temp_dir = tmp_path / "temp"
    temp_dir.mkdir()
    video = temp_dir / "BV.mp4"
    video.write_bytes(b"video data")
    ass = temp_dir / "BV.danmaku.ass"
    ass.write_text("data", encoding="utf-8")
    output_dir = tmp_path / "output"
    output = output_dir / "BV_with_danmaku.mp4"

    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["cwd"] = kwargs.get("cwd")
        # Simulate ffmpeg writing the output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_bytes(b"burned video")
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.burn.subprocess.run", fake_run)

    result = burn.render(video, ass, output)

    assert result == output
    # cwd is the temp_dir containing video + ass
    assert captured["cwd"] == temp_dir
    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-y" in cmd
    # -i uses basename (relative to cwd)
    i_idx = cmd.index("-i")
    assert cmd[i_idx + 1] == "BV.mp4"
    # -vf subtitles= uses basename
    vf_idx = cmd.index("-vf")
    assert cmd[vf_idx + 1] == "subtitles=BV.danmaku.ass"
    # libx264 preset medium crf 20
    assert "libx264" in cmd
    crf_idx = cmd.index("-crf")
    assert cmd[crf_idx + 1] == "20"
    preset_idx = cmd.index("-preset")
    assert cmd[preset_idx + 1] == "medium"
    # audio copied
    ca_idx = cmd.index("-c:a")
    assert cmd[ca_idx + 1] == "copy"
    # output is absolute path, NOT relative
    output_arg = cmd[-1]
    assert Path(output_arg).is_absolute()
    assert Path(output_arg) == output.resolve()


def test_render_raises_if_video_and_ass_in_different_dirs(tmp_path):
    video = tmp_path / "a" / "v.mp4"
    video.parent.mkdir()
    video.write_bytes(b"v")
    ass = tmp_path / "b" / "v.ass"
    ass.parent.mkdir()
    ass.write_text("data", encoding="utf-8")
    output = tmp_path / "out.mp4"
    with pytest.raises(ValueError, match="same directory"):
        burn.render(video, ass, output)
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k render
```

Expected: FAIL with `ModuleNotFoundError: No module named 'video2yt.burn'`.

- [ ] **Step 3: Implement**

Create `src/video2yt/burn.py`:

```python
import subprocess
from pathlib import Path


def render(video_path: Path, ass_path: Path, output_path: Path) -> Path:
    """Burn an ASS subtitle into a video via ffmpeg.

    ffmpeg's `subtitles=` filter is hostile to absolute paths (escaping hell),
    so we cwd into the temp directory and pass basenames for -i and -vf.
    The output path stays absolute because ffmpeg output args do not go
    through filters.
    """
    if video_path.parent != ass_path.parent:
        raise ValueError(
            f"video and ASS must live in the same directory "
            f"(got {video_path.parent} and {ass_path.parent})"
        )
    temp_dir = video_path.parent
    output_path.parent.mkdir(parents=True, exist_ok=True)

    cmd = [
        "ffmpeg", "-y",
        "-i", video_path.name,
        "-vf", f"subtitles={ass_path.name}",
        "-c:a", "copy",
        "-c:v", "libx264",
        "-preset", "medium",
        "-crf", "20",
        str(output_path.resolve()),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=temp_dir)
    return output_path
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 26 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/burn.py tests/test_smoke.py
git commit -m "feat(burn): render() wraps ffmpeg subtitle burn"
```

---

## Task 8: `cli.extract_bv_id()`

**Files:**
- Create: `src/video2yt/cli.py` (first piece)
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
from video2yt import cli


def test_extract_bv_from_full_url_with_query():
    url = "https://www.bilibili.com/video/BV191DpBmE2t/?spm_id_from=333.337&vd_source=xxx"
    assert cli.extract_bv_id(url) == "BV191DpBmE2t"


def test_extract_bv_from_plain_url():
    assert cli.extract_bv_id("https://www.bilibili.com/video/BV1Sm4y1N78J") == "BV1Sm4y1N78J"


def test_extract_bv_from_url_with_trailing_slash():
    assert cli.extract_bv_id("https://www.bilibili.com/video/BV1Sm4y1N78J/") == "BV1Sm4y1N78J"


def test_extract_bv_raises_on_non_bilibili_url():
    with pytest.raises(ValueError, match="BV"):
        cli.extract_bv_id("https://www.youtube.com/watch?v=abc123")


def test_extract_bv_raises_on_empty_string():
    with pytest.raises(ValueError, match="BV"):
        cli.extract_bv_id("")
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k extract_bv
```

Expected: FAIL with `ModuleNotFoundError: No module named 'video2yt.cli'`.

- [ ] **Step 3: Implement**

Create `src/video2yt/cli.py`:

```python
import re

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")


def extract_bv_id(url: str) -> str:
    """Extract the BV id from a Bilibili video URL."""
    m = BV_PATTERN.search(url)
    if not m:
        raise ValueError(
            f"URL does not contain a BV id: {url!r}\n"
            f"expected format: https://www.bilibili.com/video/BV..."
        )
    return m.group(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 31 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/cli.py tests/test_smoke.py
git commit -m "feat(cli): extract_bv_id() for URL parsing"
```

---

## Task 9: `cli.preflight()`

**Files:**
- Modify: `src/video2yt/cli.py` (append)
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
def test_preflight_passes_when_everything_present(monkeypatch):
    monkeypatch.setattr("video2yt.cli.shutil.which", lambda name: f"/usr/local/bin/{name}")
    # biliass already installed in dev env; import should succeed
    cli.preflight()  # should not raise


def test_preflight_fails_without_ffmpeg(monkeypatch):
    def fake_which(name):
        return None if name == "ffmpeg" else f"/usr/local/bin/{name}"
    monkeypatch.setattr("video2yt.cli.shutil.which", fake_which)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        cli.preflight()


def test_preflight_fails_without_ffprobe(monkeypatch):
    def fake_which(name):
        return None if name == "ffprobe" else f"/usr/local/bin/{name}"
    monkeypatch.setattr("video2yt.cli.shutil.which", fake_which)
    with pytest.raises(RuntimeError, match="ffprobe"):
        cli.preflight()


def test_preflight_fails_without_biliass(monkeypatch):
    monkeypatch.setattr("video2yt.cli.shutil.which", lambda name: f"/usr/local/bin/{name}")
    import sys
    # Force biliass import to fail by injecting a sentinel into sys.modules
    monkeypatch.setitem(sys.modules, "biliass", None)
    with pytest.raises(RuntimeError, match="yt-dlp-danmaku|biliass"):
        cli.preflight()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k preflight
```

Expected: FAIL with `AttributeError: module 'video2yt.cli' has no attribute 'preflight'` (and/or no `shutil` import).

- [ ] **Step 3: Implement**

Modify `src/video2yt/cli.py`. Replace its current contents with:

```python
import importlib
import re
import shutil

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")


def extract_bv_id(url: str) -> str:
    """Extract the BV id from a Bilibili video URL."""
    m = BV_PATTERN.search(url)
    if not m:
        raise ValueError(
            f"URL does not contain a BV id: {url!r}\n"
            f"expected format: https://www.bilibili.com/video/BV..."
        )
    return m.group(1)


def preflight() -> None:
    """Fail fast if required external dependencies are missing."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: brew install ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "ffprobe not found in PATH (usually ships with ffmpeg)"
        )
    try:
        mod = importlib.import_module("biliass")
        if mod is None:
            raise ImportError("biliass is None")
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp-danmaku / biliass not available. Install with: "
            "uv add yt-dlp-danmaku"
        ) from e
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 35 tests PASS.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/cli.py tests/test_smoke.py
git commit -m "feat(cli): preflight() for dependency checks"
```

---

## Task 10: `cli.parse_args()`, `cli.run()`, `cli.main()`

**Files:**
- Modify: `src/video2yt/cli.py` (append)
- Modify: `tests/test_smoke.py` (append)

- [ ] **Step 1: Write failing tests**

Append to `tests/test_smoke.py`:

```python
def test_parse_args_defaults():
    args = cli.parse_args(["https://www.bilibili.com/video/BV1"])
    assert args.url == "https://www.bilibili.com/video/BV1"
    assert args.output_dir == Path("./output")
    assert args.temp_dir == Path("./temp")
    assert args.quality == 1080
    assert args.browser == "chrome"
    assert args.keep_temp is False


def test_parse_args_custom():
    args = cli.parse_args([
        "https://www.bilibili.com/video/BV1",
        "-o", "/tmp/out",
        "-t", "/tmp/tmp",
        "-q", "720",
        "-b", "firefox",
        "--keep-temp",
    ])
    assert args.output_dir == Path("/tmp/out")
    assert args.temp_dir == Path("/tmp/tmp")
    assert args.quality == 720
    assert args.browser == "firefox"
    assert args.keep_temp is True


def test_parse_args_rejects_bad_quality():
    with pytest.raises(SystemExit):
        cli.parse_args(["https://x", "-q", "4320"])


def test_run_orchestrates_full_pipeline(tmp_path, monkeypatch):
    """Full pipeline with all subprocess boundaries mocked; verifies call order."""
    call_log = []

    # Skip dep preflight
    monkeypatch.setattr("video2yt.cli.preflight", lambda: call_log.append("preflight"))

    def fake_fetch(url, temp_dir, quality, browser, bv_id):
        call_log.append(f"fetch:{bv_id}:{quality}:{browser}")
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"fakevideo")
        a = temp_dir / f"{bv_id}.danmaku.ass"
        a.write_text(
            "[Events]\n"
            "Format: Layer, Start, End, Style, Text\n"
            "Dialogue: 0,0:00:01.00,0:00:05.00,Default,hi\n",
            encoding="utf-8",
        )
        return v, a

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)

    probe_calls = []
    source_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=10_000_000,
    )
    output_info = MediaInfo(
        duration=60.0, width=1920, height=1080,
        has_video=True, has_audio=True,
        vcodec="h264", acodec="aac", size_bytes=11_000_000,
    )

    def fake_probe(path):
        probe_calls.append(path)
        # First call = source, second call = output
        return source_info if len(probe_calls) == 1 else output_info

    monkeypatch.setattr("video2yt.cli.validate.probe", fake_probe)

    def fake_render(video_path, ass_path, output_path):
        call_log.append(f"render:{output_path.name}")
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_bytes(b"burnedoutput")
        return output_path

    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)

    args = cli.parse_args([
        "https://www.bilibili.com/video/BV191DpBmE2t/",
        "-o", str(tmp_path / "output"),
        "-t", str(tmp_path / "temp"),
    ])
    result = cli.run(args)

    assert result == tmp_path / "output" / "BV191DpBmE2t_with_danmaku.mp4"
    assert result.exists()
    # Verify call order
    assert call_log[0] == "preflight"
    assert call_log[1] == "fetch:BV191DpBmE2t:1080:chrome"
    assert call_log[2] == "render:BV191DpBmE2t_with_danmaku.mp4"
    # Probe called twice: source then output
    assert len(probe_calls) == 2


def test_run_deletes_temp_files_on_success(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)

    def fake_fetch(url, temp_dir, quality, browser, bv_id):
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"v")
        a = temp_dir / f"{bv_id}.danmaku.ass"
        a.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")
        return v, a

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr(
        "video2yt.cli.validate.probe",
        lambda p: MediaInfo(
            duration=60.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1000,
        ),
    )

    def fake_render(v, a, o):
        o.parent.mkdir(parents=True, exist_ok=True)
        o.write_bytes(b"x")
        return o

    monkeypatch.setattr("video2yt.cli.burn.render", fake_render)

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
    ])
    cli.run(args)

    # Temp files gone
    assert not (tmp_path / "tmp" / "BV1.mp4").exists()
    assert not (tmp_path / "tmp" / "BV1.danmaku.ass").exists()


def test_run_keeps_temp_when_flag_set(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)

    def fake_fetch(url, temp_dir, quality, browser, bv_id):
        v = temp_dir / f"{bv_id}.mp4"
        v.write_bytes(b"v")
        a = temp_dir / f"{bv_id}.danmaku.ass"
        a.write_text("[Events]\nDialogue: 0,0,0,D,x\n", encoding="utf-8")
        return v, a

    monkeypatch.setattr("video2yt.cli.download.fetch", fake_fetch)
    monkeypatch.setattr(
        "video2yt.cli.validate.probe",
        lambda p: MediaInfo(
            duration=60.0, width=1920, height=1080,
            has_video=True, has_audio=True,
            vcodec="h264", acodec="aac", size_bytes=1000,
        ),
    )
    monkeypatch.setattr(
        "video2yt.cli.burn.render",
        lambda v, a, o: (o.parent.mkdir(parents=True, exist_ok=True), o.write_bytes(b"x"), o)[-1],
    )

    args = cli.parse_args([
        "https://x/video/BV1",
        "-o", str(tmp_path / "out"),
        "-t", str(tmp_path / "tmp"),
        "--keep-temp",
    ])
    cli.run(args)
    assert (tmp_path / "tmp" / "BV1.mp4").exists()
    assert (tmp_path / "tmp" / "BV1.danmaku.ass").exists()


def test_main_returns_1_on_value_error(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.cli.preflight", lambda: None)
    # Make extract_bv_id fail via non-bilibili URL
    rc = cli.main(["https://www.youtube.com/x"])
    assert rc == 1
    out = capsys.readouterr()
    assert "BV" in out.err or "error" in out.err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v -k "parse_args or run_ or main_"
```

Expected: FAIL with `AttributeError: module 'video2yt.cli' has no attribute 'parse_args'`.

- [ ] **Step 3: Implement**

Replace `src/video2yt/cli.py` with the full implementation:

```python
import argparse
import importlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import burn, download, validate

BV_PATTERN = re.compile(r"/video/(BV[A-Za-z0-9]+)")


def extract_bv_id(url: str) -> str:
    """Extract the BV id from a Bilibili video URL."""
    m = BV_PATTERN.search(url)
    if not m:
        raise ValueError(
            f"URL does not contain a BV id: {url!r}\n"
            f"expected format: https://www.bilibili.com/video/BV..."
        )
    return m.group(1)


def preflight() -> None:
    """Fail fast if required external dependencies are missing."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: brew install ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError(
            "ffprobe not found in PATH (usually ships with ffmpeg)"
        )
    try:
        mod = importlib.import_module("biliass")
        if mod is None:
            raise ImportError("biliass is None")
    except ImportError as e:
        raise RuntimeError(
            "yt-dlp-danmaku / biliass not available. Install with: "
            "uv add yt-dlp-danmaku"
        ) from e


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt",
        description="Download a Bilibili video and burn danmaku into the output MP4",
    )
    parser.add_argument("url", help="Bilibili video URL")
    parser.add_argument(
        "-o", "--output-dir", type=Path, default=Path("./output"),
        help="Directory for the final MP4 (default: ./output)",
    )
    parser.add_argument(
        "-t", "--temp-dir", type=Path, default=Path("./temp"),
        help="Directory for intermediate files (default: ./temp)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=1080, choices=[1080, 720, 480],
        help="Max video quality (default: 1080)",
    )
    parser.add_argument(
        "-b", "--browser", default="chrome",
        help="Browser to read cookies from (default: chrome)",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="Keep intermediate files after success",
    )
    return parser.parse_args(argv)


def _log(msg: str) -> None:
    print(f"[video2yt] {msg}", file=sys.stderr)


def run(args: argparse.Namespace) -> Path:
    preflight()
    bv_id = extract_bv_id(args.url)
    args.temp_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    _log(f"downloading {bv_id} (quality<={args.quality}, browser={args.browser})")
    video_path, ass_path = download.fetch(
        url=args.url,
        temp_dir=args.temp_dir,
        quality=args.quality,
        browser=args.browser,
        bv_id=bv_id,
    )

    _log("probing source video")
    source_info = validate.probe(video_path)
    for w in validate.check_source(source_info, args.quality):
        _log(f"warning: {w}")

    n_danmaku = validate.check_ass(ass_path)
    _log(f"detected {n_danmaku} danmaku lines")

    output_path = args.output_dir / f"{bv_id}_with_danmaku.mp4"
    _log(f"burning danmaku into {output_path.name}")
    burn.render(video_path, ass_path, output_path)

    _log("validating output")
    output_info = validate.probe(output_path)
    for w in validate.check_output(source_info, output_info):
        _log(f"warning: {w}")

    if not args.keep_temp:
        _log("cleaning up temp files")
        video_path.unlink(missing_ok=True)
        ass_path.unlink(missing_ok=True)

    return output_path


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        output_path = run(args)
        _log(f"success: {output_path}")
        return 0
    except KeyboardInterrupt:
        _log("cancelled; temp files kept for debugging")
        return 130
    except subprocess.CalledProcessError as e:
        tool = e.cmd[0] if e.cmd else "subprocess"
        _log(f"error: {tool} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        _log(f"error: {e}")
        return 1
```

- [ ] **Step 4: Run tests to verify they pass**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest tests/test_smoke.py -v
```

Expected: all 42 tests PASS. If the `test_main_returns_1_on_value_error` test fails because `preflight()` in `main()` runs before URL parsing, check that the order in `run()` is: `preflight()` → `extract_bv_id()`. The test mocks `preflight` to a no-op so `extract_bv_id` is what raises.

- [ ] **Step 5: Commit**

```bash
cd /Users/jun/code/video2yt
git add src/video2yt/cli.py tests/test_smoke.py
git commit -m "feat(cli): parse_args, run, main — full orchestration"
```

---

## Task 11: End-to-end sanity check (no network)

**Goal:** Verify the `video2yt` console script is wired correctly without hitting the network.

- [ ] **Step 1: Check the console script is registered**

Run:
```bash
cd /Users/jun/code/video2yt
uv run video2yt --help
```

Expected: argparse help text showing `url`, `-o`, `-t`, `-q`, `-b`, `--keep-temp`. Exit code 0.

- [ ] **Step 2: Check it fails cleanly on a bogus URL**

Run:
```bash
cd /Users/jun/code/video2yt
uv run video2yt "https://www.youtube.com/watch?v=abc" 2>&1
echo "exit=$?"
```

Expected: stderr shows "error: URL does not contain a BV id ..."; exit code 1.

- [ ] **Step 3: Check `python -m video2yt` also works**

Run:
```bash
cd /Users/jun/code/video2yt
uv run python -m video2yt --help
```

Expected: same help text as step 1.

- [ ] **Step 4: Run full test suite one more time**

Run:
```bash
cd /Users/jun/code/video2yt
uv run pytest -v
```

Expected: all 42 tests PASS, no warnings about deprecation in our code.

- [ ] **Step 5: Commit (only if anything changed)**

If any fixes were needed:
```bash
cd /Users/jun/code/video2yt
git add -A
git commit -m "fix: smoke wiring issues found during sanity check"
```

Otherwise skip this step.

---

## Task 12: Manual verification with real Bilibili URL

**Goal:** Confirm the whole pipeline works end-to-end on the test URL provided by the user.

**Test URL:** `https://www.bilibili.com/video/BV191DpBmE2t/`

**Prerequisite:** Chrome browser must be closed (or at least not holding the cookie DB lock).

- [ ] **Step 1: Close Chrome** (or make sure no tab holds the cookie DB lock)

- [ ] **Step 2: Run the tool**

Run:
```bash
cd /Users/jun/code/video2yt
uv run video2yt "https://www.bilibili.com/video/BV191DpBmE2t/" --keep-temp
```

Expected: over 1-5 minutes, you should see:
```
[video2yt] downloading BV191DpBmE2t (quality<=1080, browser=chrome)
[video2yt] probing source video
[video2yt] detected N danmaku lines
[video2yt] burning danmaku into BV191DpBmE2t_with_danmaku.mp4
[video2yt] validating output
[video2yt] success: output/BV191DpBmE2t_with_danmaku.mp4
```
Exit code 0.

**Troubleshooting if it fails:**
- "could not find cookies for chrome": Close Chrome fully (quit, don't just close windows).
- yt-dlp reports "403 Forbidden": yt-dlp is stale, run `uv lock --upgrade-package yt-dlp && uv sync`.
- "source resolution ... is lower than requested 1080p": cookies weren't loaded. Confirm Chrome is logged in to Bilibili.
- "ASS file has no Dialogue lines": video genuinely has no danmaku. Try a different BV.

- [ ] **Step 3: Inspect the output**

Run:
```bash
cd /Users/jun/code/video2yt
ls -lh output/
ffprobe -v error -show_format -show_streams output/BV191DpBmE2t_with_danmaku.mp4 | head -40
```

Expected:
- File size > 1 MB
- `width=1920 height=1080` (or at least matching the source)
- `codec_name=h264`
- `codec_name=aac` (audio)
- `duration=` close to original video length

- [ ] **Step 4: Play it visually**

Run:
```bash
open output/BV191DpBmE2t_with_danmaku.mp4
```

Expected: QuickTime opens the file, video plays with Chinese danmaku text scrolling across the top half of the frame. Audio works. No subtitle picker needed (because the subtitle is burned into the picture).

- [ ] **Step 5: Clean up and re-run without `--keep-temp`**

Run:
```bash
cd /Users/jun/code/video2yt
rm -rf temp/ output/
uv run video2yt "https://www.bilibili.com/video/BV191DpBmE2t/"
ls temp/ 2>&1 || echo "temp/ not present, as expected"
ls output/
```

Expected: `temp/` is empty or missing after success; `output/BV191DpBmE2t_with_danmaku.mp4` exists.

- [ ] **Step 6: Commit any usage learnings**

If you discovered anything worth writing down (specific error messages, extra troubleshooting steps), add them to `CLAUDE.md` under "Known gotchas" or create a brief `docs/usage.md`, then:

```bash
cd /Users/jun/code/video2yt
git add CLAUDE.md docs/
git commit -m "docs: record manual verification findings"
```

If nothing new surfaced, skip this step.

- [ ] **Step 7: Final tag**

```bash
cd /Users/jun/code/video2yt
git tag v0.1.0-mvp
```

---

## Done

At this point the MVP from `docs/2026-04-11-video2yt-design.md` §1.2 is complete:

- [x] Single-link input → single MP4 output
- [x] Configurable output / temp / quality / browser
- [x] `--keep-temp` flag
- [x] Chrome cookie login for 1080p
- [x] Download + ASS + burn pipeline
- [x] Input + ASS + output validation (duration, resolution, streams, codec, size)
- [x] 42 passing tests (all mocked, fast)
- [x] Manually verified on `BV191DpBmE2t`

Everything outside §1.2 (batch, multi-P, retry, style customization, etc.) is explicitly out of scope per the spec.

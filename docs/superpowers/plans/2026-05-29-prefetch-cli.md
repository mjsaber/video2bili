# video2yt-prefetch CLI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `video2yt-prefetch <url>...` CLI that serially pre-downloads Bilibili sources into the same Stage 1 fetch cache Step 6 uses, so the slow yt-dlp download overlaps the bandwidth-free Step 1–5 intro work.

**Architecture:** A thin orchestration CLI (`prefetch_cli.py`) that loops over URLs serially, calling the existing `fetch.fetch_and_build` per URL. Truncation auto-retries up to 3 attempts (re-calling `fetch_and_build`, whose internal cache-quarantine re-downloads). Resolution below the requested quality fail-fasts and quarantines the bad cached files with a `.lowres` suffix so Step 6 won't serve them. Any URL failure fail-fasts the whole batch. The only existing-code change is a backward-compatible `TruncatedDownloadError(RuntimeError)` subclass in `download.py`.

**Tech Stack:** Python 3, `uv`, `argparse`, pytest with `monkeypatch` (all external tools mocked at the `fetch.fetch_and_build` / `subprocess.run` seam — no network).

**Spec:** `docs/superpowers/specs/2026-05-29-prefetch-cli-design.md`
**Branch:** `prefetch-workflow` (already checked out)

---

## File Structure

- **Create** `src/video2yt/prefetch_cli.py` — the `video2yt-prefetch` entry point: `preflight` (reused) / `parse_args` / `_quarantine_lowres` / `_prefetch_one` / `run` / `main`. Single responsibility: serial orchestration over `fetch.fetch_and_build`.
- **Modify** `src/video2yt/download.py` — add `TruncatedDownloadError(RuntimeError)`; retarget the one fresh-download truncation `raise` (currently line ~167) to it. Backward compatible (subclass of `RuntimeError`).
- **Modify** `pyproject.toml` — register `video2yt-prefetch = "video2yt.prefetch_cli:main"` in `[project.scripts]`.
- **Create** `tests/test_prefetch.py` — orchestration tests, mocking `video2yt.fetch.fetch_and_build`.
- **Modify** `tests/test_smoke.py` — one tiny test asserting `TruncatedDownloadError` is a `RuntimeError` subclass (the existing `test_fetch_raises_when_fresh_download_has_truncated_audio` already proves the `match="truncated audio"` behavior survives).
- **Modify** `CLAUDE.md` — Commands + Architecture sections.
- **Modify** `docs/superpowers/specs/2026-04-18-video-production-workflow.md` — Step 1 prefetch note.
- **Delete** `docs/prefetch-workflow-brief.md` — superseded by the spec.

**Design note (why no `_cleanup_partials`):** On a fresh-download truncation, `download.fetch` leaves the truncated `<bv>.mp4` in place and raises. The *next* `fetch_and_build` call's cache probe sees the file, finds it AV-inconsistent, renames it to `.broken`, and re-downloads (verified in `download.py:119-128` + existing test `test_fetch_quarantines_truncated_audio_cache_and_redownloads`). So a retry is simply "call `fetch_and_build` again" — no explicit partial cleanup is needed. The spec's speculative `_cleanup_partials` is dropped (YAGNI).

---

### Task 1: `TruncatedDownloadError` subclass in download.py

**Files:**
- Modify: `src/video2yt/download.py` (add class near top; retarget the raise at ~line 167)
- Test: `tests/test_smoke.py` (one new test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_smoke.py` (near the other `download.fetch` truncation tests, ~line 456):

```python
def test_truncated_download_error_is_runtime_error():
    """TruncatedDownloadError must subclass RuntimeError so existing
    `except RuntimeError` callers (fetch_cli.main) keep working unchanged."""
    from video2yt.download import TruncatedDownloadError
    assert issubclass(TruncatedDownloadError, RuntimeError)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py::test_truncated_download_error_is_runtime_error -v`
Expected: FAIL with `ImportError: cannot import name 'TruncatedDownloadError'`

- [ ] **Step 3: Implement the subclass and retarget the raise**

In `src/video2yt/download.py`, add the class just above `def get_metadata` (after the imports):

```python
class TruncatedDownloadError(RuntimeError):
    """yt-dlp merger hiccup: a fresh download's video/audio stream
    durations disagree (BV1UodgBJEXj-style). Subclass of RuntimeError so
    existing `except RuntimeError` callers are unaffected; a dedicated type
    lets video2yt-prefetch distinguish retryable truncation from other
    failures.
    """
```

Then change the fresh-download truncation raise (currently `raise RuntimeError(` at ~line 167) to:

```python
    if not _is_av_duration_consistent(video_path):
        v_dur, a_dur = _stream_durations(video_path)
        raise TruncatedDownloadError(
            f"yt-dlp produced {video_path.name} with truncated audio "
            f"(video {v_dur:.1f}s vs audio {a_dur:.1f}s). This is the "
            f"BV1UodgBJEXj-style merger hiccup — re-run to download again, "
            f"or run yt-dlp manually to inspect."
        )
```

(Only the exception type changes; the message is identical.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py::test_truncated_download_error_is_runtime_error tests/test_smoke.py::test_fetch_raises_when_fresh_download_has_truncated_audio -v`
Expected: BOTH PASS (the second is the pre-existing `match="truncated audio"` test — proves backward compatibility).

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/download.py tests/test_smoke.py
git commit -m "feat(download): add TruncatedDownloadError(RuntimeError) subclass

Lets video2yt-prefetch distinguish retryable yt-dlp merger-hiccup
truncation from other failures. Backward compatible: existing
except RuntimeError callers (fetch_cli.main) are unaffected."
```

---

### Task 2: prefetch_cli skeleton + script registration

**Files:**
- Create: `src/video2yt/prefetch_cli.py`
- Modify: `pyproject.toml` (`[project.scripts]`)
- Test: `tests/test_prefetch.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_prefetch.py`:

```python
"""Tests for video2yt-prefetch (serial Stage 1 cache pre-download).

All external work is mocked at the video2yt.fetch.fetch_and_build seam —
no network, no real subprocess.
"""
from video2yt import fetch, prefetch_cli, validate
from video2yt.download import TruncatedDownloadError


def _make_result(tmp_path, bv="BV1", width=1920, height=1080,
                 from_cache=False, write_files=False):
    """Build a FetchResult pointing at files under a per-segment subdir.

    write_files=True actually creates the mp4 + xml on disk so quarantine
    behavior can be asserted.
    """
    sub = tmp_path / "uploader：title"
    sub.mkdir(parents=True, exist_ok=True)
    mp4 = sub / f"{bv}.mp4"
    xml = sub / f"{bv}.danmaku.xml"
    if write_files:
        mp4.write_bytes(b"v")
        xml.write_bytes(b"<i></i>")
    return fetch.FetchResult(
        bv_id=bv, raw_video=mp4, danmaku_xml=xml,
        danmaku_ass=sub / f"{bv}.danmaku.ass",
        metadata={"title": "some title"},
        info=validate.MediaInfo(
            duration=100.0, width=width, height=height,
            has_video=True, has_audio=True, vcodec="h264",
            acodec="aac", size_bytes=1,
        ),
        from_cache=from_cache, n_danmaku=3, temp_subdir=sub, elapsed=1.0,
    )


def test_parse_args_accepts_multiple_urls():
    args = prefetch_cli.parse_args(["u/BV1", "u/BV2", "-o", "/tmp/x", "-q", "720"])
    assert args.urls == ["u/BV1", "u/BV2"]
    assert args.quality == 720
    assert str(args.temp_dir) == "/tmp/x"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_prefetch.py::test_parse_args_accepts_multiple_urls -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'video2yt.prefetch_cli'`

- [ ] **Step 3: Create the skeleton**

Create `src/video2yt/prefetch_cli.py`:

```python
"""``video2yt-prefetch`` — serial pre-download of Stage 1 sources.

Fills the same Stage 1 fetch cache that ``video2yt-fetch`` / Step 6 use,
ahead of time, so the bandwidth-heavy yt-dlp download overlaps the
bandwidth-free Step 1–5 intro work. Serial by design — parallel downloads
trigger yt-dlp merger-hiccup truncation. See
docs/superpowers/specs/2026-05-29-prefetch-cli-design.md.
"""

import argparse
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from video2yt import fetch
from video2yt.download import TruncatedDownloadError
from video2yt.fetch_cli import preflight

MAX_ATTEMPTS = 3


def _log(msg: str) -> None:
    print(f"[video2yt-prefetch] {msg}", file=sys.stderr)


class PrefetchResolutionError(RuntimeError):
    """Downloaded source resolution is below the requested quality floor."""


@dataclass
class PrefetchOutcome:
    url: str
    bv_id: str
    title: str
    width: int
    height: int
    from_cache: bool
    elapsed: float


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-prefetch",
        description=(
            "Serially pre-download one or more Bilibili sources into the "
            "Stage 1 fetch cache (mp4 + danmaku XML), so Step 6 hits a warm "
            "cache. Serial by design — parallel downloads trigger yt-dlp "
            "merger-hiccup truncation. Background it with a trailing '&'."
        ),
    )
    parser.add_argument("urls", nargs="+", help="One or more Bilibili video URLs")
    parser.add_argument(
        "-o", "--temp-dir", type=Path, default=Path("./temp"),
        help="Parent temp directory; per-segment subfolders created inside (default: ./temp)",
    )
    parser.add_argument(
        "-q", "--quality", type=int, default=1080, choices=[1080, 720, 480],
        help="Max video quality; sources below this fail-fast (default: 1080)",
    )
    parser.add_argument(
        "--codec", default="h264", choices=["h264", "h265", "auto"],
        help="Video codec preference (default: h264)",
    )
    parser.add_argument(
        "-b", "--browser", default="chrome",
        help="Browser to read cookies from (default: chrome)",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
    except KeyboardInterrupt:
        _log("cancelled")
        return 130
    except subprocess.CalledProcessError as e:
        tool = e.cmd[0] if e.cmd else "subprocess"
        _log(f"error: {tool} failed with exit {e.returncode}")
        if e.stderr:
            print(e.stderr, file=sys.stderr)
        return 1
    except (ValueError, FileNotFoundError, RuntimeError) as e:
        # fail-fast: PrefetchResolutionError + TruncatedDownloadError are RuntimeError
        _log(f"error: {e}")
        return 1
```

Note: `run`, `_prefetch_one`, and `_quarantine_lowres` are added in Tasks 3–5. This step leaves `run` undefined on purpose — Task 2's test only exercises `parse_args`.

Register the script in `pyproject.toml` `[project.scripts]`, alphabetically between `video2yt-music-mix` and `video2yt-research-card`:

```toml
video2yt-prefetch = "video2yt.prefetch_cli:main"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_prefetch.py::test_parse_args_accepts_multiple_urls -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/prefetch_cli.py pyproject.toml tests/test_prefetch.py
git commit -m "feat(prefetch): scaffold video2yt-prefetch CLI (parse_args + main)"
```

---

### Task 3: Single-URL success path (`run` + `_prefetch_one`)

**Files:**
- Modify: `src/video2yt/prefetch_cli.py` (add `_prefetch_one`, `run`)
- Test: `tests/test_prefetch.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prefetch.py`:

```python
def test_single_url_success(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.fetch.fetch_and_build",
        lambda **kw: _make_result(tmp_path),
    )
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 0


def test_cache_hit_reported(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.fetch.fetch_and_build",
        lambda **kw: _make_result(tmp_path, from_cache=True),
    )
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 0
    assert "cached" in capsys.readouterr().err
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prefetch.py::test_single_url_success -v`
Expected: FAIL with `AttributeError: module 'video2yt.prefetch_cli' has no attribute 'run'`

- [ ] **Step 3: Implement `_prefetch_one` and `run`**

Add to `src/video2yt/prefetch_cli.py` (above `main`):

```python
def _prefetch_one(
    url: str, temp_dir: Path, quality: int, codec: str, browser: str
) -> PrefetchOutcome:
    """Prefetch a single URL into the Stage 1 cache. Raises on failure."""
    result = fetch.fetch_and_build(
        url=url, temp_dir=temp_dir, quality=quality,
        codec=codec, browser=browser,
    )
    return PrefetchOutcome(
        url=url,
        bv_id=result.bv_id,
        title=result.metadata.get("title") or result.bv_id,
        width=result.info.width,
        height=result.info.height,
        from_cache=result.from_cache,
        elapsed=result.elapsed,
    )


def run(args: argparse.Namespace) -> list[PrefetchOutcome]:
    preflight()
    done: list[PrefetchOutcome] = []
    for url in args.urls:
        _log(f"prefetching {url}")
        outcome = _prefetch_one(
            url, args.temp_dir, args.quality, args.codec, args.browser
        )
        tag = "cached" if outcome.from_cache else "downloaded"
        _log(
            f"  ok bv={outcome.bv_id} {outcome.width}x{outcome.height} "
            f"{tag} ({outcome.elapsed:.1f}s) {outcome.title!r}"
        )
        done.append(outcome)
    _log(f"summary: {len(done)}/{len(args.urls)} prefetched")
    return done
```

(Retry and resolution-check logic land in Tasks 4–5; this version is the happy path only.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prefetch.py -v`
Expected: PASS (all three tests so far)

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/prefetch_cli.py tests/test_prefetch.py
git commit -m "feat(prefetch): serial single-URL run + outcome summary"
```

---

### Task 4: Truncation auto-retry (3 attempts, then fail-fast)

**Files:**
- Modify: `src/video2yt/prefetch_cli.py` (`_prefetch_one` retry loop)
- Test: `tests/test_prefetch.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prefetch.py`:

```python
def test_truncation_retries_then_succeeds(tmp_path, monkeypatch):
    calls = {"n": 0}

    def fab(**kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise TruncatedDownloadError("truncated audio")
        return _make_result(tmp_path)

    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", fab)
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 0
    assert calls["n"] == 2  # one retry


def test_truncation_exhausts_retries_fail_fast(tmp_path, monkeypatch, capsys):
    calls = {"n": 0}

    def fab(**kw):
        calls["n"] += 1
        raise TruncatedDownloadError("truncated audio")

    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", fab)
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path)])
    assert rc == 1
    assert calls["n"] == prefetch_cli.MAX_ATTEMPTS  # 3 attempts, no more
    assert "truncated" in capsys.readouterr().err.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prefetch.py::test_truncation_retries_then_succeeds -v`
Expected: FAIL — the current `_prefetch_one` calls `fetch_and_build` once and lets `TruncatedDownloadError` propagate (exit 1, `calls["n"] == 1`).

- [ ] **Step 3: Add the retry loop**

Replace `_prefetch_one` in `src/video2yt/prefetch_cli.py` with:

```python
def _prefetch_one(
    url: str, temp_dir: Path, quality: int, codec: str, browser: str
) -> PrefetchOutcome:
    """Prefetch a single URL into the Stage 1 cache. Raises on failure.

    Truncated yt-dlp merges (TruncatedDownloadError) are retried up to
    MAX_ATTEMPTS — re-calling fetch_and_build re-downloads, because
    download.fetch's cache probe quarantines the prior truncated file to
    .broken and falls through to a fresh yt-dlp run.
    """
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            result = fetch.fetch_and_build(
                url=url, temp_dir=temp_dir, quality=quality,
                codec=codec, browser=browser,
            )
        except TruncatedDownloadError:
            if attempt == MAX_ATTEMPTS:
                raise
            _log(f"  truncated merge, retry {attempt + 1}/{MAX_ATTEMPTS}")
            continue
        return PrefetchOutcome(
            url=url,
            bv_id=result.bv_id,
            title=result.metadata.get("title") or result.bv_id,
            width=result.info.width,
            height=result.info.height,
            from_cache=result.from_cache,
            elapsed=result.elapsed,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prefetch.py -v`
Expected: PASS (all five tests)

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/prefetch_cli.py tests/test_prefetch.py
git commit -m "feat(prefetch): auto-retry truncated yt-dlp merges (3 attempts)"
```

---

### Task 5: Resolution precheck + `.lowres` cache quarantine

**Files:**
- Modify: `src/video2yt/prefetch_cli.py` (`_quarantine_lowres`, resolution check in `_prefetch_one`)
- Test: `tests/test_prefetch.py`

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_prefetch.py`:

```python
def test_low_resolution_fails_fast(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr(
        "video2yt.fetch.fetch_and_build",
        lambda **kw: _make_result(tmp_path, width=854, height=480, write_files=True),
    )
    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path), "-q", "1080"])
    assert rc == 1
    assert "480" in capsys.readouterr().err


def test_low_resolution_quarantines_cache(tmp_path, monkeypatch):
    """The bad low-res files must be renamed past download.fetch's cache
    probe globs so a later Step 6 run re-downloads instead of cache-hitting."""
    result = _make_result(tmp_path, bv="BV1", width=854, height=480, write_files=True)
    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", lambda **kw: result)

    rc = prefetch_cli.main(["https://x/video/BV1", "-o", str(tmp_path), "-q", "1080"])
    assert rc == 1
    # original cache files gone, quarantined copies present
    assert not result.raw_video.exists()
    assert (result.temp_subdir / "BV1.mp4.lowres").exists()
    assert not result.danmaku_xml.exists()
    assert (result.temp_subdir / "BV1.danmaku.xml.lowres").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_prefetch.py::test_low_resolution_fails_fast tests/test_prefetch.py::test_low_resolution_quarantines_cache -v`
Expected: FAIL — current code returns the low-res result as success (rc 0, files untouched).

- [ ] **Step 3: Add quarantine + resolution check**

Add `_quarantine_lowres` to `src/video2yt/prefetch_cli.py` (above `_prefetch_one`):

```python
def _quarantine_lowres(result: fetch.FetchResult) -> None:
    """Rename the cached low-res video + danmaku XML with a `.lowres` suffix.

    fetch_and_build writes the files to the shared Stage 1 cache before
    returning, so a bare fail-fast would leave a complete, AV-consistent
    low-res file that download.fetch's cache probe (`<bv>.mp4`, `<bv>*.xml`)
    would silently serve to Step 6 until merge fails. Renaming past those
    globs forces a re-download. Mirrors download.fetch's `.broken` quarantine.
    """
    for path in (result.raw_video, result.danmaku_xml):
        if path.exists():
            path.rename(path.with_name(path.name + ".lowres"))
```

Then add the resolution check inside `_prefetch_one`, immediately after the successful `fetch_and_build` (before building `PrefetchOutcome`):

```python
        if result.info.height < quality:
            _quarantine_lowres(result)
            raise PrefetchResolutionError(
                f"{result.bv_id}: got {result.info.width}x{result.info.height}, "
                f"requested <={quality}p (VIP-locked source? merge needs "
                f"1920x1080). Quarantined cached files to *.lowres; re-run "
                f"after fixing the source."
            )
        return PrefetchOutcome(
            url=url,
            bv_id=result.bv_id,
            title=result.metadata.get("title") or result.bv_id,
            width=result.info.width,
            height=result.info.height,
            from_cache=result.from_cache,
            elapsed=result.elapsed,
        )
```

(Replace the existing bare `return PrefetchOutcome(...)` with the guarded version above.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_prefetch.py -v`
Expected: PASS (all seven tests)

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/prefetch_cli.py tests/test_prefetch.py
git commit -m "feat(prefetch): fail-fast on low resolution + quarantine bad cache

Renames sub-quality cached mp4+xml to *.lowres before raising, so
download.fetch's cache probe no longer matches and Step 6 re-downloads
instead of silently serving a low-res file that blows up at merge."
```

---

### Task 6: Multi-URL serial fail-fast

**Files:**
- Test: `tests/test_prefetch.py` (behavior already implemented by `run`'s loop + propagating raise; this task adds the regression test)

- [ ] **Step 1: Write the failing test**

Add to `tests/test_prefetch.py`:

```python
def test_multi_url_fail_fast_stops_remaining(tmp_path, monkeypatch):
    """A failure on URL 2 must stop the batch — URL 3 is never attempted."""
    seen = []

    def fab(*, url, **kw):
        seen.append(url)
        if url.endswith("BV2"):
            raise FileNotFoundError("yt-dlp produced no video file")
        return _make_result(tmp_path, bv="BV1")

    monkeypatch.setattr("video2yt.prefetch_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.fetch.fetch_and_build", fab)
    rc = prefetch_cli.main(["u/BV1", "u/BV2", "u/BV3", "-o", str(tmp_path)])
    assert rc == 1
    assert seen == ["u/BV1", "u/BV2"]  # BV3 never attempted
```

- [ ] **Step 2: Run test to verify the behavior**

Run: `uv run pytest tests/test_prefetch.py::test_multi_url_fail_fast_stops_remaining -v`
Expected: PASS immediately — `run`'s loop propagates the `FileNotFoundError` from URL 2, `main` catches it (exit 1), and the loop never reaches URL 3. (This task is a regression guard; if it fails, the loop is swallowing errors and must be fixed to let them propagate.)

- [ ] **Step 3: Commit**

```bash
git add tests/test_prefetch.py
git commit -m "test(prefetch): lock multi-URL fail-fast (stop on first failure)"
```

---

### Task 7: Full suite + CLI smoke

**Files:** none (verification only)

- [ ] **Step 1: Sync so the new entry point is installed**

Run: `uv sync`
Expected: completes; `video2yt-prefetch` now on the venv's path.

- [ ] **Step 2: CLI help smoke**

Run: `uv run video2yt-prefetch --help`
Expected: usage text listing positional `urls` and `-o/-q/--codec/-b`.

- [ ] **Step 3: Run the full test suite**

Run: `uv run pytest -q`
Expected: all tests PASS (prior count + the 8 new prefetch/download tests). No failures, no warnings introduced.

- [ ] **Step 4: Commit (only if anything changed, e.g. uv.lock)**

```bash
git add -A
git commit -m "chore(prefetch): uv sync to register video2yt-prefetch entry point" || echo "nothing to commit"
```

---

### Task 8: Docs

**Files:**
- Modify: `CLAUDE.md` (Commands + Architecture)
- Modify: `docs/superpowers/specs/2026-04-18-video-production-workflow.md` (Step 1 note)
- Delete: `docs/prefetch-workflow-brief.md`

- [ ] **Step 1: CLAUDE.md Commands section**

In the ```` ```bash ```` Commands block, add after the `video2yt-fetch` line:

```bash
uv run video2yt-prefetch "<url1>" "<url2>" -o temp/ &                  # background serial pre-download of Step 6 sources
```

- [ ] **Step 2: CLAUDE.md Architecture section**

In the `src/video2yt/` tree, add after the `fetch_cli.py` line:

```
├── prefetch_cli.py   # video2yt-prefetch: serial pre-download of N sources into the
│                     #   Stage 1 cache (truncation retry + low-res quarantine + fail-fast)
```

- [ ] **Step 3: Workflow spec Step 1 note**

In `docs/superpowers/specs/2026-04-18-video-production-workflow.md`, find the Step 1 section and add a note that the user can kick off `uv run video2yt-prefetch "<url1>" "<url2>" -o temp/ &` at the start of Step 1 so the Step 6 sources download in the background during the bandwidth-free intro work. (Match the surrounding spec's formatting; keep it to 1–2 sentences.) **Important — `-o temp/`, NOT `output/<project>/`**: prefetch's `-o` is the temp dir (mirrors `video2yt-fetch`). Step 6 (`video2yt`) reads its Stage 1 cache from `--temp-dir` (default `./temp`), while `-o output/<project>/` on `video2yt` is the *final-MP4* output dir. Pointing prefetch at the project output folder writes the cache where Step 6 never looks → cache miss → re-download. The note must say to target the same temp dir Step 6 fetches into.

- [ ] **Step 4: Delete the superseded brief**

```bash
git rm docs/prefetch-workflow-brief.md
```

- [ ] **Step 5: Verify nothing references the deleted brief**

Run: `rg -l "prefetch-workflow-brief" --glob '!docs/superpowers/plans/2026-05-29-prefetch-cli.md'`
Expected: no output (the design spec references it; if the spec links it, that link is fine — it's historical context. Only fix dangling links that would 404 in active docs.)

- [ ] **Step 6: Commit**

```bash
git add CLAUDE.md docs/superpowers/specs/2026-04-18-video-production-workflow.md
git commit -m "docs: document video2yt-prefetch; remove superseded brief"
```

---

## Self-Review

**Spec coverage:**
- 串行预取多 URL → Task 3 (`run` loop) + Task 6 (fail-fast test). ✅
- 截断自动重试 3 次 → Task 4. ✅
- 重试机制（无需 _cleanup_partials）→ documented in File Structure note + Task 4 docstring. ✅
- 分辨率不足 fail-fast → Task 5. ✅
- 低分辨率隔离坏缓存（.lowres，no-poison）→ Task 5 (`_quarantine_lowres` + dedicated test). ✅
- 多 URL fail-fast（第二个失败第三个不碰）→ Task 6. ✅
- `TruncatedDownloadError(RuntimeError)` 唯一侵入 download.py，向后兼容 → Task 1 (subclass test + existing-test re-run). ✅
- 缓存命中秒回 → Task 3 (`test_cache_hit_reported`). ✅
- CLI 形状 / 退出码 0/1/130 → Task 2 (`main`) + Task 5/4 (exit 1 paths). ✅
- pyproject script 注册 → Task 2. ✅
- 镜像 fetch 参数面（-o/-q/--codec/-b），省略字体 → Task 2 `parse_args`. ✅
- 测试矩阵 8 条 → Tasks 1,3,4,5,6 (1 subclass + 7 prefetch). ✅
- 文档 + 删 brief → Task 8. ✅

**Placeholder scan:** No TBD/TODO; every code step shows full code; every command shows expected output. ✅

**Type consistency:** `PrefetchOutcome` fields (url/bv_id/title/width/height/from_cache/elapsed) consistent across Tasks 3–5. `_prefetch_one(url, temp_dir, quality, codec, browser)` signature stable Tasks 3→4→5. `_quarantine_lowres(result)` matches its one call site. `MAX_ATTEMPTS` referenced in test (Task 4) matches the module constant (Task 2). `FetchResult` / `MediaInfo` constructor args in `_make_result` match the real dataclasses — `FetchResult`: `bv_id, raw_video, danmaku_xml, danmaku_ass, metadata, info, from_cache, n_danmaku, temp_subdir, elapsed`; `MediaInfo` (8 fields, all required, no defaults): `duration, width, height, has_video, has_audio, vcodec, acodec, size_bytes`. ✅ (Corrected post-Task-2: an earlier draft of this helper omitted the last 5 `MediaInfo` fields — caught in Task 2 review.)

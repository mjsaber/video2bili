# video2yt-music-swap Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `video2yt-music-swap` CLI that isolates the streamer's commentary voice from a burnt Bilibili segment, discards the original music+SFX mix, and lays a stitched CC0 royalty-free music bed underneath — producing an MP4 with the copyrighted background music suppressed.

**Architecture:** Three new modules. `music_library.py` owns the CC0 track manifest, the download/verify cache, and track-pool selection. `music_swap.py` owns the audio pipeline (extract → Demucs vocal isolation → stitch music bed → mix with ducking → remux). `music_swap_cli.py` is the entry point (`preflight`/`parse_args`/`run`/`main`), mirroring `compose_cli.py`. Everything that touches `ffmpeg`/`ffprobe`/`demucs` shells out via `subprocess.run`, so tests mock that one boundary.

**Tech Stack:** Python 3.10+, `demucs` (PyTorch source separation, run as a subprocess), `ffmpeg`/`ffprobe` (system), `requests` (already a dep, for track downloads), `pytest`.

---

## Spec reference

Approved spec: `docs/superpowers/specs/2026-05-20-music-swap-design.md`. Read it before starting.

## Conventions in this codebase (read first)

- Tests all live in the single file `tests/test_smoke.py`. Append new tests there.
- Every external tool is invoked through `subprocess.run`; tests `monkeypatch` it at the module boundary (e.g. `monkeypatch.setattr("video2yt.music_swap.subprocess.run", fake_run)`). No real ffmpeg/demucs/network in tests.
- CLI modules expose `preflight()`, `parse_args(argv)`, `run(args)`, `main(argv)` and a module-level `_log(msg)` helper that prints `[video2yt-music-swap] ...` to stderr. See `src/video2yt/compose_cli.py`.
- `validate.probe(path) -> MediaInfo` (in `src/video2yt/validate.py`) is the shared ffprobe wrapper. `MediaInfo` has `.duration .width .height .has_video .has_audio .vcodec .acodec .size_bytes`. Reuse it; do not write a new probe.
- Run all commands with `uv run` (e.g. `uv run pytest`). Never hand-edit dependency entries in `pyproject.toml`; use `uv add`.

## File Structure

| File | Responsibility |
|---|---|
| `src/video2yt/music_library.py` (create) | Manifest parsing, sha256-verified download cache, audio-file scan + duration probe, track-sequence selection. |
| `src/video2yt/music_swap.py` (create) | Audio pipeline: `extract_audio`, `separate_vocals`, `build_music_bed`, `mix`, `remux`, `render` orchestration + output validation. `MusicSwapInputs` dataclass. |
| `src/video2yt/music_swap_cli.py` (create) | `video2yt-music-swap` entry point: `preflight`, `parse_args`, `run`, `main`. |
| `src/video2yt/data/music_library.json` (create) | Committed CC0 track manifest. Ships empty initially; seeded in Task 13. |
| `tests/test_smoke.py` (modify) | Append all new tests. |
| `pyproject.toml` (modify) | Add `demucs` dep (via `uv add`), the `video2yt-music-swap` script entry, and a `force-include` for the manifest JSON. |
| `docs/superpowers/specs/2026-04-18-video-production-workflow.md` (modify) | Add Step 6.5, renumber subtitle to 6.6. |
| `CLAUDE.md` (modify) | Commands, architecture map, feature flags, gotchas. |

---

## Task 1: Project plumbing — dependency, entry point, empty manifest

**Files:**
- Modify: `pyproject.toml`
- Create: `src/video2yt/data/music_library.json`

- [x] **Step 1: Add the Demucs dependency**

Run: `uv add demucs`

Expected: `pyproject.toml` `dependencies` gains a `demucs>=...` line and `uv.lock` updates. (Demucs pulls in PyTorch; whisperx already does, so this is consistent.)

- [x] **Step 2: Create the empty manifest file**

Create `src/video2yt/data/music_library.json` with exactly:

```json
{
  "tracks": []
}
```

The manifest ships empty; real CC0 tracks are seeded in Task 13. An empty manifest is valid (per spec §6 the cache dir is the source of truth).

- [x] **Step 3: Register the console script**

In `pyproject.toml`, under `[project.scripts]`, add this line after the `video2yt-subtitle` line:

```toml
video2yt-music-swap = "video2yt.music_swap_cli:main"
```

- [x] **Step 4: Force-include the manifest in the wheel**

In `pyproject.toml`, under `[tool.hatch.build.targets.wheel.force-include]`, add after the `bg_glossary.yaml` line:

```toml
"src/video2yt/data/music_library.json" = "video2yt/data/music_library.json"
```

- [x] **Step 5: Verify the package still imports**

Run: `uv run python -c "import video2yt"`
Expected: no output, exit 0.

- [x] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock src/video2yt/data/music_library.json
git commit -m "chore: add demucs dep + music-swap entry point + empty manifest"
```

---

## Task 2: `music_library.load_manifest`

**Files:**
- Create: `src/video2yt/music_library.py`
- Test: `tests/test_smoke.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
from video2yt import music_library


def test_load_manifest_parses_tracks(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text(
        '{"tracks": [{"name": "a", "url": "http://x/a.mp3", '
        '"sha256": "ab", "duration": 120.0, "license": "CC0"}]}',
        encoding="utf-8",
    )
    tracks = music_library.load_manifest(manifest)
    assert len(tracks) == 1
    assert tracks[0]["name"] == "a"


def test_load_manifest_empty_is_ok(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text('{"tracks": []}', encoding="utf-8")
    assert music_library.load_manifest(manifest) == []


def test_load_manifest_malformed_raises(tmp_path):
    manifest = tmp_path / "m.json"
    manifest.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError):
        music_library.load_manifest(manifest)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k load_manifest -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'video2yt.music_library'`.

- [x] **Step 3: Create the module with `load_manifest`**

Create `src/video2yt/music_library.py`:

```python
"""CC0 royalty-free music library: manifest, download cache, track selection.

The cache directory ``~/.cache/video2yt/music/`` is the source of truth — the
music bed is built from every audio file present there. The committed manifest
(``data/music_library.json``) is an auto-fill convenience that downloads
redistributable CC0 tracks into the cache on first use. Users may also drop
their own tracks into the cache directory by hand.
"""
from __future__ import annotations

import hashlib
import json
import random
import sys
from dataclasses import dataclass
from pathlib import Path

import requests

MANIFEST_PATH = Path(__file__).parent / "data" / "music_library.json"
CACHE_DIR = Path.home() / ".cache" / "video2yt" / "music"
AUDIO_EXTENSIONS = {".mp3", ".m4a", ".wav", ".flac", ".ogg", ".opus"}


def _log(msg: str) -> None:
    print(f"[music_library] {msg}", file=sys.stderr)


def load_manifest(manifest_path: Path | None = None) -> list[dict]:
    """Parse the committed manifest JSON and return its ``tracks`` list.

    Raises ``ValueError`` if the file is missing or not valid JSON, or if the
    top-level ``tracks`` key is absent.
    """
    path = manifest_path if manifest_path is not None else MANIFEST_PATH
    if not path.exists():
        raise ValueError(f"music manifest not found: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise ValueError(f"music manifest is not valid JSON: {path}: {e}") from e
    if not isinstance(data, dict) or "tracks" not in data:
        raise ValueError(f"music manifest missing 'tracks' key: {path}")
    return list(data["tracks"])
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k load_manifest -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add src/video2yt/music_library.py tests/test_smoke.py
git commit -m "feat(music_library): add load_manifest"
```

---

## Task 3: `music_library.ensure_manifest_cached` (download + verify + skip-on-failure)

**Files:**
- Modify: `src/video2yt/music_library.py`
- Test: `tests/test_smoke.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def test_ensure_manifest_cached_downloads_missing(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    payload = b"FAKEAUDIO"
    sha = hashlib.sha256(payload).hexdigest()

    def fake_get(url, timeout=0):
        resp = MagicMock()
        resp.content = payload
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr("video2yt.music_library.requests.get", fake_get)
    manifest = [{"name": "song1", "url": "http://x/s1.mp3",
                 "sha256": sha, "duration": 90.0, "license": "CC0"}]
    music_library.ensure_manifest_cached(manifest, cache)
    assert (cache / "song1.mp3").read_bytes() == payload


def test_ensure_manifest_cached_skips_cache_hit(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "song1.mp3").write_bytes(b"already here")
    called = []
    monkeypatch.setattr("video2yt.music_library.requests.get",
                        lambda *a, **k: called.append(1))
    manifest = [{"name": "song1", "url": "http://x/s1.mp3",
                 "sha256": "whatever", "duration": 90.0, "license": "CC0"}]
    music_library.ensure_manifest_cached(manifest, cache)
    assert called == []  # cache hit -> no download


def test_ensure_manifest_cached_skips_on_sha_mismatch(tmp_path, monkeypatch):
    cache = tmp_path / "cache"

    def fake_get(url, timeout=0):
        resp = MagicMock()
        resp.content = b"WRONG"
        resp.raise_for_status = lambda: None
        return resp

    monkeypatch.setattr("video2yt.music_library.requests.get", fake_get)
    manifest = [{"name": "song1", "url": "http://x/s1.mp3",
                 "sha256": "0" * 64, "duration": 90.0, "license": "CC0"}]
    # Must not raise — bad track is warned and skipped.
    music_library.ensure_manifest_cached(manifest, cache)
    assert not (cache / "song1.mp3").exists()


def test_ensure_manifest_cached_skips_on_download_error(tmp_path, monkeypatch):
    cache = tmp_path / "cache"

    def fake_get(url, timeout=0):
        raise requests.RequestException("boom")

    monkeypatch.setattr("video2yt.music_library.requests.get", fake_get)
    manifest = [{"name": "song1", "url": "http://x/s1.mp3",
                 "sha256": "0" * 64, "duration": 90.0, "license": "CC0"}]
    music_library.ensure_manifest_cached(manifest, cache)  # must not raise
    assert not (cache / "song1.mp3").exists()
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k ensure_manifest_cached -v`
Expected: FAIL — `AttributeError: module 'video2yt.music_library' has no attribute 'ensure_manifest_cached'`.

- [x] **Step 3: Implement `ensure_manifest_cached`**

Append to `src/video2yt/music_library.py`:

```python
def _cache_filename(entry: dict) -> str:
    """Cache filename for a manifest entry: ``<name><ext-from-url>``."""
    ext = Path(entry["url"]).suffix or ".mp3"
    return f"{entry['name']}{ext}"


def ensure_manifest_cached(manifest: list[dict], cache_dir: Path) -> None:
    """Download every manifest track that is not already cached.

    Each track is downloaded to ``cache_dir/<name><ext>`` and verified against
    its ``sha256``. A track that fails to download or fails verification is
    warned about and skipped — one bad entry never aborts the run (spec §9).
    """
    cache_dir.mkdir(parents=True, exist_ok=True)
    for entry in manifest:
        dest = cache_dir / _cache_filename(entry)
        if dest.exists():
            continue
        try:
            resp = requests.get(entry["url"], timeout=60)
            resp.raise_for_status()
        except requests.RequestException as e:
            _log(f"WARNING: skipping {entry['name']!r} — download failed: {e}")
            continue
        actual = hashlib.sha256(resp.content).hexdigest()
        if actual != entry["sha256"]:
            _log(
                f"WARNING: skipping {entry['name']!r} — sha256 mismatch "
                f"(expected {entry['sha256']}, got {actual})"
            )
            continue
        dest.write_bytes(resp.content)
        _log(f"cached {dest.name}")
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k ensure_manifest_cached -v`
Expected: 4 passed.

- [x] **Step 5: Commit**

```bash
git add src/video2yt/music_library.py tests/test_smoke.py
git commit -m "feat(music_library): add ensure_manifest_cached with skip-on-failure"
```

---

## Task 4: `music_library.scan_cache` (build the Track pool)

**Files:**
- Modify: `src/video2yt/music_library.py`
- Test: `tests/test_smoke.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def test_scan_cache_builds_pool_with_probed_durations(tmp_path, monkeypatch):
    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / "a.mp3").write_bytes(b"x")
    (cache / "b.wav").write_bytes(b"x")
    (cache / "notes.txt").write_text("ignore me")  # non-audio, must be skipped

    durations = {"a.mp3": 100.0, "b.wav": 200.0}

    def fake_probe(path):
        return _mk_info(duration=durations[Path(path).name],
                        has_video=False, vcodec="", acodec="mp3")

    monkeypatch.setattr("video2yt.music_library.validate.probe", fake_probe)
    pool = music_library.scan_cache(cache)
    names = sorted(t.name for t in pool)
    assert names == ["a.mp3", "b.wav"]
    by_name = {t.name: t.duration for t in pool}
    assert by_name == {"a.mp3": 100.0, "b.wav": 200.0}


def test_scan_cache_empty_raises(tmp_path):
    cache = tmp_path / "cache"
    cache.mkdir()
    with pytest.raises(ValueError, match="no usable"):
        music_library.scan_cache(cache)


def test_scan_cache_missing_dir_raises(tmp_path):
    with pytest.raises(ValueError, match="no usable"):
        music_library.scan_cache(tmp_path / "does_not_exist")
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k scan_cache -v`
Expected: FAIL — `AttributeError: ... has no attribute 'scan_cache'`.

- [x] **Step 3: Implement `Track` + `scan_cache`**

Add the `validate` import to the top of `src/video2yt/music_library.py` (next to the other imports):

```python
from video2yt import validate
```

Append to `src/video2yt/music_library.py`:

```python
@dataclass
class Track:
    """One playable music file in the cache pool."""
    name: str
    path: Path
    duration: float


def scan_cache(cache_dir: Path) -> list[Track]:
    """Return the Track pool: every audio file in ``cache_dir``, duration-probed.

    Duration comes from ``validate.probe`` (ffprobe), not from the manifest,
    so user-supplied tracks with no manifest entry work correctly (spec §5).
    Raises ``ValueError`` if the directory has no usable audio file at all.
    """
    files = []
    if cache_dir.is_dir():
        files = sorted(
            p for p in cache_dir.iterdir()
            if p.is_file() and p.suffix.lower() in AUDIO_EXTENSIONS
        )
    if not files:
        raise ValueError(
            f"no usable music track found in {cache_dir}. Fix the manifest / "
            f"network, or drop your own audio files into that directory."
        )
    pool: list[Track] = []
    for f in files:
        info = validate.probe(f)
        pool.append(Track(name=f.name, path=f, duration=info.duration))
    return pool
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k scan_cache -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add src/video2yt/music_library.py tests/test_smoke.py
git commit -m "feat(music_library): add scan_cache + Track pool"
```

---

## Task 5: `music_library.select_sequence` (shuffle + fill to target)

**Files:**
- Modify: `src/video2yt/music_library.py`
- Test: `tests/test_smoke.py`

- [x] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def _track(name, duration):
    return music_library.Track(name=name, path=Path(name), duration=duration)


def test_select_sequence_fills_to_target():
    pool = [_track("a.mp3", 100.0), _track("b.mp3", 100.0)]
    seq = music_library.select_sequence(pool, target_duration=250.0,
                                        crossfade=2.0, seed=1)
    # effective length = sum(d) - (n-1)*crossfade must reach >= 250
    eff = sum(t.duration for t in seq) - (len(seq) - 1) * 2.0
    assert eff >= 250.0


def test_select_sequence_is_deterministic_with_seed():
    pool = [_track("a.mp3", 60.0), _track("b.mp3", 60.0), _track("c.mp3", 60.0)]
    s1 = music_library.select_sequence(pool, 300.0, crossfade=2.0, seed=42)
    s2 = music_library.select_sequence(pool, 300.0, crossfade=2.0, seed=42)
    assert [t.name for t in s1] == [t.name for t in s2]


def test_select_sequence_repeats_pool_when_short():
    pool = [_track("only.mp3", 30.0)]
    seq = music_library.select_sequence(pool, target_duration=120.0,
                                        crossfade=2.0, seed=1)
    assert len(seq) >= 4  # 30s track must repeat to cover 120s
    assert all(t.name == "only.mp3" for t in seq)
```

- [x] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k select_sequence -v`
Expected: FAIL — `AttributeError: ... has no attribute 'select_sequence'`.

- [x] **Step 3: Implement `select_sequence`**

Append to `src/video2yt/music_library.py`:

```python
def select_sequence(
    pool: list[Track],
    target_duration: float,
    crossfade: float = 2.0,
    seed: int | None = None,
) -> list[Track]:
    """Pick a track sequence whose stitched length covers ``target_duration``.

    The pool is shuffled (deterministically when ``seed`` is given), then
    walked cyclically — repeating the shuffled order — appending tracks until
    the stitched length reaches the target. Stitching consecutive tracks with
    an ``acrossfade`` of ``crossfade`` seconds overlaps them, so the effective
    length of N tracks is ``sum(durations) - (N-1) * crossfade``.
    """
    if not pool:
        raise ValueError("cannot select from an empty track pool")
    order = list(pool)
    random.Random(seed).shuffle(order)

    seq: list[Track] = []
    total = 0.0
    i = 0
    while True:
        track = order[i % len(order)]
        seq.append(track)
        if len(seq) == 1:
            total = track.duration
        else:
            total += track.duration - crossfade
        if total >= target_duration:
            break
        i += 1
    return seq
```

- [x] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k select_sequence -v`
Expected: 3 passed.

- [x] **Step 5: Commit**

```bash
git add src/video2yt/music_library.py tests/test_smoke.py
git commit -m "feat(music_library): add select_sequence"
```

---

## Task 6: `music_swap.extract_audio`

**Files:**
- Create: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [x] **Step 1: Write the failing test**

Append to `tests/test_smoke.py`:

```python
from video2yt import music_swap


def test_extract_audio_builds_ffmpeg_command(tmp_path, monkeypatch):
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"x")
    out = tmp_path / "audio.wav"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.music_swap.subprocess.run", fake_run)
    music_swap.extract_audio(src, out)
    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    assert "-vn" in cmd
    assert str(src) in cmd
    assert str(out) in cmd
    # 44.1 kHz stereo PCM
    assert "44100" in cmd
    assert "2" in cmd
```

- [x] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py -k extract_audio -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'video2yt.music_swap'`.

- [x] **Step 3: Create the module with `extract_audio`**

Create `src/video2yt/music_swap.py`:

```python
"""Audio pipeline for video2yt-music-swap.

Replaces the streamer's copyrighted background music in a burnt Bilibili
segment: extract audio -> isolate the commentary voice with Demucs -> discard
the music+SFX mix -> stitch a CC0 music bed -> mix (with ducking) -> remux the
new audio back into the video (no video re-encode).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from video2yt import music_library, validate


def _log(msg: str) -> None:
    print(f"[music_swap] {msg}", file=sys.stderr)


@dataclass
class MusicSwapInputs:
    input_path: Path
    output_path: Path
    music_volume: float = 0.25
    duck: bool = True
    model: str = "htdemucs"
    seed: int | None = None
    keep_temp: bool = False


def extract_audio(input_path: Path, wav_path: Path) -> None:
    """Extract the input's audio to a 44.1 kHz stereo 16-bit PCM WAV."""
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-vn",
        "-ac", "2",
        "-ar", "44100",
        "-c:a", "pcm_s16le",
        str(wav_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
```

- [x] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_smoke.py -k extract_audio -v`
Expected: 1 passed.

- [x] **Step 5: Commit**

```bash
git add src/video2yt/music_swap.py tests/test_smoke.py
git commit -m "feat(music_swap): add extract_audio"
```

---

## Task 7: `music_swap.separate_vocals` (Demucs)

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def test_separate_vocals_runs_demucs_two_stems(tmp_path, monkeypatch):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"x")
    out_dir = tmp_path / "demucs_out"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        # Demucs writes <out>/<model>/<stem>/vocals.wav
        stem_dir = out_dir / "htdemucs" / "audio"
        stem_dir.mkdir(parents=True, exist_ok=True)
        (stem_dir / "vocals.wav").write_bytes(b"VOCALS")
        (stem_dir / "no_vocals.wav").write_bytes(b"REST")
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.music_swap.subprocess.run", fake_run)
    monkeypatch.setattr("video2yt.music_swap._pick_device", lambda: "cpu")
    vocals = music_swap.separate_vocals(wav, "htdemucs", out_dir)

    cmd = captured["cmd"]
    assert "demucs" in cmd
    assert "--two-stems" in cmd
    assert "vocals" in cmd
    assert "htdemucs" in cmd
    assert vocals.name == "vocals.wav"
    assert vocals.read_bytes() == b"VOCALS"


def test_separate_vocals_raises_if_vocals_missing(tmp_path, monkeypatch):
    wav = tmp_path / "audio.wav"
    wav.write_bytes(b"x")
    monkeypatch.setattr("video2yt.music_swap.subprocess.run",
                        lambda cmd, **k: MagicMock(returncode=0))
    monkeypatch.setattr("video2yt.music_swap._pick_device", lambda: "cpu")
    with pytest.raises(ValueError, match="vocals"):
        music_swap.separate_vocals(wav, "htdemucs", tmp_path / "out")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k separate_vocals -v`
Expected: FAIL — `AttributeError: ... has no attribute 'separate_vocals'`.

- [ ] **Step 3: Implement `_pick_device` + `separate_vocals`**

Append to `src/video2yt/music_swap.py`:

```python
def _pick_device() -> str:
    """Return the Demucs device: ``mps`` on Apple Silicon if available, else ``cpu``.

    CUDA is intentionally not selected here — the target machine is macOS.
    """
    try:
        import torch
        if torch.backends.mps.is_available():
            return "mps"
    except Exception:
        pass
    return "cpu"


def separate_vocals(wav_path: Path, model: str, out_dir: Path) -> Path:
    """Run Demucs in two-stem mode and return the path to ``vocals.wav``.

    Demucs writes ``<out_dir>/<model>/<wav stem>/{vocals,no_vocals}.wav``.
    ``no_vocals.wav`` (the music + game-SFX mix) is left on disk but ignored —
    it is the Approach A trade-off (spec §2). Demucs runs as a subprocess via
    ``python -m demucs`` so the call is mockable at the ``subprocess.run``
    boundary.
    """
    device = _pick_device()
    _log(f"running Demucs ({model}, device={device}) — this is slow on CPU")
    cmd = [
        sys.executable, "-m", "demucs",
        "--two-stems", "vocals",
        "-n", model,
        "-d", device,
        "-o", str(out_dir),
        str(wav_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
    vocals = out_dir / model / wav_path.stem / "vocals.wav"
    if not vocals.exists():
        raise ValueError(
            f"Demucs did not produce {vocals} — separation failed"
        )
    return vocals
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k separate_vocals -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/music_swap.py tests/test_smoke.py
git commit -m "feat(music_swap): add separate_vocals via Demucs"
```

---

## Task 8: `music_swap.build_music_bed`

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def test_build_music_bed_multi_track_crossfades(tmp_path, monkeypatch):
    seq = [_track(str(tmp_path / "a.mp3"), 100.0),
           _track(str(tmp_path / "b.mp3"), 100.0)]
    bed = tmp_path / "bed.wav"
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        return MagicMock(returncode=0)

    monkeypatch.setattr("video2yt.music_swap.subprocess.run", fake_run)
    music_swap.build_music_bed(seq, target_duration=150.0,
                               bed_path=bed, crossfade=2.0)
    cmd = captured["cmd"]
    joined = " ".join(cmd)
    assert cmd[0] == "ffmpeg"
    assert "-i" in cmd  # both tracks fed as inputs
    assert cmd.count("-i") == 2
    assert "acrossfade" in joined
    assert "afade" in joined          # tail fade-out
    assert "-t" in cmd                # trimmed to exact target
    assert str(bed) in cmd


def test_build_music_bed_single_track_no_crossfade(tmp_path, monkeypatch):
    seq = [_track(str(tmp_path / "only.mp3"), 400.0)]
    bed = tmp_path / "bed.wav"
    captured = {}
    monkeypatch.setattr("video2yt.music_swap.subprocess.run",
                        lambda cmd, **k: captured.setdefault("cmd", cmd)
                        or MagicMock(returncode=0))
    music_swap.build_music_bed(seq, target_duration=120.0,
                               bed_path=bed, crossfade=2.0)
    joined = " ".join(captured["cmd"])
    assert "acrossfade" not in joined  # one track -> nothing to crossfade
    assert "afade" in joined
    assert captured["cmd"].count("-i") == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k build_music_bed -v`
Expected: FAIL — `AttributeError: ... has no attribute 'build_music_bed'`.

- [ ] **Step 3: Implement `build_music_bed`**

Append to `src/video2yt/music_swap.py`:

```python
def build_music_bed(
    tracks: list,
    target_duration: float,
    bed_path: Path,
    crossfade: float = 2.0,
) -> None:
    """Stitch ``tracks`` into a single music bed of exactly ``target_duration``.

    Consecutive tracks are joined with an ``acrossfade`` of ``crossfade``
    seconds. The result is trimmed to the target with ``-t`` and a
    ``crossfade``-second ``afade`` out is applied at the tail. ``tracks`` is a
    non-empty list of ``music_library.Track``.
    """
    if not tracks:
        raise ValueError("cannot build a music bed from an empty track list")

    cmd = ["ffmpeg", "-y"]
    for t in tracks:
        cmd += ["-i", str(t.path)]

    fade_start = max(0.0, target_duration - crossfade)
    if len(tracks) == 1:
        # Single track: loop it to be safe, then fade + trim.
        filtergraph = (
            f"[0:a]aloop=loop=-1:size=2e9,"
            f"afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}[out]"
        )
    else:
        # Chain acrossfade across all inputs: [0][1]->[a1], [a1][2]->[a2], ...
        steps = []
        prev = "[0:a]"
        for idx in range(1, len(tracks)):
            label = "[out]" if idx == len(tracks) - 1 else f"[a{idx}]"
            steps.append(
                f"{prev}[{idx}:a]acrossfade=d={crossfade:.3f}:c1=tri:c2=tri{label}"
            )
            prev = label
        # Append the tail fade as a second branch off the final label.
        joined = ";".join(steps)
        filtergraph = (
            joined.replace("[out]", "[mix]")
            + f";[mix]afade=t=out:st={fade_start:.3f}:d={crossfade:.3f}[out]"
        )

    cmd += [
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-t", f"{target_duration:.3f}",
        "-c:a", "pcm_s16le",
        str(bed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k build_music_bed -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/music_swap.py tests/test_smoke.py
git commit -m "feat(music_swap): add build_music_bed"
```

---

## Task 9: `music_swap.mix` (voice + bed, with optional ducking)

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def test_mix_with_ducking(tmp_path, monkeypatch):
    vocals = tmp_path / "vocals.wav"
    bed = tmp_path / "bed.wav"
    out = tmp_path / "mixed.wav"
    captured = {}
    monkeypatch.setattr("video2yt.music_swap.subprocess.run",
                        lambda cmd, **k: captured.setdefault("cmd", cmd)
                        or MagicMock(returncode=0))
    music_swap.mix(vocals, bed, music_volume=0.25, duck=True, mixed_path=out)
    joined = " ".join(captured["cmd"])
    assert "sidechaincompress" in joined
    assert "volume=0.25" in joined
    assert "amix" in joined
    assert str(out) in captured["cmd"]


def test_mix_without_ducking(tmp_path, monkeypatch):
    vocals = tmp_path / "vocals.wav"
    bed = tmp_path / "bed.wav"
    out = tmp_path / "mixed.wav"
    captured = {}
    monkeypatch.setattr("video2yt.music_swap.subprocess.run",
                        lambda cmd, **k: captured.setdefault("cmd", cmd)
                        or MagicMock(returncode=0))
    music_swap.mix(vocals, bed, music_volume=0.3, duck=False, mixed_path=out)
    joined = " ".join(captured["cmd"])
    assert "sidechaincompress" not in joined  # flat mix
    assert "volume=0.3" in joined
    assert "amix" in joined
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k "test_mix_with" -v`
Expected: FAIL — `AttributeError: ... has no attribute 'mix'`.

- [ ] **Step 3: Implement `mix`**

Append to `src/video2yt/music_swap.py`:

```python
def mix(
    vocals_path: Path,
    bed_path: Path,
    music_volume: float,
    duck: bool,
    mixed_path: Path,
) -> None:
    """Mix the isolated commentary (input 0) with the music bed (input 1).

    The bed is scaled to ``music_volume`` relative to the voice. When ``duck``
    is true, the bed is side-chain compressed against the voice so it drops in
    level while the streamer talks; otherwise the bed plays at a flat level.
    The voice is always passed through at full level. The two are combined
    with ``amix``; output length follows the voice (input 0).
    """
    if duck:
        filtergraph = (
            f"[1:a]volume={music_volume}[bed];"
            f"[bed][0:a]sidechaincompress="
            f"threshold=0.05:ratio=8:attack=5:release=300[ducked];"
            f"[0:a][ducked]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[out]"
        )
    else:
        filtergraph = (
            f"[1:a]volume={music_volume}[bed];"
            f"[0:a][bed]amix=inputs=2:duration=first:"
            f"dropout_transition=0:normalize=0[out]"
        )
    cmd = [
        "ffmpeg", "-y",
        "-i", str(vocals_path),
        "-i", str(bed_path),
        "-filter_complex", filtergraph,
        "-map", "[out]",
        "-c:a", "pcm_s16le",
        str(mixed_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k "test_mix_with" -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/music_swap.py tests/test_smoke.py
git commit -m "feat(music_swap): add mix with sidechain ducking"
```

---

## Task 10: `music_swap.remux`

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_smoke.py`:

```python
def test_remux_copies_video_and_encodes_aac(tmp_path, monkeypatch):
    video = tmp_path / "seg.mp4"
    audio = tmp_path / "mixed.wav"
    out = tmp_path / "seg_clean.mp4"
    captured = {}
    monkeypatch.setattr("video2yt.music_swap.subprocess.run",
                        lambda cmd, **k: captured.setdefault("cmd", cmd)
                        or MagicMock(returncode=0))
    music_swap.remux(video, audio, out)
    cmd = captured["cmd"]
    assert cmd[0] == "ffmpeg"
    # video copied, not re-encoded
    assert "copy" in cmd
    assert "aac" in cmd
    assert str(video) in cmd
    assert str(audio) in cmd
    assert str(out) in cmd
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_smoke.py -k test_remux -v`
Expected: FAIL — `AttributeError: ... has no attribute 'remux'`.

- [ ] **Step 3: Implement `remux`**

Append to `src/video2yt/music_swap.py`:

```python
def remux(input_path: Path, mixed_path: Path, output_path: Path) -> None:
    """Combine the original video stream with the new mixed audio.

    The video stream is stream-copied (``-c:v copy``) — no re-encode — and the
    new audio is encoded to AAC 192k. The original audio stream is dropped.
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-i", str(input_path),
        "-i", str(mixed_path),
        "-map", "0:v:0",
        "-map", "1:a:0",
        "-c:v", "copy",
        "-c:a", "aac",
        "-b:a", "192k",
        "-movflags", "+faststart",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True, text=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_smoke.py -k test_remux -v`
Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/music_swap.py tests/test_smoke.py
git commit -m "feat(music_swap): add remux"
```

---

## Task 11: `music_swap.render` (orchestration + validation)

**Files:**
- Modify: `src/video2yt/music_swap.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
def test_render_orchestrates_pipeline_in_order(tmp_path, monkeypatch):
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"x" * 100)
    out = tmp_path / "seg_clean.mp4"
    calls = []

    def fake_probe(path):
        # input: a normal 1080p video; output: same shape
        return _mk_info(duration=300.0, width=1920, height=1080,
                        has_video=True, has_audio=True, vcodec="h264")

    monkeypatch.setattr("video2yt.music_swap.validate.probe", fake_probe)
    monkeypatch.setattr("video2yt.music_swap.extract_audio",
                        lambda i, o: calls.append("extract") or o.write_bytes(b"a"))
    monkeypatch.setattr(
        "video2yt.music_swap.separate_vocals",
        lambda w, m, d: calls.append("separate") or _touch(d / "v.wav"))
    monkeypatch.setattr("video2yt.music_swap.music_library.ensure_manifest_cached",
                        lambda manifest, cache: calls.append("ensure_cache"))
    monkeypatch.setattr("video2yt.music_swap.music_library.load_manifest",
                        lambda: [])
    monkeypatch.setattr(
        "video2yt.music_swap.music_library.scan_cache",
        lambda cache: calls.append("scan") or [_track("a.mp3", 400.0)])
    monkeypatch.setattr("video2yt.music_swap.music_library.select_sequence",
                        lambda pool, dur, crossfade, seed:
                        calls.append("select") or pool)
    monkeypatch.setattr("video2yt.music_swap.build_music_bed",
                        lambda seq, dur, bed, crossfade=2.0:
                        calls.append("bed") or bed.write_bytes(b"b"))
    monkeypatch.setattr("video2yt.music_swap.mix",
                        lambda v, b, mv, dk, mp:
                        calls.append("mix") or mp.write_bytes(b"m"))
    monkeypatch.setattr("video2yt.music_swap.remux",
                        lambda i, m, o: calls.append("remux") or o.write_bytes(b"o"))

    inputs = music_swap.MusicSwapInputs(input_path=src, output_path=out)
    result = music_swap.render(inputs)

    assert result == out
    assert calls.index("extract") < calls.index("separate")
    assert calls.index("separate") < calls.index("mix")
    assert calls.index("bed") < calls.index("mix")
    assert calls.index("mix") < calls.index("remux")


def test_render_rejects_input_with_no_audio(tmp_path, monkeypatch):
    src = tmp_path / "seg.mp4"
    src.write_bytes(b"x")
    monkeypatch.setattr(
        "video2yt.music_swap.validate.probe",
        lambda p: _mk_info(has_audio=False, acodec=None))
    inputs = music_swap.MusicSwapInputs(input_path=src,
                                        output_path=tmp_path / "o.mp4")
    with pytest.raises(ValueError, match="audio"):
        music_swap.render(inputs)
```

Also add this helper near the top of the test file's helper section (after `_mk_info`):

```python
def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x")
    return path
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k test_render_orchestrates -v`
Expected: FAIL — `AttributeError: ... has no attribute 'render'`.

- [ ] **Step 3: Implement `render`**

Append to `src/video2yt/music_swap.py`:

```python
def render(inputs: MusicSwapInputs) -> Path:
    """Run the full music-swap pipeline and return the output path.

    Steps: probe input -> extract audio -> Demucs vocal isolation -> build the
    CC0 music bed -> mix (with ducking) -> remux into the video -> validate.
    Temp files go in a scratch directory removed afterwards unless
    ``keep_temp`` is set. Final loudness is left to ``video2yt-merge``.
    """
    src_info = validate.probe(inputs.input_path)
    if not src_info.has_video:
        raise ValueError(f"input has no video stream: {inputs.input_path}")
    if not src_info.has_audio:
        raise ValueError(f"input has no audio stream: {inputs.input_path}")

    work = Path(tempfile.mkdtemp(prefix="music_swap_"))
    try:
        wav = work / "audio.wav"
        _log("extracting audio")
        extract_audio(inputs.input_path, wav)

        _log("isolating commentary voice")
        demucs_out = work / "demucs"
        vocals = separate_vocals(wav, inputs.model, demucs_out)

        _log("building royalty-free music bed")
        music_library.ensure_manifest_cached(
            music_library.load_manifest(), music_library.CACHE_DIR
        )
        pool = music_library.scan_cache(music_library.CACHE_DIR)
        sequence = music_library.select_sequence(
            pool, src_info.duration, crossfade=2.0, seed=inputs.seed
        )
        bed = work / "bed.wav"
        build_music_bed(sequence, src_info.duration, bed, crossfade=2.0)

        _log(f"mixing (music_volume={inputs.music_volume}, duck={inputs.duck})")
        mixed = work / "mixed.wav"
        mix(vocals, bed, inputs.music_volume, inputs.duck, mixed)

        _log("remuxing into the video")
        remux(inputs.input_path, mixed, inputs.output_path)

        _log("validating output")
        out_info = validate.probe(inputs.output_path)
        if not out_info.has_video or not out_info.has_audio:
            raise ValueError("output is missing a video or audio stream")
        if out_info.width != src_info.width or out_info.height != src_info.height:
            raise ValueError(
                f"output resolution {out_info.width}x{out_info.height} "
                f"differs from input {src_info.width}x{src_info.height}"
            )
        if abs(out_info.duration - src_info.duration) >= 1.0:
            raise ValueError(
                f"output duration {out_info.duration:.2f}s differs from input "
                f"{src_info.duration:.2f}s by more than 1 second"
            )
        _log(f"success: {inputs.output_path}")
        return inputs.output_path
    finally:
        if inputs.keep_temp:
            _log(f"keeping temp dir: {work}")
        else:
            shutil.rmtree(work, ignore_errors=True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_smoke.py -k "test_render_orchestrates or test_render_rejects" -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/music_swap.py tests/test_smoke.py
git commit -m "feat(music_swap): add render orchestration + validation"
```

---

## Task 12: `music_swap_cli` (entry point)

**Files:**
- Create: `src/video2yt/music_swap_cli.py`
- Test: `tests/test_smoke.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_smoke.py`:

```python
from video2yt import music_swap_cli


def test_cli_parse_args_defaults():
    args = music_swap_cli.parse_args(["seg.mp4"])
    assert args.input == Path("seg.mp4")
    assert args.output is None
    assert args.music_volume == 0.25
    assert args.no_duck is False
    assert args.model == "htdemucs"
    assert args.seed is None
    assert args.keep_temp is False


def test_cli_parse_args_all_flags():
    args = music_swap_cli.parse_args([
        "seg.mp4", "-o", "out.mp4", "--music-volume", "0.4",
        "--no-duck", "--model", "htdemucs_ft", "--seed", "7", "--keep-temp",
    ])
    assert args.output == Path("out.mp4")
    assert args.music_volume == 0.4
    assert args.no_duck is True
    assert args.model == "htdemucs_ft"
    assert args.seed == 7
    assert args.keep_temp is True


def test_cli_preflight_fails_without_ffmpeg(monkeypatch):
    monkeypatch.setattr("video2yt.music_swap_cli.shutil.which",
                        lambda name: None)
    with pytest.raises(RuntimeError, match="ffmpeg"):
        music_swap_cli.preflight()


def test_cli_preflight_fails_without_demucs(monkeypatch):
    monkeypatch.setattr("video2yt.music_swap_cli.shutil.which",
                        lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr("video2yt.music_swap_cli.importlib.util.find_spec",
                        lambda name: None)
    with pytest.raises(RuntimeError, match="demucs"):
        music_swap_cli.preflight()


def test_cli_run_derives_default_output(tmp_path, monkeypatch):
    src = tmp_path / "BV123_with_danmaku.mp4"
    src.write_bytes(b"x")
    captured = {}
    monkeypatch.setattr("video2yt.music_swap_cli.preflight", lambda: None)
    monkeypatch.setattr("video2yt.music_swap_cli.music_swap.render",
                        lambda inputs: captured.setdefault("inputs", inputs)
                        or inputs.output_path)
    args = music_swap_cli.parse_args([str(src)])
    music_swap_cli.run(args)
    assert captured["inputs"].output_path == src.with_name(
        "BV123_with_danmaku_clean.mp4")


def test_cli_run_rejects_missing_input(tmp_path, monkeypatch):
    monkeypatch.setattr("video2yt.music_swap_cli.preflight", lambda: None)
    args = music_swap_cli.parse_args([str(tmp_path / "nope.mp4")])
    with pytest.raises(FileNotFoundError):
        music_swap_cli.run(args)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_smoke.py -k "test_cli_" -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'video2yt.music_swap_cli'`.

- [ ] **Step 3: Create the CLI module**

Create `src/video2yt/music_swap_cli.py`:

```python
"""video2yt-music-swap entry point.

Replaces the streamer's copyrighted background music in a burnt Bilibili
segment with a CC0 royalty-free music bed (Approach A — see the design spec).
"""
import argparse
import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

from video2yt import music_swap


def _log(msg: str) -> None:
    print(f"[video2yt-music-swap] {msg}", file=sys.stderr)


def preflight() -> None:
    """Fail fast if ffmpeg, ffprobe, or the demucs package are unavailable."""
    if shutil.which("ffmpeg") is None:
        raise RuntimeError(
            "ffmpeg not found in PATH. Install with: "
            "brew install homebrew-ffmpeg/ffmpeg/ffmpeg"
        )
    if shutil.which("ffprobe") is None:
        raise RuntimeError("ffprobe not found in PATH (usually ships with ffmpeg)")
    if importlib.util.find_spec("demucs") is None:
        raise RuntimeError(
            "demucs package not found. Install with: uv add demucs"
        )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="video2yt-music-swap",
        description=(
            "Isolate the commentary voice from a burnt Bilibili segment and "
            "replace the streamer's background music with a CC0 music bed."
        ),
    )
    parser.add_argument("input", type=Path, help="Input segment MP4")
    parser.add_argument(
        "-o", "--output", type=Path, default=None,
        help="Output MP4 (default: <input stem>_clean.mp4 alongside the input)",
    )
    parser.add_argument(
        "--music-volume", type=float, default=0.25,
        help="Music bed level relative to the voice (default: 0.25)",
    )
    parser.add_argument(
        "--no-duck", action="store_true",
        help="Disable sidechain ducking; mix the bed at a flat level",
    )
    parser.add_argument(
        "--model", default="htdemucs",
        help="Demucs separation model (default: htdemucs)",
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Seed for reproducible music-track selection",
    )
    parser.add_argument(
        "--keep-temp", action="store_true",
        help="Keep the temp directory (extracted WAV, Demucs output)",
    )
    return parser.parse_args(argv)


def run(args: argparse.Namespace) -> Path:
    preflight()
    if not args.input.exists():
        raise FileNotFoundError(f"input file not found: {args.input}")
    output = args.output or args.input.with_name(
        f"{args.input.stem}_clean.mp4"
    )
    inputs = music_swap.MusicSwapInputs(
        input_path=args.input,
        output_path=output,
        music_volume=args.music_volume,
        duck=not args.no_duck,
        model=args.model,
        seed=args.seed,
        keep_temp=args.keep_temp,
    )
    _log(f"music-swapping {args.input.name} -> {output.name}")
    return music_swap.render(inputs)


def main(argv: list[str] | None = None) -> int:
    try:
        args = parse_args(argv)
        run(args)
        return 0
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

Run: `uv run pytest tests/test_smoke.py -k "test_cli_" -v`
Expected: 6 passed.

- [ ] **Step 5: Run the whole suite + verify the console script resolves**

Run: `uv run pytest`
Expected: all tests pass (the original 162+ plus the new ones).

Run: `uv run video2yt-music-swap --help`
Expected: the argparse help text prints, exit 0.

- [ ] **Step 6: Commit**

```bash
git add src/video2yt/music_swap_cli.py tests/test_smoke.py
git commit -m "feat(music-swap): add video2yt-music-swap CLI entry point"
```

---

## Task 13: Seed the CC0 music manifest (research task — not code)

> This task is research, not programming. It cannot be TDD'd. The tool already
> works with an empty manifest (the user can drop their own tracks into
> `~/.cache/video2yt/music/`); this task makes it useful out of the box.

**Files:**
- Modify: `src/video2yt/data/music_library.json`

- [ ] **Step 1: Collect candidate tracks**

Find 6–10 instrumental background tracks that satisfy **both** rules from spec §6:
1. **Redistributable** — the license must explicitly permit redistribution / direct download. In practice this means **CC0 / public-domain dedication**. Acceptable sources: the CC0 collections on Free Music Archive (`freemusicarchive.org`, filter License = CC0), or other catalogs that publish a CC0 dedication and a stable direct-download URL. **Do NOT use YouTube Audio Library tracks** — its license forbids redistribution, so the tool cannot download them (spec §6).
2. **Not in Content ID** — as far as is practical, confirm the track is not registered in YouTube Content ID (e.g. search the track on YouTube and check whether uploads using it carry claims).

Prefer calm, instrumental, loopable tracks (no vocals) so they sit unobtrusively under commentary.

- [ ] **Step 2: Compute sha256 + duration for each track**

For each chosen track, download it once and run:

```bash
shasum -a 256 <file>          # the sha256 hex digest
uv run python -c "from video2yt import validate; print(validate.probe(__import__('pathlib').Path('<file>')).duration)"
```

- [ ] **Step 3: Populate the manifest**

Replace the contents of `src/video2yt/data/music_library.json` with the real entries, e.g.:

```json
{
  "tracks": [
    {
      "name": "calm_morning",
      "url": "https://files.freemusicarchive.org/.../calm_morning.mp3",
      "sha256": "<64-hex-digest>",
      "duration": 184.6,
      "license": "CC0"
    }
  ]
}
```

`name` must be unique and filename-safe (it becomes the cache filename). `url` must be the canonical host's direct-download URL, not a re-hosted copy.

- [ ] **Step 4: Verify the manifest loads and downloads**

Run: `uv run python -c "from video2yt import music_library as m; print(len(m.load_manifest()))"`
Expected: prints the track count.

Run: `uv run python -c "from video2yt import music_library as m; m.ensure_manifest_cached(m.load_manifest(), m.CACHE_DIR)"`
Expected: each track logs `[music_library] cached <name>.<ext>` with no `WARNING` lines (a WARNING means a bad URL or sha256 — fix the manifest entry).

- [ ] **Step 5: Commit**

```bash
git add src/video2yt/data/music_library.json
git commit -m "chore(music-swap): seed CC0 music manifest"
```

---

## Task 14: Documentation

**Files:**
- Modify: `docs/superpowers/specs/2026-04-18-video-production-workflow.md`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Add Step 6.5 to the workflow spec**

In `docs/superpowers/specs/2026-04-18-video-production-workflow.md`, insert a new `### Step 6.5 — Replace copyrighted background music` section between Step 6 and the current subtitle step. Content:

```markdown
### Step 6.5 — Replace copyrighted background music

**Input**: a burnt segment MP4 from Step 6.
**Output**: `<segment>_clean.mp4` — same video, music bed swapped.
**Tool**: `video2yt-music-swap`.

\`\`\`bash
uv run video2yt-music-swap output/<project>/<uploader>：<title>/<bv>_with_danmaku_*.mp4
\`\`\`

Isolates the streamer's commentary voice with Demucs, discards the original
music + game SFX, and lays a stitched CC0 royalty-free music bed underneath
(auto-ducked under the voice). This suppresses the streamer's copyrighted
background music so the upload is very unlikely to draw a Content ID claim on
it — **risk reduction, not a guarantee** (see the music-swap design spec).

Run this **before** the subtitle step so its speech recognition works on
clean isolated vocals. **Performance**: Demucs is slow — a 17-minute segment
can take 10–30 minutes on CPU; faster on Apple Silicon (MPS). Plan accordingly,
like the subtitle step.
```

Then renumber the existing `### Step 6.5 — ...` subtitle section to `### Step 6.6`, and update the per-project checklist in section 8 (the `- [ ] Step 6.5 — add STT subtitles ...` line becomes `Step 6.6`, and add a `- [ ] Step 6.5 — replace background music via video2yt-music-swap` line above it).

- [ ] **Step 2: Update CLAUDE.md — Commands block**

In `CLAUDE.md`, in the `## Commands` code block, add after the `video2yt-subtitle` line:

```
uv run video2yt-music-swap seg.mp4                         # swap copyrighted BGM for CC0 music
```

- [ ] **Step 3: Update CLAUDE.md — Architecture map**

In the `## Architecture` tree, add these entries:

```
├── music_swap.py     # extract → Demucs vocal isolation → CC0 bed → mix → remux
├── music_swap_cli.py # video2yt-music-swap entry point
├── music_library.py  # CC0 manifest + download cache + track selection
```

- [ ] **Step 4: Update CLAUDE.md — gotcha**

In `## Known gotchas`, add:

```
- **music-swap is risk reduction, not a guarantee**: `video2yt-music-swap` isolates the commentary voice (Demucs) and discards the original music+SFX mix, so the game sound effects are lost by design (Approach A — see `docs/superpowers/specs/2026-05-20-music-swap-design.md`). Demucs separation is imperfect: faint music can bleed into the vocals stem, and the replacement CC0 track carries its own claim risk. It strongly suppresses the streamer's music but does not mathematically guarantee a claim-free upload. Demucs is also slow (10–30 min for a 17-min segment on CPU; faster on Apple Silicon MPS).
```

- [ ] **Step 5: Commit**

```bash
git add docs/superpowers/specs/2026-04-18-video-production-workflow.md CLAUDE.md
git commit -m "docs: add video2yt-music-swap to workflow spec + CLAUDE.md"
```

---

## Self-Review

**Spec coverage** — every spec section maps to a task:
- §1/§2 problem + Approach A trade-off → Task 7 (`separate_vocals` discards `no_vocals.wav`), documented in Task 14.
- §4 workflow placement (Step 6.5, before subtitle) → Task 14.
- §5 internal pipeline → Tasks 6–11 (extract → separate → bed → mix → remux → validate). Cache-dir-as-source-of-truth + ffprobe durations + pool-repeat → Tasks 4, 5.
- §6 music library (manifest, download/cache, sha256, user-supplied tracks, CC0/redistributable rule, vetting) → Tasks 2, 3, 4, 13.
- §7 CLI flags → Task 12.
- §8 performance (MPS auto-select) → Task 7 (`_pick_device`), documented in Task 14.
- §9 error handling (missing tools, no audio/video, skip-on-failure, empty-pool fatal, duration drift) → Tasks 3, 4, 11, 12.
- §10 module layout (`music_swap.py`, `music_swap_cli.py`, `music_library.py`, `data/music_library.json`) → Tasks 1, 2, 6, 12.
- §11 testing (subprocess-boundary mocking, listed cases) → tests in every task.
- §12 docs → Task 14.

**Placeholder scan** — no TBD/TODO; all code blocks are complete. Task 13 is explicitly a research task (manifest content depends on live external sources) and gives a concrete, verifiable procedure rather than placeholder data.

**Type consistency** — `MusicSwapInputs` fields (`input_path`, `output_path`, `music_volume`, `duck`, `model`, `seed`, `keep_temp`) are defined in Task 6 and used identically in Tasks 11 and 12. `Track` (`name`, `path`, `duration`) is defined in Task 4 and used in Tasks 5, 8. `music_library` functions — `load_manifest`, `ensure_manifest_cached`, `scan_cache`, `select_sequence`, `CACHE_DIR` — keep the same signatures from definition (Tasks 2–5) through use in `render` (Task 11). `music_swap` functions — `extract_audio`, `separate_vocals`, `build_music_bed`, `mix`, `remux` — match between definition (Tasks 6–10) and the `render` orchestrator (Task 11).

# Step 6 Restructure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. Mark each step done as you finish it; commit at the end of every task (not every step) so reviewers can bisect by task.

**Goal:** Restructure the per-segment pipeline (`video2yt` → `video2yt-music-swap` → `video2yt-subtitle`) into five small CLIs (`video2yt-fetch`, `video2yt-stems`, `video2yt-subtitle`, `video2yt-music-mix`, `video2yt-burn`) orchestrated by `video2yt`. Replace the Demucs-in-music-swap step with the new `song-remover` CLI (default `--device remote` via Modal T4 GPU, 7.2× faster than local CPU). Burn danmaku ASS + cleaned subtitle ASS + new audio mix in a **single ffmpeg pass** with cache-meta sidecars guarding stem→subtitle and source→bed staleness.

**Spec reference:** `docs/superpowers/specs/2026-05-24-step6-restructure.md`. Read it end-to-end before starting Task 1.

**Tech Stack:** Python 3.10+, system `ffmpeg` (must include libass — see CLAUDE.md "Known gotchas"), `whisperx` (already a dep), `song-remover` CLI on `$PATH` (subprocess invocation; one-time `uv tool install` from `~/code/song-remover`).

---

## Conventions (read first)

- Tests all live in `tests/test_smoke.py` and `tests/test_subtitle.py`. Append new ones; do not create new test files unless the spec calls for them (the spec calls for `test_stems.py`, `test_music_mix.py`, `test_burn_all.py`).
- Every external tool (ffmpeg, ffprobe, yt-dlp, song-remover, whisperx, codex) is invoked through `subprocess.run`. Tests `monkeypatch.setattr("video2yt.<module>.subprocess.run", fake_run)` at the module boundary — no real subprocess in tests.
- CLI modules expose `preflight()`, `parse_args(argv)`, `run(args)`, `main(argv)`, and a module-level `_log(msg)` helper that prints `[<cli-name>] ...` to stderr. See `src/video2yt/compose_cli.py` for the template.
- `validate.probe(path) -> MediaInfo` (`src/video2yt/validate.py`) is the shared ffprobe wrapper — reuse, do not write a new one.
- Run everything with `uv run`. Never hand-edit dep lines in `pyproject.toml`; use `uv add` / `uv remove`.
- `subprocess.run` calls use `check=True, capture_output=True, text=True` unless there's a documented reason otherwise.
- Match the existing logging format: `[<cli-name>] <message>` to stderr, one line per phase, with wall-clock timings on the `success:` line.

## File structure (deltas from current state)

| File | Action | Responsibility |
|---|---|---|
| `src/video2yt/fetch.py` | CREATE | yt-dlp + biliass orchestration (extracted from today's `download.py` + parts of `cli.py`). |
| `src/video2yt/fetch_cli.py` | CREATE | `video2yt-fetch` entry point. |
| `src/video2yt/download.py` | MODIFY | Keep only the thin yt-dlp subprocess wrapper. Move biliass call and the metadata/duration helpers into `fetch.py`. |
| `src/video2yt/stems.py` | CREATE | song-remover subprocess wrapper; `.stems_source_meta.json` sidecar; cache-aware re-run. |
| `src/video2yt/stems_cli.py` | CREATE | `video2yt-stems` entry point. |
| `src/video2yt/subtitle.py` | MODIFY | Audio source flips from "extract from `<bv>.mp4` / find `<input>.vocals.wav` sidecar" to "read `<dir>/<bv>/speech.wav` directly". Demucs-vocals-stem code paths removed. Output flips from SRT to ASS via `compose.srt_to_ass`. Cache invalidation chain via `.speech_source_meta.json` + glob delete of `<bv>/speech.cleaned.*.srt`. |
| `src/video2yt/subtitle_cli.py` | MODIFY | Same input shape (`<bv>.mp4`), now requires `<bv>/speech.wav` as sibling; removes detection-logic branches. |
| `src/video2yt/music_mix.py` | CREATE | CC0 bed build, extracted from today's `music_swap.build_music_bed` + downstream helpers. `<bv>.music_bed_meta.json` sidecar. |
| `src/video2yt/music_mix_cli.py` | CREATE | `video2yt-music-mix` entry point. |
| `src/video2yt/burn.py` | MODIFY | `_build_filter_complex` extended for: two chained `subtitles=` filters, optional speech + music-bed inputs with sidechain-ducked amix, `-pix_fmt yuv420p -r 30 -ar 48000` outputs. Stage-5 path-escaping symlink pre-flight. Ephemeral cut-rewrite on both ASS files. |
| `src/video2yt/burn_cli.py` | CREATE | `video2yt-burn` entry point. |
| `src/video2yt/cli.py` | MODIFY | Becomes the thin orchestrator: calls the five stages in order with skip-flag contracts. Removes inline burn/font-size/cut logic (moved to fetch/burn). |
| `src/video2yt/music_swap.py` | DELETE | All logic absorbed into `burn.py` (mix) or `music_mix.py` (bed build). |
| `src/video2yt/music_swap_cli.py` | DELETE | — |
| `src/video2yt/music_detect.py` | DELETE | Existed only to mask Demucs `no_vocals` music residue; no longer needed. |
| `tests/test_stems.py` | CREATE | song-remover subprocess + meta-sidecar coverage. |
| `tests/test_music_mix.py` | CREATE | CC0 bed build + meta-sidecar coverage. |
| `tests/test_burn_all.py` | CREATE | filter_complex string assertions for all (cuts × speed × subtitle × music-swap) combinations. |
| `tests/test_smoke.py` | MODIFY | Drop music_swap tests; add orchestrator-level five-stage ordering + stage-skip-on-cache-hit tests. |
| `tests/test_subtitle.py` | MODIFY | Drop detection-logic tests; add `.speech_source_meta.json` + glob-delete tests. |
| `pyproject.toml` | MODIFY | Add new `[project.scripts]` lines; remove `video2yt-music-swap` line; remove `demucs`, `torchaudio`, `soundfile` deps (used only by deleted music_swap path). |
| `CLAUDE.md` | MODIFY | Commands, architecture map, gotchas — full rewrite of the per-segment pipeline section. |
| `docs/superpowers/specs/2026-04-18-video-production-workflow.md` | MODIFY | Step 6 / 6.5 / 6.6 collapsed to a single Step 6 with the new five-stage flow. |

---

## Task ordering rationale

Tasks 1–2 set up scaffolding so subsequent CLIs can be added one by one without breaking anything. Tasks 3–7 build the five new stages in dependency order (fetch → stems → subtitle → music-mix → burn). Task 8 wires the orchestrator. Task 9 deletes the old music-swap code (kept until the new path is verified end-to-end). Tasks 10–11 cover docs + workflow-spec updates and the real-ffmpeg smoke test that codex review N3 owes us.

**Do not commit until each task's full Definition-of-Done checklist passes**, including `uv run pytest` (full suite green) and `uv run mypy src/` (no new errors).

---

## Task 1: Project plumbing — entry points + song-remover preflight

**Files:**
- Modify: `pyproject.toml`
- Create: `src/video2yt/__init__.py` (probably unchanged, verify)

- [x] **Step 1: Register `video2yt-fetch` console script only**

In `pyproject.toml`, under `[project.scripts]`, add (alphabetized with existing entries):

```toml
video2yt-fetch = "video2yt.fetch_cli:main"
```

**The other three (`video2yt-burn`, `-music-mix`, `-stems`) are registered in their own tasks** (T3 stems, T5 music-mix, T6 burn) so that every commit leaves the repo in a runnable state — registering a script before its module exists makes `uv run video2yt-X` fail with a confusing `ModuleNotFoundError`. (Original T1 registered all four at once and codex stop-hook caught the broken-entry-point regression after T2.)

(Keep the existing `video2yt-music-swap` line for now — it's removed in Task 9 after the new path is verified.)

- [ ] **Step 2: Document the song-remover one-time setup in this plan**

Add a section to `CLAUDE.md` "External dependencies" listing the song-remover install:

```
- song-remover (out-of-tree subprocess): `cd ~/code/song-remover && uv tool install .`
  Then for cloud GPU: `uv sync --extra remote && uv run modal token new && uv run modal deploy -m modal_app.prep && uv run modal run -m modal_app.prep && uv run modal deploy -m modal_app.separator`
  Verify with `song-remover --version`.
```

(Don't touch any other part of CLAUDE.md yet — full rewrite is in Task 10.)

- [x] **Step 3: Verify the new script resolves AND that no broken entry points exist**

```bash
uv sync
uv run video2yt-fetch --help    # should fail with ModuleNotFoundError BEFORE T2 lands (expected); succeeds after.
uv run pytest                    # must stay green (no code changes yet)
```

Do NOT pre-register `video2yt-burn` / `-music-mix` / `-stems` here. They land in T3 / T5 / T6 alongside their modules so each commit leaves the entry-point set in a runnable state.

**Definition of Done:**
- `pyproject.toml` has the four new script lines.
- `uv run pytest` passes (full existing suite).
- CLAUDE.md has the song-remover install paragraph.
- Commit: `chore(step6): register new entry points and document song-remover setup`

---

## Task 2: Extract `fetch.py` from `download.py` + `cli.py`

**Spec section:** §4 Stage 1, §7 `video2yt-fetch`.

**Files:**
- Create: `src/video2yt/fetch.py`, `src/video2yt/fetch_cli.py`
- Modify: `src/video2yt/download.py`, `src/video2yt/cli.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Carve `fetch.fetch_and_build(url, temp_subdir, font_face, font_size, quality, codec) -> FetchResult`** out of today's `download.fetch` + the surrounding `cli.run` orchestration. Return a dataclass:

```python
@dataclass
class FetchResult:
    bv_id: str
    raw_video: Path          # <dir>/<bv>.mp4
    danmaku_xml: Path        # <dir>/<bv>.danmaku.xml
    danmaku_ass: Path        # <dir>/<bv>.danmaku.ass (un-cut; cut-rewrite is Stage 5)
    metadata: dict           # uploader, title, duration (from yt-dlp)
    info: MediaInfo          # ffprobe of raw_video
    from_cache: bool
```

Behavior identical to today's combined call chain. Crucially, **do NOT call `cuts.rewrite_ass_for_cuts` from this function** — that responsibility moves to Stage 5 (Task 7).

- [ ] **Step 2: Slim `download.py` down to just the yt-dlp subprocess wrapper**

Keep `download.fetch_video(...)` (the actual yt-dlp call + cache check) and `download.get_metadata`. Move biliass invocation, the per-video subfolder construction (`_build_dir_name`), and the font-size auto-computation into `fetch.py`. Update `cli.py`'s imports.

- [ ] **Step 3: Write `fetch_cli.py`**

Standard four-function shape (`preflight`, `parse_args`, `run`, `main`) per the conventions section. Args:

```
url: positional
--out / -o: output directory (required; the per-segment subfolder is built inside it)
--quality {480,720,1080}
--codec {h264,h265,auto}
--font-face NAME
--font-size N           # default: auto from video height
--cookies-from-browser
```

Output on success: one line `[video2yt-fetch] success: <FetchResult.raw_video>`.

- [ ] **Step 4: Unit tests in `tests/test_smoke.py`**

Append a `test_fetch_*` group. Mock `subprocess.run` so yt-dlp + biliass + ffprobe return canned outputs. Assert:
- Cache hit when `<bv>.mp4` + `<bv>*.xml` + `<bv>.danmaku.ass` all exist (yt-dlp NOT invoked).
- Cache miss when any of those is absent (yt-dlp IS invoked).
- `cuts.rewrite_ass_for_cuts` is NEVER called from this function.
- font_size is auto-computed when not provided (`video_height * 25 / 540`).

- [ ] **Step 5: Update `cli.py` to call `fetch.fetch_and_build` instead of the inline chain**

Don't add the other four stages yet — just keep behavior identical. Existing `video2yt <url>` smoke tests must still pass.

**Definition of Done:**
- `uv run video2yt-fetch <url> -o /tmp/test/` produces the three files and exits 0 (manual sanity check on a small clip; or rely on tests).
- `uv run pytest` passes.
- `uv run video2yt <url> -o /tmp/test/` still works end-to-end (the old pipeline is intact since cli.py is the only caller of fetch.py for now).
- Commit: `feat(fetch): extract video2yt-fetch CLI from download+cli`

---

## Task 3: Build `stems.py` + `video2yt-stems`

**Spec section:** §4 Stage 2, §7 `video2yt-stems`, §11 Q9.

**Files:**
- Create: `src/video2yt/stems.py`, `src/video2yt/stems_cli.py`, `tests/test_stems.py`

- [ ] **Step 1: Sidecar helpers in a shared location**

Decide where `.stems_source_meta.json`, `.speech_source_meta.json`, and `<bv>.music_bed_meta.json` schema lives. Recommend a tiny new module `src/video2yt/meta.py` with:

```python
def write_meta(path: Path, payload: dict) -> None: ...
def read_meta(path: Path) -> dict | None: ...
def compute_first_1mb_sha256(file: Path) -> str: ...
def meta_matches(path: Path, expected: dict) -> bool: ...
```

Reused by stems / subtitle / music-mix. Atomic write (temp file → `os.replace`) — see codex review N2.

- [ ] **Step 2: `stems.separate(raw_mp4, device, chunk_min, force) -> StemsResult`**

```python
@dataclass
class StemsResult:
    bv_dir: Path             # <dir>/<bv>/
    speech_wav: Path         # bv_dir/speech.wav
    music_wav: Path          # bv_dir/music.wav
    sfx_wav: Path            # bv_dir/sfx.wav
    no_music_wav: Path       # bv_dir/no_music.wav
    no_music_gain_txt: Path | None  # optional, song-remover writes it only when peak-normalization fires
    from_cache: bool
    elapsed_seconds: float
```

Behavior:
- Compute expected meta from `raw_mp4` (ffprobe duration + width/height + first-1MB sha256 + quality_label inferred from height).
- If `bv_dir/speech.wav` AND `bv_dir/.stems_source_meta.json` exist AND meta matches AND `force` is false → cache hit, return immediately.
- Otherwise, invoke song-remover via subprocess (see Step 3 below) and write the new sidecar.

Note: `bv_dir = raw_mp4.parent / raw_mp4.stem` — song-remover's natural output layout under `-o <parent>/`.

- [ ] **Step 3: Subprocess invocation**

```python
cmd = [
    "song-remover",
    str(raw_mp4.name),
    "-o", ".",                    # relative; we set cwd=raw_mp4.parent
    "--force",                    # always pass; cache check is upstream
    "--device", device,           # "remote" by default
]
if device == "remote" and chunk_min is not None:
    cmd.extend(["--chunk-min", str(chunk_min)])
subprocess.run(cmd, cwd=raw_mp4.parent, check=True, capture_output=True, text=True)
```

After it returns, assert `bv_dir/speech.wav` exists (and the other three); raise `RuntimeError` with the captured stderr otherwise.

- [ ] **Step 4: `video2yt-stems` CLI**

Args:
```
raw_mp4: positional
--device {cpu,mps,auto,remote}   # default 'remote'
--chunk-min N                    # default 5; song-remover ignores it unless --device=remote
--force                          # bypass cache + pass --force to song-remover
```

Output: `[video2yt-stems] success: <bv_dir>/speech.wav  elapsed=<N>s  from_cache=<bool>`.

**Register the script in this task** (deferred from T1):

```toml
# pyproject.toml
video2yt-stems = "video2yt.stems_cli:main"
```

- [ ] **Step 5: Tests in `tests/test_stems.py`**

Mock subprocess.run. Cover:
- Cache hit: pre-create `speech.wav` + a matching `.stems_source_meta.json`; assert subprocess NOT invoked, `from_cache=True`.
- Cache miss (missing sidecar): assert subprocess invoked with the right argv, sidecar is written after.
- Stale sidecar (different sha256): assert subprocess invoked, sidecar updated.
- `--force` regardless of cache state.
- Argv contains `--remote` only when `--device remote`.
- Argv contains `--chunk-min N` only when `--device remote`.
- Raises with informative message when `speech.wav` doesn't exist after subprocess returns.

- [ ] **Step 6: Preflight check in `stems_cli.preflight()`**

`shutil.which("song-remover")` must succeed; otherwise print install instructions (point at the CLAUDE.md doc paragraph) and exit 2.

**Definition of Done:**
- All tests in `tests/test_stems.py` pass.
- Manual smoke: `uv run video2yt-stems temp/<dir>/<bv>.mp4` produces `<bv>/speech.wav` and the sidecar. (Skip if no Modal setup yet; rely on mocked tests.)
- `uv run pytest` full suite passes.
- Commit: `feat(stems): add video2yt-stems wrapping song-remover with meta-sidecar cache`

---

## Task 4: Refactor `subtitle.py` to consume `speech.wav` + close the cache-invalidation chain

**Spec section:** §4 Stage 3, §7 `video2yt-subtitle`, §11 Q9 (Stage 3 sub-bullet).

**Files:**
- Modify: `src/video2yt/subtitle.py`, `src/video2yt/subtitle_cli.py`
- Modify: `tests/test_subtitle.py`

- [ ] **Step 1: Wire sibling-lookup for `<bv>/speech.wav`**

In `subtitle_cli.run(args)`, after the existing `validate.probe(args.segment)` call (which gives width/height):

```python
bv_dir = args.segment.parent / args.segment.stem
speech_wav = bv_dir / "speech.wav"
if not speech_wav.exists():
    _log(f"missing required stem: {speech_wav} — run `video2yt-stems` first")
    sys.exit(2)
```

Remove the today's `vocals_sidecar = args.segment.with_name(f"{args.segment.stem}.vocals.wav")` line entirely. Anywhere subtitle.py used to consume the vocals sidecar — silencedetect, ASR — now consumes `speech_wav`.

- [ ] **Step 2: Close the cache-invalidation chain via `.speech_source_meta.json`**

At the top of the cache-check region (currently the `if raw_srt_path.exists() and not args.force_asr:` block), insert:

```python
meta_path = bv_dir / ".speech_source_meta.json"
expected = {"sha256": meta.compute_first_1mb_sha256(speech_wav)}
if not meta.meta_matches(meta_path, expected):
    _log("speech.wav changed since last run — invalidating ASR + cleanup caches")
    raw_srt_path.unlink(missing_ok=True)
    for stale in bv_dir.glob("speech.cleaned.*.srt"):
        stale.unlink()
    meta.write_meta(meta_path, expected)
```

This is the **single point** of stems→subtitle cache invalidation. Glob covers all threshold variants (not just the current run's `--threshold` — see codex stop-hook finding 2026-05-24).

- [ ] **Step 3: Output an ASS file alongside the SRT**

After today's `cleaned_srt_path.write_text(...)` call, immediately convert to ASS via `compose.srt_to_ass`:

```python
cleaned_ass_path = bv_dir / "speech.cleaned.ass"
compose.srt_to_ass(
    srt_path=cleaned_srt_path,
    ass_path=cleaned_ass_path,
    video_width=info.width,
    video_height=info.height,
    font_size=args.font_size,            # auto-derived above
    margin_v=args.margin_v,
    outline_px=args.outline_px,
    shadow_px=args.shadow_px,
    position="bottom",
)
```

`speech.cleaned.ass` is cheap (sub-second); always rebuilt, no cache.

- [ ] **Step 4: Remove detection-logic branches**

Drop the danmaku-XML scan, OCR sample, and `--force-add` / `--force-skip` flag handling. They're orchestrator-level concerns now (orchestrator's `--no-subtitle` flag does the per-segment toggle).

- [ ] **Step 5: Update `tests/test_subtitle.py`**

Drop the detection-logic tests. Add:
- **`test_missing_speech_wav_errors`** — fixture has `<bv>.mp4` but no `<bv>/speech.wav`; CLI exits non-zero with the expected message.
- **`test_silencedetect_runs_on_speech_wav`** — assert the mocked silencedetect subprocess receives `<bv>/speech.wav` as input, not a vocals sidecar.
- **`test_speech_source_meta_written_first_run`** — empty cache, runs ASR, sidecar present after.
- **`test_stale_speech_source_meta_invalidates_all_cleanup_caches`** — fixture has `speech.raw.srt`, `speech.cleaned.p0p6.srt`, `speech.cleaned.p0p8.srt`, and a sidecar with mismatching sha256; after run, the raw.srt is regenerated and **both** cleaned.*.srt files are gone, replaced by the current-threshold one.
- **`test_warm_run_skips_asr_and_cleanup`** — sidecar matches, raw.srt + current-threshold cleaned.p<th>.srt present; assert ASR + cleanup subprocesses NOT invoked.

**Definition of Done:**
- `tests/test_subtitle.py` updated as above, all tests pass.
- `uv run pytest` full suite passes.
- Manual smoke (if local song-remover + a real segment available): `uv run video2yt-subtitle temp/<dir>/<bv>.mp4` produces `<bv>/speech.cleaned.ass`.
- Commit: `feat(subtitle): consume speech.wav from stems + chain-invalidate caches via meta sidecar`

---

## Task 5: Extract `music_mix.py` from `music_swap.py`

**Spec section:** §4 Stage 4, §7 `video2yt-music-mix`, §11 Q9 (Stage 4 sub-bullet).

**Files:**
- Create: `src/video2yt/music_mix.py`, `src/video2yt/music_mix_cli.py`, `tests/test_music_mix.py`

- [ ] **Step 1: Carve out the bed-build path**

From today's `music_swap.py`, copy (don't move yet — music_swap.py stays alive until Task 9) into `music_mix.py`:
- `build_music_bed(...)` and any private helpers it calls.
- The CC0 credits-text writer.

Drop everything Demucs/no_vocals/music-detect/silence-gate-related. The new function shape:

```python
def render(
    raw_mp4: Path,
    out_bed: Path,             # <bv>.music_bed.wav
    out_credits: Path,         # <bv>.music_credits.txt
    force: bool = False,
) -> MusicMixResult:
    ...
```

- [ ] **Step 2: `<bv>.music_bed_meta.json` sidecar**

Same pattern as Task 3. Cache check: if `out_bed` exists AND `out_credits` exists AND the sidecar's recorded duration matches the current `raw_mp4` duration → skip; else rebuild.

- [ ] **Step 3: `video2yt-music-mix` CLI**

Args:
```
raw_mp4: positional
--force
```

Output: `[video2yt-music-mix] success: <out_bed>  duration=<N>s  tracks_used=<M>  from_cache=<bool>`.

**Register the script in this task** (deferred from T1):

```toml
# pyproject.toml
video2yt-music-mix = "video2yt.music_mix_cli:main"
```

- [ ] **Step 4: Tests in `tests/test_music_mix.py`**

Mock `subprocess.run` (the ffmpeg concat invocation) and `music_library.select_tracks_for_duration`. Cover:
- Cache hit when both outputs + sidecar match duration.
- Cache miss when sidecar duration ≠ current `raw_mp4` duration.
- Cache miss when sidecar is absent (first run).
- Credits text contains exactly the manifest attribution lines for the chosen tracks.

**Definition of Done:**
- `tests/test_music_mix.py` passes.
- `uv run pytest` full suite passes.
- Commit: `feat(music-mix): extract video2yt-music-mix from music-swap bed-build path`

---

## Task 6: Extend `burn.py` for the combined single-pass burn

**Spec section:** §4 Stage 5, §6, §11 Q4 (chained ASS — verified by codex).

**Files:**
- Modify: `src/video2yt/burn.py`
- Create: `src/video2yt/burn_cli.py`, `tests/test_burn_all.py`

- [ ] **Step 1: Extend `_build_filter_complex` signature**

New signature (additive — existing callers pass new params as defaults):

```python
def _build_filter_complex(
    keep_ranges: list[tuple[float, float]] | None,
    danmaku_ass_filename: str,
    speed: float = 1.0,
    cleaned_ass_filename: str | None = None,    # NEW — second subtitles=
    speech_input_index: int | None = None,      # NEW — ffmpeg input # for speech.wav, e.g. 1
    music_bed_input_index: int | None = None,   # NEW — ffmpeg input # for music_bed.wav, e.g. 2
) -> str:
    ...
```

Behavior:
- When `cleaned_ass_filename is None`: video chain has one `subtitles=` filter (today's behavior).
- When both `speech_input_index` and `music_bed_input_index` are set: emit the audio chain from spec §6 (Stage A0 normalize → Stage A1 cut → Stage A2 sidechain-amix → Stage A3 speed). Output label `[aout]`.
- When neither audio index is set: emit the today's passthrough `[0:a] (cut) (atempo)` chain. Output label `[aout]`.
- Final output labels are always `[vout]` and `[aout]`.

- [ ] **Step 2: Update `burn.render`**

Add args matching the spec §4 Stage 5 contract:
- `cleaned_ass`: optional path to `<bv>/speech.cleaned.ass` (becomes `<bv>.cleaned.ass` after symlink).
- `speech_wav`: optional path to `<bv>/speech.wav`.
- `music_bed_wav`: optional path to `<bv>.music_bed.wav`.
- `apply_music_swap`: bool — when False, original `<bv>.mp4` audio passes through (`--no-music-swap` orchestrator flag).
- `apply_subtitle`: bool — when False, `cleaned_ass` is ignored (`--no-subtitle`).

Pre-flight inside `render`:
1. If `cleaned_ass` is provided and `apply_subtitle`: symlink `<bv>/speech.cleaned.ass` → `<bv>.cleaned.ass`. Use `Path.symlink_to`; fall back to `shutil.copy` on systems where symlink fails. The symlink lives in `video_path.parent` so the cwd-with-basename trick works.
2. If `keep_ranges` is non-empty: produce ephemeral `<bv>.danmaku.cut.ass` (and `<bv>.cleaned.cut.ass` if applicable) via `cuts.rewrite_ass_for_cuts`. After ffmpeg returns, delete them.

Output args additions (codex review B5):

```python
"-c:v", "libx264", "-preset", "medium", "-crf", "20",
"-pix_fmt", "yuv420p", "-r", "30",          # for merge strict mode
"-c:a", "aac", "-b:a", "160k", "-ar", "48000",  # consistent with speech.wav 48k
```

The `-c:a copy` fast path is gone (we always amix audio).

- [ ] **Step 3: `video2yt-burn` CLI**

Args:
```
temp_dir: positional      # the <dir>/ that contains <bv>.mp4 etc.
--bv BV_ID                # required
-o / --output PATH        # final output path
--cut START~END           # repeatable
--speed FLOAT             # default 1.0
--preview-seconds N
--no-subtitle
--no-music-swap
```

Output: `[video2yt-burn] success: <output>  elapsed=<N>s`.

**Register the script in this task** (deferred from T1):

```toml
# pyproject.toml
video2yt-burn = "video2yt.burn_cli:main"
```

- [ ] **Step 4: Tests in `tests/test_burn_all.py`**

Pure-string assertions on `_build_filter_complex` output. Cover the 16-way matrix (cuts y/n × speed=1.0/!=1.0 × cleaned y/n × music-swap y/n). For each, assert:
- Final labels are `[vout]` and `[aout]`.
- When music_swap is on: graph contains `aresample=48000`, `sidechaincompress`, `amix`.
- When music_swap is off: graph references `[0:a]` not `[1:a]`/`[2:a]`.
- When cleaned subtitle is on: two `subtitles=f='...'` filters chained.
- When cleaned subtitle is off: exactly one `subtitles=f='...'`.
- When speed != 1.0: `setpts=PTS/<speed>` and `atempo=<speed>` are present.
- When cuts: `trim`/`atrim` for the correct number of ranges; `concat` count matches.

Add one **subprocess-mocked end-to-end** test that calls `burn.render` with all combinations enabled, asserting ffmpeg argv contains `-pix_fmt yuv420p`, `-r 30`, `-ar 48000`, and that the symlink + ephemeral cut files are cleaned up after.

**Definition of Done:**
- All `test_burn_all.py` tests pass.
- `uv run pytest` full suite passes.
- Manual smoke (real ffmpeg, real 30s clip): chained two-ASS render produces an mp4 that contains both subtitle layers; mark this off as the "codex review N3 owed test".
- Commit: `feat(burn): single-pass danmaku+subtitle+amix in one filter_complex`

---

## Task 7: Orchestrator — wire `cli.py` to the five stages

**Spec section:** §7 `video2yt <url>` (orchestrator), N5 skip-flag contracts.

**Files:**
- Modify: `src/video2yt/cli.py`
- Modify: `tests/test_smoke.py`

- [ ] **Step 1: Replace `cli.run` body with a thin five-stage loop**

```python
def run(args):
    _log_phase_start("fetch")
    fetch_result = fetch.fetch_and_build(args.url, ...)
    _log_phase_end("fetch", fetch_result.elapsed)

    if not args.no_music_swap or not args.no_subtitle:
        _log_phase_start("stems")
        stems_result = stems.separate(fetch_result.raw_video, device=args.device, chunk_min=args.chunk_min, force=False)
        _log_phase_end("stems", stems_result.elapsed)

    if not args.no_subtitle:
        _log_phase_start("subtitle")
        subtitle_cli.run_for_segment(fetch_result.raw_video, ...)
        _log_phase_end("subtitle")

    if not args.no_music_swap:
        _log_phase_start("music-mix")
        music_mix.render(fetch_result.raw_video, ...)
        _log_phase_end("music-mix")

    _log_phase_start("burn")
    burn.render(
        video_path=fetch_result.raw_video,
        ass_path=fetch_result.danmaku_ass,
        cleaned_ass=(bv_dir / "speech.cleaned.ass") if not args.no_subtitle else None,
        speech_wav=(bv_dir / "speech.wav") if not args.no_music_swap else None,
        music_bed_wav=(temp_dir / f"{bv_id}.music_bed.wav") if not args.no_music_swap else None,
        apply_subtitle=not args.no_subtitle,
        apply_music_swap=not args.no_music_swap,
        keep_ranges=keep_ranges,
        speed=args.speed,
        ...
    )
    _log_phase_end("burn")
```

- [ ] **Step 2: Flag passthrough**

Add to `argparse`:
- `--no-subtitle` (default False)
- `--no-music-swap` (default False)
- `--device {cpu,mps,auto,remote}` (default `remote`)
- `--chunk-min N` (default 5)

Existing flags (`--cut`, `--speed`, `--preview-seconds`, `--quality`, `--codec`, `--font-size`, `--font-face`, `--keep-temp`) stay; their semantics are unchanged.

- [ ] **Step 3: Output filename**

The final output goes to `output/<project>/<dir>/<bv>_final.mp4`. Update `_build_output_filename` to drop the `_with_danmaku`, `_clean`, `_subbed` legacy suffixes (the design replaces all of them with a single `_final.mp4`). Keep `_cut`, `_<speed>x`, `_preview` suffixes — those describe what's IN the output, not the pipeline stage.

- [ ] **Step 4: Smoke test in `tests/test_smoke.py`**

Append:
- **`test_orchestrator_runs_all_five_stages_in_order`** — mock every stage's `render`/`separate` function (not subprocess) and assert call order.
- **`test_orchestrator_skips_stems_subtitle_music_mix_under_no_subtitle_and_no_music_swap`** — pass both flags; assert only fetch + burn fire.
- **`test_orchestrator_passes_no_music_swap_to_burn`** — verify burn.render receives `apply_music_swap=False`.

Drop today's music_swap-related smoke tests in this same task (they're testing the removed flow).

**Definition of Done:**
- All orchestrator tests pass.
- `uv run video2yt <url> -o /tmp/test/` on a real short clip produces `<bv>_final.mp4` and works end-to-end (manual; this is the system-level proof).
- `uv run pytest` full suite passes.
- Commit: `feat(cli): orchestrate the new five-stage pipeline`

---

## Task 8: Delete the old music-swap path

**Files:**
- Delete: `src/video2yt/music_swap.py`, `src/video2yt/music_swap_cli.py`, `src/video2yt/music_detect.py`
- Delete: any test file dedicated to music_swap (today they live in `test_smoke.py`; the relevant tests should already be removed by Task 7).
- Modify: `pyproject.toml`

- [ ] **Step 1: Verify no remaining importers**

```bash
grep -nR "music_swap\|music_detect" src/ tests/
```

Expected: only matches inside the files about to be deleted. If any other file still imports, fix that first.

- [ ] **Step 2: Delete files**

```bash
git rm src/video2yt/music_swap.py src/video2yt/music_swap_cli.py src/video2yt/music_detect.py
```

- [ ] **Step 3: Drop the `video2yt-music-swap` console script**

In `pyproject.toml`, remove the `video2yt-music-swap = ...` line.

- [ ] **Step 4: Drop dependencies that were only used by the deleted path**

```bash
uv remove demucs torchaudio soundfile
```

(Verify with `grep -nR "demucs\|torchaudio\|soundfile" src/ tests/` first — if anything else still imports them, leave them in and note the surprise.)

- [ ] **Step 5: Full suite**

```bash
uv run pytest
uv run mypy src/
```

Both green.

**Definition of Done:**
- Three files deleted, one script entry removed, three deps removed.
- Full pytest + mypy pass.
- Commit: `chore(step6): remove obsolete music-swap path and Demucs deps`

---

## Task 9: Update CLAUDE.md and the workflow spec

**Files:**
- Modify: `CLAUDE.md`
- Modify: `docs/superpowers/specs/2026-04-18-video-production-workflow.md`

- [ ] **Step 1: Rewrite CLAUDE.md "Commands" section**

Replace the per-segment example commands with:
```bash
uv run video2yt "<url>" -o output/<project>/                          # full pipeline (stems via Modal by default)
uv run video2yt "<url>" -o output/<project>/ --no-subtitle            # skip STT subtitle
uv run video2yt "<url>" -o output/<project>/ --no-music-swap          # keep original audio
uv run video2yt "<url>" -o output/<project>/ --device cpu             # local CPU separation (slow)
uv run video2yt-fetch "<url>" -o output/<project>/                    # only download + danmaku ASS
uv run video2yt-stems temp/<dir>/<bv>.mp4                             # only run song-remover
uv run video2yt-subtitle temp/<dir>/<bv>.mp4                          # only run STT (requires stems first)
uv run video2yt-music-mix temp/<dir>/<bv>.mp4                         # only build music bed
uv run video2yt-burn temp/<dir>/ --bv <bv> -o <output>                # only do the burn
```

- [ ] **Step 2: Update "Architecture" section**

Replace the today's per-segment pipeline ASCII flow with the new five-stage one (the design doc §4 diagram is the source of truth — adapt it for CLAUDE.md's compact style).

- [ ] **Step 3: Update "Known gotchas"**

- Remove music-swap-specific gotchas (`soundfile` install requirement, vocal-gate threshold, Demucs MPS perf note).
- Add: "song-remover `--device remote` requires one-time Modal setup; falls back to `cpu` if Modal isn't configured (or fails loudly — pick one in stems.py implementation)".
- Add: "Stage 3 cache uses `<bv>/.speech_source_meta.json` — if you manually replace `speech.wav`, the next run regenerates ASR + cleanup automatically; if you manually edit `speech.raw.srt`, delete the sidecar to force a rerun".
- Keep the ffmpeg-with-libass requirement, the cut-boundary dialogue-drop, the Bilibili VIP-locked 1080p note.

- [ ] **Step 4: Update `docs/superpowers/specs/2026-04-18-video-production-workflow.md`**

In Step 6, collapse the today's "Step 6 / Step 6.5 / Step 6.6" trio into a single Step 6 referencing the new five-stage pipeline:

```
### Step 6 — Burn N Bilibili segments (5-stage pipeline)

[brief paragraph describing the new flow]

Per-streamer toggle table reused from today's Step 6.6 (郭楓荷 → --no-subtitle; everyone else → default).
```

Don't rewrite the whole workflow spec — just this one step. Mark the 6.5 and 6.6 sub-steps as folded into Step 6 with a brief migration note.

**Definition of Done:**
- CLAUDE.md reads correctly; `uv run video2yt --help` matches the documented commands.
- The workflow spec's Step 6 is single, coherent, and accurate.
- Commit: `docs(step6): refresh CLAUDE.md and workflow spec for new pipeline`

---

## Task 10: Real-ffmpeg integration smoke (codex review N3)

**Spec section:** §11 Q4 (codex verified chained subtitles locally; full graph still not exercised).

**Files:**
- Create: `tests/test_burn_real_ffmpeg.py` — gated by an env var or pytest marker so it doesn't run in normal CI but can be invoked explicitly.

- [ ] **Step 1: Generate test fixtures on-the-fly**

```python
import pytest
@pytest.fixture
def tiny_mp4(tmp_path):
    # generate a 5s color bar mp4 via ffmpeg
    ...

@pytest.fixture
def tiny_ass(tmp_path):
    # write a minimal valid ASS with one Dialogue line
    ...
```

- [ ] **Step 2: One end-to-end test**

```python
@pytest.mark.skipif(not _has_libass_ffmpeg(), reason="ffmpeg with libass not on PATH")
def test_burn_with_two_ass_layers_and_amix(tiny_mp4, tiny_ass, tmp_path):
    # build two ASS files, two short wavs, invoke burn.render with everything on, assert exit 0
    # and the output mp4 has video + audio streams (ffprobe).
```

That single test covers what codex N3 calls out as "owed": real ffmpeg + chained subtitles + the full audio chain.

- [ ] **Step 3: Document how to run**

In `CLAUDE.md` "Commands" section, add:
```
uv run pytest tests/test_burn_real_ffmpeg.py  # opt-in, requires ffmpeg with libass
```

**Definition of Done:**
- `uv run pytest tests/test_burn_real_ffmpeg.py` passes on the user's local ffmpeg 8.x + libass build.
- The test stays skipped under environments without libass (don't break CI).
- Commit: `test(burn): add opt-in real-ffmpeg smoke for two-ASS + amix`

---

## Task 11: Production validation

This is a manual checklist, not a code task. Do it after Task 10's commit lands.

- [ ] **Step 1: Pick a real Bilibili segment** that's already been processed under the old pipeline (so we have a known-good reference). Suggest the `mooniron` segment that just shipped.

- [ ] **Step 2: Run the new pipeline end-to-end**

```bash
uv run video2yt "<url>" -o output/regression-test/ --quality 1080
```

- [ ] **Step 3: A/B compare**

- Visual: scrub through both files at 0:00, 5:00, 10:00; danmaku timing identical, subtitle timing identical.
- Audio: confirm voice is clear, music bed is present at the same volume profile as the old pipeline.
- ffprobe: assert 1920×1080 30fps h264 yuv420p + AAC 48k stereo (for merge strict mode compatibility).
- File size: rough parity with the old pipeline (±20%).
- Wall-clock: log per-phase timings; confirm total is in the expected band (§12 §spec table).

- [ ] **Step 4: If anything diverges**, file an issue with the divergence; do not ship until resolved.

- [ ] **Step 5: Document the regression test in the spec's verification log** (the existing §7 table in `2026-04-18-video-production-workflow.md`).

**Definition of Done:**
- Regression mp4 matches expectations.
- Workflow spec verification log has a new row for this regression run.
- Commit: `chore(workflow): log step6-restructure regression run`

---

## Out-of-scope (deferred to follow-up plans)

- **Atomic writes everywhere** (codex review N2). The meta-sidecar atomic write lands in Task 3; extending atomic writes to all stage outputs is a follow-up.
- **`no_music_gain.txt` propagation through to a credits sidecar** (codex review N4 — already handled at the "preserve on disk" level by Task 3, no further propagation needed unless we surface gain in the final video credits).
- **Modal one-time setup automation** — the install steps stay manual for now; if a fresh-machine setup is needed often, write a `make modal-bootstrap` target later.

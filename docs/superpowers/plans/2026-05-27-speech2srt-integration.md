# speech2srt integration — Stage 3 cutover plan

**Date:** 2026-05-27
**Spec parent:** none (this plan is the spec)
**Codex review status:** v3 (v1 + v2 review feedback 2026-05-27 fully addressed; awaiting v3 sign-off before T1)
**Related:**
- `~/code/speech2srt/README.md` (the tool being integrated)
- `docs/superpowers/specs/2026-05-24-step6-restructure.md` §4 Stage 3 (current Stage 3 design — being replaced)
- `/Users/jun/.claude/projects/-Users-jun-code-video2yt/memory/project_stt_improvement_followup.md` (the deferred follow-up this plan resolves)

## Goal

Replace Stage 3 of the five-stage `video2yt` pipeline. The current Stage 3 runs `whisperx` ASR on speech.wav, applies a `ffmpeg silencedetect`-based pause-split workaround, then calls `codex exec` with a YAML glossary to clean terminology. The pause-split workaround produces a "one-character-per-frame" artifact because whisperx is called without `whisperx.align()` and only emits coarse segment-level timestamps.

After this cutover, Stage 3 runs a single subprocess: `speech2srt --cleanup --context-file <per-project ctx> --max-line-chars N -o <bv>/speech.cleaned.srt <bv>/speech.wav`. `speech2srt` does its own ASR via Volcengine 豆包 Seed-ASR (real word-level timestamps), its own codex cleanup with a free-form `--context` string, and its own line splitting at word boundaries. video2yt-subtitle then converts that SRT to ASS via existing `compose.srt_to_ass` and writes `<bv>/speech.cleaned.ass` — the Stage 5 burn contract is unchanged.

## Architecture

```
BEFORE (Stage 3) ────────────────────────────────────────────────────────
  <bv>/speech.wav
    │
    ├─► whisperx large-v3 (CPU, segment-level only)  → speech.raw.srt
    │   (~8 min on 17-min segment)
    ├─► ffmpeg silencedetect (find pauses ≥0.6s)
    │
    ├─► _split_segments_on_silences (proportional text distribution)
    │
    └─► codex exec + bg_glossary.yaml                → speech.cleaned.p0p6.srt
        (~13 min cold)                                  (threshold-keyed)
                                                                │
        video2yt's own split_segments + _apply_hard_floor (max_line_chars)
                                                                │
        compose.srt_to_ass                            → <bv>/speech.cleaned.ass
                                                                │
                                                        Stage 5 (burn) consumes

AFTER (Stage 3) ─────────────────────────────────────────────────────────
  <bv>/speech.wav
  <project>/subtitle_context.txt (explicit, per-project, threaded via flag)
    │       │
    └──► speech2srt --cleanup --context-file <ctx> --max-line-chars N
                    --force -o <bv>/speech.cleaned.srt <bv>/speech.wav
         (internal: Volcengine Seed-ASR ─► codex+context cleanup
                    ─► word-level-aware line splitter)
                                                                │
         compose.srt_to_ass (unchanged)                → <bv>/speech.cleaned.ass
                                                                │
                                                        Stage 5 (burn) consumes
```

## Non-goals

- **Stage 5 (burn) contract is frozen.** This plan must not touch `burn.py`, `burn_cli.py`, or anything downstream of `<bv>/speech.cleaned.ass`. The ASS file's contents may differ (better timing) but the contract — path, basic ASS format, dialogue-line structure — does not.
- **No backfill of already-shipped segments.** `output/redchroma/`, `output/mooniron/`, `output/zaige/` stay as-is.
- **No changes to Stage 1 fetch, Stage 2 stems, or Stage 4 music-mix.**
- **No new Python deps.** `speech2srt` is invoked as a subprocess (uv tool install pattern, same as song-remover).
- **No backwards-compat alias for `--glossary`.** speech2srt v0.3.0 dropped it; we do too.
- **`whisperx` stays as a project dependency** — it is still used by `src/video2yt/transcribe.py` for the intro-SRT alignment (Step 4 of the production workflow). T6 from the v1 plan (drop whisperx dep) is removed. We only stop using it from Stage 3.
- **No migration of `video2yt-transcribe`** to speech2srt. Out of scope.

## Per-project context file — explicit flag, no sibling fallback

User instruction: "T2 的 context 每次要根据这个视频的主播和流派，context 单独生成传入" — context is **per-video**, hand-authored per project, not a packaged default.

**Codex v1 review caught a flaw in the v1 plan's sibling-fallback:** the v1 plan claimed `<segment>.parent` would be the project folder, but in the actual full-pipeline flow the orchestrator passes `temp/<dir>/<bv>.mp4` to subtitle_cli (`cli.py:281`), so `<segment>.parent` is the TEMP dir — not where a user would author `subtitle_context.txt`. v2 removes the sibling fallback entirely.

**Resolution order in `video2yt-subtitle` (v2):**
1. Explicit `--context-file PATH` flag → use it. Error (exit 2, FileNotFoundError) if missing.
2. No flag and `--skip-cleanup` is also NOT set → speech2srt is invoked with `--cleanup` but no `--context-file`. Print a clearly-worded WARNING to stderr explaining quality will be lower.
3. `--skip-cleanup` set → neither `--cleanup` nor `--context-file` go on the speech2srt argv.

**Orchestrator wiring:** `video2yt` (full pipeline) gets a matching `--subtitle-context-file PATH` flag. When set, the orchestrator threads it to `video2yt-subtitle` via the lazy-import argv. When `--no-subtitle` is set, the orchestrator silently ignores the flag (no warning).

**Authoring convention:** users write `output/<project>/subtitle_context.txt` (per-project, beside `intro.mp4` etc.) and pass it via `--subtitle-context-file` on each `video2yt <url>` invocation. Workflow spec updated in T7 to document this.

## Tasks

Each task lists Goal → Tests → DoD → Status. Codex review happens after each task; agreement gate before moving on.

---

### T1 — Install speech2srt + smoke test against a real wav
**Status:** Not Started
**Goal:** `speech2srt` CLI is on `$PATH` via `uv tool install`. The argv we plan to use (T3) is validated against a real `speech.wav` from an existing project.
**Tests:** None (one-time op).
**Verification:**
1. `cd ~/code/speech2srt && uv tool install . --force`
2. `speech2srt --version` exits 0 and prints a version.
3. Pick one existing `output/<project>/<bv>/speech.wav`. Author a short context file at `/tmp/speech2srt_smoke_context.txt` (~200-500 chars; B站UP主 + 炉石战棋 + a handful of terms). Run:
   ```
   speech2srt that.wav -o /tmp/test.srt --cleanup \
     --context-file /tmp/speech2srt_smoke_context.txt \
     --max-line-chars 18 --force -v
   ```
   (Smoke uses `--context-file` — same flag T3's locked argv contract uses — instead of inline `--context`, to exercise the actual integration path.)
4. Confirm exit 0, `/tmp/test.srt` is well-formed, char count and ¥ cost printed to stderr.
**DoD:** Manual smoke succeeds; record the exact wall-clock + character count in the commit message of the next task.

---

### T2 — Wire `--context-file` flag through subtitle_cli AND orchestrator
**Status:** Not Started
**Goal:** New `--context-file PATH` flag on `video2yt-subtitle`; matching `--subtitle-context-file PATH` flag on `video2yt` orchestrator that threads to subtitle_cli. No sibling fallback. Combined with v1's T7 (orchestrator threading) so full-pipeline runs work the same day T3 lands.
**Tests (write first):**
1. `test_subtitle_cli_context_file_flag_threads_to_speech2srt_argv` — `--context-file /tmp/ctx.txt` ends up on speech2srt argv as `--context-file /tmp/ctx.txt`.
2. `test_subtitle_cli_explicit_context_file_missing_raises_exit_2` — `--context-file /does/not/exist.txt` → `FileNotFoundError` → exit 2.
3. `test_subtitle_cli_no_context_file_and_cleanup_on_emits_warning` — no flag, `--skip-cleanup` not set: stderr contains "no context file"; speech2srt argv has `--cleanup` but no `--context-file`.
4. `test_subtitle_cli_skip_cleanup_omits_both_cleanup_and_context_file` — `--skip-cleanup` set: no `--cleanup` and no `--context-file` on argv, regardless of `--context-file` flag presence.
5. `test_subtitle_cli_explicit_context_file_wins_over_warning` — `--context-file ctx.txt` set: no warning emitted, argv has the path.
6. `test_orchestrator_threads_subtitle_context_file_to_subtitle_cli` — `video2yt ... --subtitle-context-file foo.txt` → patched `subtitle_cli.parse_args` receives `--context-file foo.txt`.
7. `test_orchestrator_subtitle_context_file_silently_ignored_when_no_subtitle` — `--no-subtitle --subtitle-context-file foo.txt` runs without error; subtitle_cli is not invoked; no warning.
**DoD:** All 7 tests pass; existing tests still pass. (Note: tests 1, 3, 4, 5 will run against a real speech2srt argv only after T3 wires it; T2 lands the flag-resolution helper but the argv assembly itself is in T3. T2 can use a stub argv-builder that exercises the helper.)
**Codex sub-gate before T3:** review the resolution helper + test design.

---

### T3 — Rewrite `subtitle_cli.run` to subprocess `speech2srt`
**Status:** Not Started
**Goal:** Replace the whisperx + silencedetect + codex internal chain with a single `speech2srt` subprocess. Output contract (`<bv>/speech.cleaned.ass`) preserved.

**Argv contract (locked):**
- Positional: `<bv>/speech.wav`
- `-o <bv>/speech.cleaned.srt` (kept on disk as a debug artifact — see T5 expected-artifacts list)
- `--cleanup` (unless `--skip-cleanup` set on our side)
- `--context-file <resolved-path>` (only when explicit `--context-file` provided on our side AND `--cleanup` is in effect)
- `--max-line-chars N` where `N = compose._effective_chars_per_line(font_size, video_width, margin_l=80, margin_r=80)` — same value the downstream ASS converter wraps at, verified consistent in codex v1 review (`compose.py:208`)
- `--force` (always — speech2srt's `--force` only authorizes `-o` overwrite, not cache; safe per codex v1 review)
- `--no-cache` is NOT used. (codex v1 review caught that speech2srt's `--no-cache` skips BOTH lookup AND store; "force regen with save" is not a single flag.)

**Flag removals on our side (parse_args):**
- `--force-cleanup` → removed
- `--glossary` → removed (replaced by `--context-file` in T2)
- `--pause-split-seconds` → removed
- `--force-asr` → kept, but reimplemented: deletes `<wav>.speech2srt.json` and `<wav>.speech2srt.srt` (speech2srt's canonical sidecar pair) BEFORE invoking speech2srt without `--no-cache`. Result: fresh ASR run that DOES re-populate the cache (which is what users actually want).
- `--skip-cleanup` → kept; omits `--cleanup` from argv (and therefore `--context-file` too)
- `--no-preview-burn` → kept (orchestrator passes it)
- `--font-face`, `--font-size`, `--outline-px`, `--shadow-px`, `--margin-v` → kept (drive ASS rendering, unchanged)

**Tests (write first):**
1. `test_cli_invokes_speech2srt_with_expected_argv` — argv contains every locked element above when explicit context-file + --cleanup default.
2. `test_cli_passes_max_line_chars_from_compose_helper` — `N == compose._effective_chars_per_line(font_size, info.width, 80, 80)`.
3. `test_cli_force_asr_deletes_speech2srt_sidecars_and_omits_no_cache` — `--force-asr`: confirm `<wav>.speech2srt.json` + `.srt` get unlinked AND `--no-cache` is NOT on argv.
4. `test_cli_force_asr_tolerates_missing_sidecars` — `--force-asr` on a cold run where sidecars don't exist yet → unlink calls don't raise; speech2srt still runs.
5. `test_cli_skip_cleanup_omits_cleanup_and_context_file` — `--skip-cleanup`: no `--cleanup` and no `--context-file` on argv.
6. `test_cli_reads_speech2srt_srt_output_and_writes_speech_cleaned_ass` — given a mocked speech2srt that writes a known SRT, the resulting ASS contains expected dialogue lines.
7. `test_cli_propagates_speech2srt_exit_code_3_auth_error` — speech2srt exit 3 → subtitle_cli exits 3.
8. `test_cli_propagates_speech2srt_exit_code_4_quota_error` — speech2srt exit 4 → subtitle_cli exits 4. (codex v1 review nice-to-have.)
9. `test_cli_preflight_checks_speech2srt_on_path` — patched `shutil.which("speech2srt")` returning None → exit 1 with "speech2srt not found".
10. ~~`test_cli_preflight_checks_VOLCENGINE_API_KEY_env_var`~~ → **dropped in T3 implementation**. VOLCENGINE_API_KEY validation is intentionally delegated to speech2srt (which loads `.env` from cwd, then exits 1 with `[speech2srt] preflight error: VOLCENGINE_API_KEY not set in env or .env`). subtitle_cli propagates that exit 1 unchanged. This avoids duplicating the env-var/`.env` discovery logic and lets one place own the contract. Tests #7 + #8 exercise speech2srt-exit-code propagation; that mechanism covers the missing-key case too.
11. `test_cli_no_preview_burn_skips_ffmpeg_burn` — `--no-preview-burn` set → no ffmpeg subprocess for the preview burn. (T3 dropped the legacy preview-burn entirely; test now asserts only the speech2srt subprocess fires.)
12. `test_cli_removed_flags_are_rejected_by_argparse` → **relocated to `test_parse_args_no_longer_accepts_legacy_flags`** (extends the existing detection-flags test rather than adding a parallel one). Covers `--force-cleanup`, `--glossary`, `--pause-split-seconds`.

**DoD:** All 12 tests pass; `subtitle_cli.run` is shorter (target ≤ 120 LOC).
**Codex sub-gate before T4:** review the diff against this argv contract.

---

### T4 — Delete dead Stage 3 code from `subtitle.py`
**Status:** Not Started
**Goal:** `subtitle.py` shrinks to only what's still consumed (in practice: nothing, so the module gets deleted).
**Symbols to remove:** `transcribe`, `_run_asr`, `_extract_wav`, `detect_silences`, `_split_segments_on_silences`, `cleanup_with_codex`, `_build_cleanup_prompt`, `_invoke_codex`, `load_glossary`, `Glossary`, `FunASRSegment`, `SrtEntry`, `segments_to_srt`, `parse_srt_to_segments`, `_format_srt_time`, `_parse_srt_time`, `split_segments`, `_split_one_recursive`, `_apply_hard_floor`, `_split_at_effective_midpoint`, `_split_by_punctuation`, `_is_useful_split`, `_allocate_time_proportionally`, `burn_subtitles`, `passthrough`, plus pre-existing dead detection chain (`scan_danmaku`, `sample_ocr`, `decide`, `DanmakuSignal`, `OcrSignal`, `Decision`, `_extract_frames`, `_split_mjpeg_stream`, `_run_rapidocr`, `BILIBILI_FIXED_DANMAKU_SECONDS`, `HARD_FLOOR_SECONDS`, `CLEANUP_TIMEOUT_SECONDS`, `SENTENCE_PUNCT`, `CLAUSE_PUNCT`).
**Codex v1 review noted:** the opportunistic deletion of pre-existing dead detection code is justified because: (a) the cli already rejects the detection flags (`tests/test_subtitle.py:887`), (b) the file is being gutted anyway. Verified-correct.
**Tests:** Delete entries in `tests/test_subtitle.py` that cover removed symbols. Keep new T2/T3 tests.
**DoD:**
- `grep -rE "from video2yt\.?subtitle\b|from video2yt import subtitle\b|import video2yt\.subtitle\b|video2yt\.subtitle\." src/ tests/` returns 0 lines outside the removal itself. (codex v1 review caught the v1 plan's grep missed the `from video2yt import subtitle` form; codex v2 review caught the bare `import video2yt.subtitle` form too.)
- If `subtitle.py` ends empty, delete the file.
- ruff + pytest green.

---

### T5 — Drop dead cache logic from `subtitle_cli.py`
**Status:** Not Started
**Goal:** Remove video2yt's own SRT cache layer; speech2srt owns its cache.
**Code to remove:** `_threshold_filename_suffix`, `_invalidate_subtitle_caches`, `.speech_source_meta.json` writes/reads, `speech.raw.srt` cache file path, threshold-keyed `speech.cleaned.{threshold}.srt` cache file paths.
**Stage-3-owned artifacts retained in `<bv>/` after a run (v2 reconciles the v1 T3/T5 conflict):**
- `speech.wav.speech2srt.json` (speech2srt's own cache sidecar; lives next to `speech.wav`)
- `speech.wav.speech2srt.srt` (speech2srt's canonical SRT cache)
- `speech.cleaned.srt` (T3's `-o` target; debug artifact, ~few KB)
- `speech.cleaned.ass` (Stage 5 contract; regenerated each run, sub-second)

`speech.cleaned.srt` is essentially a copy of `speech.wav.speech2srt.srt` (speech2srt's canonical) — useful for debugging without grepping for sidecar suffix. Roughly free.

Stage 2-owned artifacts (not touched by T5; listed here so the artifacts list isn't read as "everything in `<bv>/`"): `speech.wav`, `music.wav`, `sfx.wav`, `no_music.wav`, and `.stems_source_meta.json` — all per `stems.py` contract. Per CLAUDE.md user decision 2026-05-24, all four stems stay on disk after Stage 2 finishes.
**Tests:**
1. `test_cli_creates_no_speech_source_meta_sidecar` — `.speech_source_meta.json` does not exist after a run.
2. `test_cli_creates_no_raw_srt_in_bv_dir` — `speech.raw.srt` does not exist.
3. `test_cli_creates_no_threshold_keyed_cleaned_srt_in_bv_dir` — `speech.cleaned.p0p6.srt` etc. do not exist.
4. `test_cli_idempotent_when_speech2srt_cache_warm` — second run also subprocesses speech2srt; subtitle_cli's behavior is deterministic and BOTH `speech.cleaned.srt` AND `speech.cleaned.ass` are byte-equal to the first run. (codex v2 review nice-to-have — explicit SRT byte-equality too, not just ASS.)
**DoD:** Tests pass; `ls <bv>/` matches the artifacts-retained list above.

---

### ~~T6 — Remove whisperx + transitive deps from pyproject.toml~~
**Status:** REMOVED (v1 → v2)
**Reason:** Codex v1 review caught that `whisperx` is still imported by `src/video2yt/transcribe.py:210` (intro-SRT word-level alignment used by `video2yt-compose`) and `src/video2yt/transcribe_cli.py:22`. These power Step 4 of the production workflow — distinct from Stage 3 (subtitle on bilibili segments). The dep stays.
**Future work (separate plan, not in scope here):** if/when we migrate `video2yt-transcribe` away from whisperx, that future plan can drop the dep.

---

### T6 (was T7) — Update CLAUDE.md + workflow spec + memory
**Status:** Not Started
**Updates:**
1. `CLAUDE.md`:
   - Architecture diagram Stage 3 line: replace "whisperx+codex subtitle" with "speech2srt (火山 Seed-ASR + codex)".
   - External dependencies section: keep whisperx note (intro alignment), add `speech2srt` install line (`uv tool install ~/code/speech2srt`) and VOLCENGINE_API_KEY env var.
   - "Subtitle / whisperx" gotcha section: rename to "Subtitle / speech2srt", rewrite to cover: VOLCENGINE_API_KEY env var, ~2-3 min wall-clock per segment, privacy note (audio → 火山, cleanup → OpenAI), per-project `subtitle_context.txt` convention with `--subtitle-context-file` flag.
   - cli.py comment at line 277 (`# lazy: brings in whisperx`) → update to reflect speech2srt subprocess (no whisperx import from Stage 3 anymore).
2. `docs/superpowers/specs/2026-04-18-video-production-workflow.md` Step 6 Stage 3 row: rewrite to reflect speech2srt invocation; add a bullet about authoring `output/<project>/subtitle_context.txt`.
3. Memory:
   - **Delete** `project_stt_improvement_followup.md` (this plan resolves it; root fix shipped).
   - **Add** `project_speech2srt_canonical.md` documenting the new Stage 3 + the per-project context-file convention.
   - Update `MEMORY.md` index accordingly.
**DoD:** `grep -rE "whisperx" CLAUDE.md docs/superpowers/specs/2026-04-18-video-production-workflow.md` returns only the intentional intro-alignment mention; memory index reflects the swap.

---

### T7 (was T9) — Production verification on a recent project
**Status:** Not Started
**Goal:** Rerun Stage 3 on a real shipped segment, eyeball quality + record timing.
**Steps:**
1. Pick `output/redchroma/` (most recent shipped, easy comparison) or whatever the user prefers.
2. Author `output/redchroma/subtitle_context.txt` (≤ 2KB) describing redchroma streamers (郭楓荷, 瓦莉拉) + 紅龍流 / 紅色彩色龍 terms.
3. Pre-run cleanup for true cold path measurement:
   - `mv <bv>/speech.cleaned.ass <bv>/speech.cleaned.ass.before_speech2srt.bak` (backup, don't delete — A/B visual reference). Codex v1 review nice-to-have.
   - `rm -f <bv>/speech.wav.speech2srt.json <bv>/speech.wav.speech2srt.srt` (force speech2srt cold).
   - `rm -f <bv>/.speech_source_meta.json` (old-pipeline sidecar — harmless after T5, but explicit cleanup avoids confusion).
4. **Verify input shape:** the segment passed to `video2yt-subtitle` is a raw `<bv>.mp4` MP4 with a sibling `<bv>/speech.wav` (codex v1 review point — current CLI requires this at `subtitle_cli.py:169`). Confirm with `ls -la <segment_dir>/<bv>.mp4 <segment_dir>/<bv>/speech.wav`.
5. Run `uv run video2yt-subtitle <segment_dir>/<bv>.mp4 --context-file output/redchroma/subtitle_context.txt --no-preview-burn`.
6. Eyeball the resulting `<bv>/speech.cleaned.ass`. Expect proper sentence-level timing, no "one-char-per-frame" artifact.
7. Measure cold + warm wall-clock (rerun the command — should hit speech2srt cache and finish in seconds).
**DoD:** ASS file visibly improves over the backup; cold ~2-4 min, warm <5s; results recorded in the commit message.

---

## Codex review gates

- **Plan-level review** before T1 → THIS REVIEW (v2 awaiting agreement).
- **T2 sub-gate** before T3 (test design for the flag-resolution helper).
- **T3 sub-gate** before T4 (diff against the locked argv contract).
- After each subsequent task's commit → codex review the diff. Block the next task until consensus.
- After T7 → codex review of the entire integration delta.

## Risk + rollback

- **Volcengine API key not set / quota exhausted:** T3 preflight catches the missing env var; quota exhaustion surfaces as speech2srt exit code 4. Rollback is `git revert` of the T3 / T4 / T5 commits; whisperx-based Stage 3 code returns.
- **speech2srt subprocess hangs:** speech2srt has its own `--cleanup-timeout` (default 1200s); subtitle_cli sets a wider hard timeout (default 1800s) on the subprocess.run call to catch a wedged ASR.
- **Per-project context content is wrong:** speech2srt will fall back to raw ASR with a stderr warning; ASS still renders, just less clean. User adjusts `subtitle_context.txt` and reruns with `--force-asr` (deletes speech2srt sidecars to force regen).

## Changelog vs v1

| # | v1 → v2 change | Trigger |
|---|---|---|
| 1 | Drop sibling-fallback for context-file (was: `<segment>.parent / subtitle_context.txt`) — explicit `--context-file` only | Codex v1 Q1 BLOCKER — segment.parent is `temp/<dir>/` in the orchestrator, not the project folder |
| 2 | `--force-asr` reimpl: delete speech2srt sidecars; do NOT pass `--no-cache` | Codex v1 Q2a BLOCKER — `--no-cache` skips store too |
| 3 | Explicitly remove `--force-cleanup`, `--glossary`, `--pause-split-seconds` from argparse; add reject-test | Codex v1 Q2b BLOCKER — old flag semantics were unspecified |
| 4 | Reconcile: keep `<bv>/speech.cleaned.srt` on disk; update T5 expected-artifacts list | Codex v1 Q2c/Q4 BLOCKER — T3 wrote it but T5 said nothing in bv_dir |
| 5 | T4 grep uses `-E` and covers `from video2yt import subtitle` | Codex v1 Q3 BLOCKER — alternate import form |
| 6 | T6 (drop whisperx) removed — whisperx stays for transcribe.py | Codex v1 Q5 BLOCKER — transcribe.py still uses it |
| 7 | T7 (orchestrator threading) merged into T2 | Codex v1 Q7 — avoid window where full-pipeline runs lack context plumbing |
| 8 | T9 (verification) adds explicit input-shape check + backup-don't-delete the old ASS | Codex v1 Q6 nice-to-have + sanity |
| 9 | New T3 tests #8 (exit-4 propagation), #12 (rejected flags) | Codex v1 Q2 nice-to-have + Q2b plumbing |
| 10 | New review sub-gates after T2 and T3 | Codex v1 Q8 nice-to-have |

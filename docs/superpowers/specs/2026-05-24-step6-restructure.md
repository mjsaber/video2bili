# Step 6 Restructure — song-remover Stems + Single-Pass Burn

**Date**: 2026-05-24
**Status**: **SHIPPED 2026-05-25 + PARTIALLY SUPERSEDED 2026-05-27.** This spec defined the 5-stage pipeline, which is the canonical structure. However, **Stage 3 (subtitle) was rewritten in the speech2srt-integration plan** (`docs/superpowers/plans/2026-05-27-speech2srt-integration.md`) to shell out to the external `speech2srt` CLI instead of running whisperx + silencedetect + codex internally. Every Stage 3 reference in this doc — `subtitle.py`, `.speech_source_meta.json`, `speech.raw.srt`, threshold-keyed cleanup SRTs, the whisperx ASR + silencedetect pause-split chain — is historical only. Use the speech2srt-integration plan for current Stage 3 behavior. Stages 1/2/4/5 in this spec are still accurate.
**Target audience**: Future Claude agents implementing the rewrite; the user
reviewing the approach before code is written.

## 1. Goal

Replace the current three-step segment pipeline (`video2yt` → `video2yt-music-swap` → `video2yt-subtitle`) with a clean five-stage pipeline that:

1. Uses the new `song-remover` (Bandit-v2 4-stem separator at `~/code/song-remover`) to produce all four stems ONCE per segment, replacing the current Demucs-in-music-swap call. Downstream **consumes only** `speech.wav`; the other three remain on disk.
2. Approach A is preserved at the consumption layer — `speech.wav` is the only audio source for the final mix, so original game SFX is intentionally dropped along with the copyrighted BGM.
3. Burns danmaku ASS, subtitle ASS, **and** mixes the new audio bed in a **single ffmpeg pass** — eliminating one full video re-encode (~3 min/segment) and one intermediate ~1 GB mp4 file.
4. Caches at five well-defined stage boundaries (raw download, stems, SRT, music bed, final mp4), so any single stage can be rerun without redoing the slow ones.

The pipeline is a per-segment operation, the same scope as today's three-step chain.

## 2. Non-goals

- This does NOT change Step 1–5 (intro flow), Step 7 (merge), Step 8 (metadata), Step 9 (upload), or the Bonus thumbnail step.
- This does NOT change the `video2yt-compose` intro path, the `compose.srt_to_ass` styler, or the merge logic.
- This does NOT change the Bilibili download (`yt-dlp` invocation, danmaku XML retrieval, BV-id-based caching). Stage 1 is a refactor-extract of today's `download.fetch`, not a rewrite.
- This does NOT change the CC0 music library, manifest, attribution sidecar, or `music_library.py`.
- This does NOT introduce a new ASR engine, cleanup engine, or glossary — the speech.wav → SRT pipeline reuses the existing `whisperx` + Codex-cleanup logic in `subtitle.py`.
- Downstream stages (subtitle, burn) consume ONLY `speech.wav` from the stems folder. `music.wav` / `sfx.wav` / `no_music.wav` are not consumed by any later stage, but ARE preserved on disk (user 2026-05-24: "1.先都留我自己删" — keep all four, manual cleanup; matches today's raw-download cache convention).
- This does NOT preserve backwards compatibility with the existing `_clean.mp4`, `_subbed.mp4`, `_clean_subbed.mp4` intermediate files. After this lands, the only segment output is `<bv>_final.mp4`.

## 3. Locked design decisions

| Dimension | Decision | Rationale |
|---|---|---|
| Separator | `song-remover` Bandit-v2 multilingual CLI (`~/code/song-remover`), invoked as a subprocess. We only consume `speech.wav` from its output. | User-provided tool, designed for this stream/commentary use case; subprocess boundary keeps tests mockable like the current `subprocess.run`-mocking pattern. The Demucs path in `music_swap.py` is removed. |
| Default device | **`--remote`** (Modal serverless T4 GPU; song-remover commit `f3380d1`, 7.2× faster than local CPU). On a 4 min input: 3 min 39 s remote vs 26 min 18 s local CPU. On a 17 min input: ~12–15 min remote vs ~3 hours local CPU. One-time Modal setup (`modal token new`, `modal deploy ...`) documented in §7. | The new `--remote` flag (added in song-remover 2026-05-24) lifts the 11× realtime CPU regression to within striking distance of the current Demucs flow. Cost: ~$0.03-0.05 per 4 min, fits in Modal's $30/month free tier for personal use. |
| Speed expectation | Wallclock parity with current pipeline is achievable via `--remote`; the spec stays correct under local CPU as well (subprocess boundary is identical). | User confirmed remote-mode use is acceptable. |
| What we keep from stems | **All 4 stems remain on disk** in `temp/<dir>/<bv>/`. Downstream stages only **consume** `speech.wav`; the other three are kept for the user's manual inspection / cleanup. | User decision 2026-05-24: "1.先都留我自己删". Approach A trade-off (downstream uses only speech.wav, no SFX leaks into final audio) is preserved at the **consumption** layer; on-disk retention is independent. |
| Number of stages | Five small CLIs: `video2yt-fetch`, `video2yt-stems`, `video2yt-subtitle`, `video2yt-music-mix`, `video2yt-burn`. Plus an `video2yt` orchestrator that calls them in order (cache-aware). | song-remover is slow; cache boundaries must be explicit. Five small CLIs make partial reruns trivial. Orchestrator preserves the one-line UX (`uv run video2yt <url>`) for the common case. |
| Burn pass | **Single ffmpeg invocation** combining: danmaku ASS burn + cleaned subtitle ASS burn + speech/music-bed amix with sidechain ducking + (optional) cut/speed stages. | Avoids one full video re-encode (~3 min for 17 min input) and one intermediate ~1 GB mp4. ffmpeg can chain `subtitles=` filters and run audio mix in the same `-filter_complex`. |
| Subtitle file format used in burn | **Both danmaku and cleaned subtitles are ASS** by the time they reach the burn stage. `subtitle.py` already produces an ASS-via-`srt_to_ass`; danmaku is already ASS from biliass. | Two ASS files in one filter chain means all styling lives in the file (no `force_style=` overrides in the filter line, no SRT/ASS quoting differences). |
| Stems cache | `temp/<dir>/<bv>/` (song-remover's natural `<basename>/` output dir), siblings of the existing `<bv>.mp4` + `<bv>.danmaku.xml`. User deletes manually. | song-remover already creates `<basename>/` — adopting its layout avoids a rename step. Matches the current raw-download cache convention (manual cleanup); orchestrator skips song-remover when `<bv>/speech.wav` exists. |
| Cuts and speed | Both applied **inside the single burn pass** via the existing `_build_filter_complex` pattern. ASR runs on the **un-cut, un-sped speech.wav**; the burn stage maps the SRT timeline along with the video (subtitles burned BEFORE `setpts`, same as today's danmaku). | Preserves today's correct danmaku timeline behavior; same logic extends naturally to the cleaned SRT. Avoids needing to cut/speed audio twice. |
| The existing `_clean.mp4` / `_subbed.mp4` intermediates | Removed. The only segment artifact is `<bv>_final.mp4`. | These intermediates exist only because the current pipeline is three sequential ffmpeg passes. With one burn, they have no reason to exist. |
| The existing `music_swap.py` Demucs / no_vocals masking / music-detect / silence-gate logic | Deleted. The new `music_mix.py` is much smaller — it only builds the CC0 music bed from `music_library.py` and emits the bed wav for the burn stage to amix. | These all exist to compensate for Demucs's vocals-stem residual music. song-remover's `speech.wav` is the clean stem; the gating tax is gone. (If song-remover quality turns out worse than expected, we add gating back at that point, not preemptively.) |
| Test boundary | Mock at the `subprocess.run` boundary, same as today. song-remover CLI, ffmpeg, ffprobe, whisperx, Codex all mocked. | No new boundaries introduced. Existing test infra (`tests/test_*`) extends naturally. |

## 4. New per-segment pipeline

**Naming convention (matches existing `download.fetch` / `subtitle_cli` conventions):**
All per-segment artifacts live in `temp/<uploader_prefix>：<title>/` (referred to as `<dir>` below) and are prefixed with the BV id (`<bv>`). The only exception is the stems sub-folder, whose layout is dictated by song-remover itself.

```
Bilibili URL
  │
  ▼
┌─────────────────────────────────────────────────────────────┐
│ video2yt-fetch <url> -o temp/<dir>/                         │  Stage 1
│   yt-dlp → <bv>.mp4 + <bv>.danmaku.xml                      │
│   biliass → <bv>.danmaku.ass                                │
│   cache: skip yt-dlp if <bv>.{mp4,mkv,webm} + <bv>*.xml     │
│          present (same as today's download.fetch)           │
│          skip biliass if <bv>.danmaku.ass present           │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ temp/<dir>/{<bv>.mp4, <bv>.danmaku.xml, <bv>.danmaku.ass}
   │
┌─────────────────────────────────────────────────────────────┐
│ video2yt-stems temp/<dir>/<bv>.mp4                          │  Stage 2  (slow)
│   song-remover --device cpu <bv>.mp4 -o temp/<dir>/         │
│   → temp/<dir>/<bv>/{speech,music,sfx,no_music}.wav         │
│     (+ optional no_music_gain.txt — preserved, see §11 Q9)  │
│   ALL four stems kept on disk (user 2026-05-24 decision);   │
│   downstream stages consume only speech.wav.                 │
│   cache: skip if <bv>/speech.wav exists AND meta sidecar    │
│          matches current <bv>.mp4 (see §11 Q9)               │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ temp/<dir>/<bv>/speech.wav
   │
┌─────────────────────────────────────────────────────────────┐
│ video2yt-subtitle temp/<dir>/<bv>.mp4                       │  Stage 3
│   ffprobe <bv>.mp4 → width/height for ASS PlayResX/Y         │
│   read <bv>/speech.wav (sibling lookup, errors if missing)   │
│   silencedetect on speech.wav (NOT on a vocals sidecar —     │
│     speech.wav is the new direct STT input)                  │
│   whisperx ASR → pause-split → codex cleanup                 │
│   → <bv>/speech.raw.srt, <bv>/speech.cleaned.p0p6.srt,       │
│     <bv>/speech.cleaned.ass                                  │
│   cache check order:                                         │
│     1. If .speech_source_meta.json missing/mismatched:       │
│        delete speech.raw.srt AND **every** speech.cleaned.*.srt│
│        in <bv>/ (glob — covers all threshold variants, not    │
│        just the current run's threshold), then write the new  │
│        sidecar before ASR runs.                               │
│     2. Skip ASR if speech.raw.srt present (post-step-1).      │
│     3. Skip cleanup if speech.cleaned.p<th>.srt present       │
│        (threshold encoded in filename — see subtitle_cli).    │
│     4. cleaned.ass always rebuilt (cheap).                    │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ temp/<dir>/<bv>/speech.cleaned.ass
   │
┌─────────────────────────────────────────────────────────────┐
│ video2yt-music-mix temp/<dir>/<bv>.mp4                      │  Stage 4  (fast)
│   probe duration → build CC0 bed via music_library.py       │
│   → <bv>.music_bed.wav, <bv>.music_credits.txt              │
│   cache: skip if both present                                │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ temp/<dir>/{<bv>.music_bed.wav, <bv>.music_credits.txt}
   │
┌─────────────────────────────────────────────────────────────┐
│ video2yt-burn temp/<dir>/ --bv <bv> -o <output>             │  Stage 5
│   pre-flight: symlink <bv>/speech.cleaned.ass to            │
│     <bv>.cleaned.ass (or .cut.ass if --cut used; see §6)    │
│   single ffmpeg pass (cwd=temp/<dir>/, basenames only):     │
│     -i <bv>.mp4 -i <bv>/speech.wav -i <bv>.music_bed.wav    │
│     filter_complex:                                         │
│       [0:v] (cut) subtitles=f='<bv>.danmaku.ass',           │
│              subtitles=f='<bv>.cleaned.ass'                 │
│              (setpts) → [vout]                              │
│       [1:a] (atrim) → [sp]                                  │
│       [2:a][sp] sidechaincompress → [music_ducked]          │
│       [sp][music_ducked] amix (atempo) → [aout]             │
│   → output/<project>/<dir>/<bv>_final.mp4                   │
│   no cache (always re-run if invoked)                       │
└─────────────────────────────────────────────────────────────┘
   │
   ▼ output/<project>/<dir>/<bv>_final.mp4  +  <bv>.music_credits.txt
```

**Path-escaping note for stage 5**: today's `burn.py` runs `ffmpeg` with `cwd=temp/<dir>/` and passes ASS filenames as basenames to work around ffmpeg 8.x `subtitles=` quoting bugs. With the cleaned subtitle nested under `<bv>/`, the basename trick breaks (filter would need `<bv>/speech.cleaned.ass`, which contains a slash — fragile). Mitigation: **symlink or copy** `temp/<dir>/<bv>/speech.cleaned.ass` to `temp/<dir>/<bv>.cleaned.ass` at the start of the burn stage so both ASS files are siblings of `<bv>.mp4` and the cwd-with-basename trick works for both. The symlink is in `temp/<dir>/` and is cheap; it does not affect the cache.

The `video2yt` top-level CLI (existing) becomes a thin orchestrator that calls
the five stages in order. Each stage is cache-aware, so the orchestrator does
not need to know which stages are stale.

## 5. Module structure

```
src/video2yt/
├── cli.py              # MODIFIED — orchestrator only; calls the five stages.
│                       # Removes inline burn/cut/font-size logic (moved to burn.py / stems.py).
├── fetch.py            # NEW — extracted from today's download.py + part of cli.py.
│                       # download raw mp4 + xml + build danmaku.ass.
├── fetch_cli.py        # NEW — video2yt-fetch entry point.
├── download.py         # MODIFIED — keep only the yt-dlp subprocess wrapper; remove biliass call (moves to fetch.py).
├── stems.py            # NEW — song-remover subprocess wrapper; output management; speech.wav extraction.
├── stems_cli.py        # NEW — video2yt-stems entry point.
├── subtitle.py         # MODIFIED — still accepts <dir>/<bv>.mp4 (kept so ffprobe can recover width/height for ASS PlayResX/Y), but the audio source for ASR + silencedetect changes from "extract from mp4 / find <input>.vocals.wav sidecar" to "read <dir>/<bv>/speech.wav directly" (errors if missing). All Demucs/vocals-stem code paths removed.
│                       # Writes <dir>/<bv>/speech.cleaned.ass alongside (via compose.srt_to_ass) instead of cleaned.srt.
├── subtitle_cli.py     # MODIFIED — input is still <bv>.mp4, but the CLI now requires <bv>/speech.wav as a sibling (errors with "run video2yt-stems first" if missing); detection-logic branches removed (orchestrator-level --no-subtitle replaces them).
├── music_mix.py        # NEW (replaces large parts of music_swap.py) — builds CC0 bed from music_library.py; emits <dir>/<bv>.music_bed.wav + <dir>/<bv>.music_credits.txt.
├── music_mix_cli.py    # NEW — video2yt-music-mix entry point.
├── music_library.py    # UNCHANGED.
├── burn.py             # MODIFIED — _build_filter_complex extended to accept multiple ASS subtitles, optional aux audio inputs, sidechain-ducking mix params.
├── burn_cli.py         # NEW — video2yt-burn entry point.
├── music_swap.py       # DELETED — all logic either inlined into burn.py (mix) or replaced by music_mix.py (bed build).
├── music_swap_cli.py   # DELETED.
└── music_detect.py     # DELETED — no longer needed (existed only to mask Demucs no_vocals music residue).

tests/
├── test_smoke.py       # MODIFIED — drop music_swap tests; orchestrator-level test asserting the five stages fire in order and cache files cause stage-skip on second run.
├── test_subtitle.py    # MODIFIED — input fixture is still a video path, but tests now assert the CLI looks up <bv>/speech.wav as a sibling; drop detection-logic tests; add a .speech_source_meta.json cache-invalidation test.
├── test_music_swap.py  # DELETED (if it exists as a separate file).
├── test_stems.py       # NEW — song-remover subprocess + cache-meta-sidecar coverage.
├── test_music_mix.py   # NEW — CC0 bed build + cache-meta-sidecar coverage.
└── test_burn_all.py    # NEW — combined danmaku+SRT+audio-mix filter_complex graph (unit-level, no ffmpeg invocation).

pyproject.toml          # MODIFIED:
                         #   - Add `[project.scripts] video2yt-fetch`, `video2yt-stems`,
                         #     `video2yt-music-mix`, `video2yt-burn`.
                         #   - Remove `video2yt-music-swap`.
                         #   - song-remover stays out-of-tree (subprocess invocation only,
                         #     no path/Git dep yet — see §11 Q3).
                         #   - Remove `demucs`, `torchaudio`, `soundfile`, plus any
                         #     other deps used only by the deleted music_swap path.
```

## 6. The single ffmpeg burn pass — concrete graph

`burn.py::_build_filter_complex` extended. Conceptual graph (cuts and speed both optional):

```
inputs:
  -i <bv>.mp4               (#0: original video + original audio — original audio is IGNORED, not mapped)
  -i <bv>/speech.wav        (#1: clean voice — output of song-remover, fed as full path because it is
                             not a subtitle file; ffmpeg's `-i` accepts paths with subdirs fine)
  -i <bv>.music_bed.wav     (#2: CC0 bed — output of music_mix)

filter_complex:
  # ===== VIDEO chain =====
  # Stage V1: cut → [cv]
  [0:v]trim=start=s1:end=e1,setpts=PTS-STARTPTS[v0]
  [0:v]trim=start=s2:end=e2,setpts=PTS-STARTPTS[v1]
  [v0][v1]concat=n=N:v=1:a=0[cv]               # or [0:v]null[cv] when no cuts

  # Stage V2: burn both subtitle layers (basenames, cwd into temp dir).
  # Stage 5 picks the on-disk file names based on whether --cut was passed.
  # Pseudo-Python at burn-stage entry:
  #   danmaku_ass = "<bv>.danmaku.cut.ass" if cuts else "<bv>.danmaku.ass"
  #   cleaned_ass = "<bv>.cleaned.cut.ass" if cuts else "<bv>.cleaned.ass"
  # Where:
  #   - no cuts: <bv>.danmaku.ass already exists from stage 1; <bv>.cleaned.ass is a
  #              symlink to <bv>/speech.cleaned.ass produced by stage 3.
  #   - cuts:    both .cut.ass files are produced by cuts.rewrite_ass_for_cuts at
  #              burn-stage entry (ephemeral; deleted on burn success).
  # Both forms are flat siblings of <bv>.mp4 so the cwd-with-basename trick works.
  [cv]subtitles=f='{danmaku_ass}'[d1]
  [d1]subtitles=f='{cleaned_ass}'[sv]

  # Stage V3: speed → [vout]
  [sv]setpts=PTS/1.5[vout]                     # or [sv]null[vout] when speed=1.0

  # ===== AUDIO chain =====
  # Stage A0: normalize both audio inputs to 48k stereo before any further work.
  # speech.wav is already 24-bit PCM 48k stereo from song-remover, but the music
  # bed may have been concatenated from CC0 sources at varying sample rates;
  # `aresample` + `aformat` makes the graph deterministic.
  [1:a]aresample=48000,aformat=channel_layouts=stereo[spN]
  [2:a]aresample=48000,aformat=channel_layouts=stereo[bedN]

  # Stage A1: cut speech and bed in lock-step → [csp], [cbed]
  [spN]atrim=start=s1:end=e1,asetpts=PTS-STARTPTS[sp0]
  [1:a]atrim=start=s2:end=e2,asetpts=PTS-STARTPTS[sp1]
  [sp0][sp1]concat=n=N:v=0:a=1[csp]
  [bedN]atrim=start=s1:end=e1,asetpts=PTS-STARTPTS[bed0]
  [bedN]atrim=start=s2:end=e2,asetpts=PTS-STARTPTS[bed1]
  [bed0][bed1]concat=n=N:v=0:a=1[cbed]         # passthroughs when no cuts (then [spN]→[csp], [bedN]→[cbed])

  # Stage A2: mix speech with sidechain-ducked bed → [amix]
  [csp]asplit=2[sp_a][sp_b]
  [cbed]volume=0.18[bed_scaled]
  [bed_scaled][sp_a]sidechaincompress=threshold=0.05:ratio=8:attack=5:release=300[bed_ducked]
  [sp_b][bed_ducked]amix=inputs=2:duration=first:dropout_transition=0:normalize=0[mixed]

  # Stage A3: speed → [aout]
  [mixed]atempo=1.5[aout]                      # or [mixed]anull[aout] when speed=1.0

map:
  -map [vout] -map [aout]
  -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30
  -c:a aac -b:a 160k -ar 48000
  output/<project>/<dir>/<bv>_final.mp4
```

The `-pix_fmt yuv420p -r 30` pair is **required** for downstream `video2yt-merge` strict mode (1920×1080 30fps h264 — see CLAUDE.md "merge strict mode"). If the source `<bv>.mp4` is not 1920×1080 (e.g. VIP-locked 480p Bilibili source), an explicit upscale-via-`scale` filter must be inserted before the subtitle stage — surface this through preflight, not silently. `-ar 48000` keeps the AAC sample rate consistent with song-remover's 48 kHz output and avoids implicit resampling artefacts.

Notes baked into this graph:

1. **Cuts apply uniformly** to video, speech, and bed in lock-step. **Important change from today**: today's `cuts.rewrite_ass_for_cuts` runs on the danmaku ASS at the CLI orchestrator level (after fetch, before burn), producing a separate `<bv>.danmaku.cut.ass`. Caching that file is unsafe — it's keyed by the cut ranges, which are CLI flags not encoded in the filename. The design pulls the rewrite **into the burn stage** for **both** ASS files: stage 1 produces only the un-cut `<bv>.danmaku.ass` (no `.cut.ass` written), stage 3 produces only the un-cut `<bv>/speech.cleaned.ass`, and stage 5 runs `cuts.rewrite_ass_for_cuts` on both into ephemeral temp ASS files just before ffmpeg launch. Single ownership of cuts in stage 5; stages 1-4 never see the cut flags.
2. **Speed is applied last** (after subtitle burn) so danmaku and cleaned subtitles are baked at the original timeline, then setpts/atempo scale them along with the rest of the frame. This matches today's danmaku behavior.
3. **The original audio (`[0:a]`) is never mapped.** The new audio comes entirely from speech + bed. This is intentional (Approach A: discard everything except the clean voice).
4. **Two `subtitles=` filters chained**: `[cv]subtitles=f='danmaku.ass'[d1]; [d1]subtitles=f='cleaned.ass'[sv]`. ffmpeg applies them in order, so the cleaned subtitle is drawn on top of the danmaku frame — acceptable because cleaned subtitles live at the bottom (`MarginV=15`) and danmaku floats top-to-mid; overlap is rare and a clean SRT line winning over a passing danmaku is a feature, not a bug.
5. **Path escaping**: both ASS files must live in the same dir, and ffmpeg is invoked with `cwd=temp/<dir>/`, basenames in the filter string. Same trick `burn.py` already uses. The `compose.py` SRT trick is identical.
6. **Audio constants** (`volume=0.18`, sidechaincompress params, `amix normalize=0`) come from today's `music_swap.mix()` (lines 432-445). They are known-good; no new tuning.
7. **No `-c:a copy` fast path**. The new pipeline always re-encodes audio (we are mixing two sources). This is fine — audio encode is fast compared to video. Today's simple-mode `-c:a copy` is gone.

## 7. CLI surface

`<dir>` below always means `temp/<uploader_prefix>：<title>/`. All filenames are exactly as in §4 / §8 — this section just lists the per-CLI contracts; refer there for the canonical layout.

### `video2yt-fetch <url> -o <dir>/`

- **Input**: Bilibili URL.
- **Output**: `<dir>/<bv>.mp4`, `<dir>/<bv>.danmaku.xml`, `<dir>/<bv>.danmaku.ass`.
- **Cache**: skips yt-dlp if `<bv>.{mp4,mkv,webm}` + `<bv>*.xml` are present (same predicate as today's `download.fetch`). Skips biliass if `<bv>.danmaku.ass` is present.
- **Flags**: `--quality`, `--codec`, `--font-size`, `--font-face` (font params route to biliass).

### `video2yt-stems <dir>/<bv>.mp4`

- **Input**: `<dir>/<bv>.mp4`.
- **Output**: `<dir>/<bv>/{speech,music,sfx,no_music}.wav` (all four kept on disk — see §3 "What we keep from stems"). Brief log line noting wall-clock + device.
- **Cache**: skips song-remover if `<dir>/<bv>/speech.wav` is present **and** the `<dir>/<bv>/.stems_source_meta.json` sidecar matches the current `<bv>.mp4` (see §11 Q9).
- **Internal**: invokes `song-remover` (the CLI) as subprocess with `-o <dir>/`. song-remover natively writes `<dir>/<bv>/{speech,music,sfx,no_music}.wav` — no rename / move needed.
- **Flags**:
    - `--device {cpu,mps,auto,remote}` — default **`remote`** (Modal T4 GPU, 7.2× faster than local CPU; see §3 "Default device" decision). Falls through to song-remover's own `--device` flag and, when `remote`, to its `--remote` flag.
    - `--chunk-min N` — only meaningful with `--device remote`; passed to song-remover. Default 5 (5-minute chunks, matches song-remover's own default). For long inputs, lower it for more parallelism (e.g. `--chunk-min 3`); set to 0 to disable chunking.
    - `--force` — overwrite existing stems.
- **One-time setup** (only needed for `--device remote`): from the song-remover repo, `uv sync --extra remote && uv run modal token new && uv run modal deploy -m modal_app.prep && uv run modal run -m modal_app.prep && uv run modal deploy -m modal_app.separator`. Documented in CLAUDE.md after implementation.

### `video2yt-subtitle <dir>/<bv>.mp4`

- **Input**: `<dir>/<bv>.mp4` (same input shape as today, but the CLI no longer extracts audio from it).
- **Sibling-lookup inputs**: `<dir>/<bv>/speech.wav` (required — errors with "run `video2yt-stems` first" if missing).
- **Output**: alongside the speech.wav, `<dir>/<bv>/speech.cleaned.ass`. Sidecars `<dir>/<bv>/speech.raw.srt`, `<dir>/<bv>/speech.cleaned.p0p6.srt`, and `<dir>/<bv>/.speech_source_meta.json` (see §11 Q9 for the stems→subtitle cache invalidation chain).
- **Cache check order**:
    1. If `.speech_source_meta.json` is missing **or** does not match the current `<bv>/speech.wav` (SHA-256 of first 1 MB), delete `speech.raw.srt` and **every** file matching `<bv>/speech.cleaned.*.srt` (glob — covers all historical threshold variants, not just the current run's), then rewrite the sidecar BEFORE proceeding. This is the **single point** where stems→subtitle cache invalidation happens — closing the codex review's B3 finding.
    2. Skip ASR if `speech.raw.srt` is present (post-step-1).
    3. Skip cleanup if `speech.cleaned.p<th>.srt` for the current threshold is present (today's behavior, unchanged — a different threshold picks a different cache key naturally).
    4. `speech.cleaned.ass` is cheap and rebuilt every invocation.
- **Internal**: ffprobe `<bv>.mp4` for width/height (needed for ASS PlayResX/PlayResY so the cleaned subtitle renders at the same pixel size as the danmaku). Then today's whisperx ASR + silencedetect-on-speech.wav + pause-split + Codex cleanup. The final SRT-to-ASS conversion uses `compose.srt_to_ass` (already present) with the subtitle-CLI's tuned defaults (font 18, margin_v 15, outline 2, shadow 0) and the ffprobed dimensions.
- **Pause-split source change**: today's code runs silencedetect on a `<input>.vocals.wav` sidecar (the Demucs vocals stem produced by music-swap). The new flow runs it directly on `<bv>/speech.wav` — song-remover's speech stem is already isolated, so the explicit vocals sidecar lookup is removed.
- **Detection logic**: removed. The previous danmaku-XML / OCR / manual-flag detection lived in today's CLI because the input was a video and the question was "should we add subtitles to this video at all?" The new flow always calls `video2yt-subtitle` for the segments we want subbed; the per-streamer "skip" decision moves up to the orchestrator's CLI flag `--no-subtitle` (default off). For sources that already have burned-in subs, pass `--no-subtitle` at orchestrator level.

### `video2yt-music-mix <dir>/<bv>.mp4`

- **Input**: `<dir>/<bv>.mp4` (only used to probe total duration).
- **Output**: `<dir>/<bv>.music_bed.wav`, `<dir>/<bv>.music_credits.txt`, and the sidecar `<dir>/<bv>.music_bed_meta.json` (records the source duration — see §11 Q9).
- **Cache**: skips if `<bv>.music_bed.wav` + `<bv>.music_credits.txt` are present **and** the sidecar duration matches the current `<bv>.mp4`.
- **Internal**: reuses `music_library.py::select_tracks_for_duration` and the bed-concat ffmpeg command from today's `music_swap.build_music_bed`.

### `video2yt-burn <dir>/ --bv <bv> -o <output>`

- **Inputs read from `<dir>/`**: `<bv>.mp4`, `<bv>.danmaku.ass`, `<bv>/speech.wav`, `<bv>/speech.cleaned.ass` (optional — skipped under `--no-subtitle`), `<bv>.music_bed.wav` (optional — skipped under `--no-music-swap`, in which case `<bv>.mp4`'s native audio is mapped).
- **Output**: `<output>` is the final mp4 path (typically `output/<project>/<dir>/<bv>_final.mp4`). Also copies `<bv>.music_credits.txt` next to the final mp4 when music-mix was used.
- **Cache**: none. The burn is the cheap step (~3 min); always re-run when invoked.
- **Flags**: `--cut START~END` (repeatable), `--speed FLOAT`, `--preview-seconds N`, `--no-subtitle` (skip the cleaned.ass burn; danmaku still burned), `--no-music-swap` (use `<bv>.mp4`'s native audio; skip speech+bed mix).

### `video2yt <url> -o <project>/` (orchestrator)

- Loops through stages 1-5 in order. Each stage is a function call into the same modules used by the per-stage CLIs.
- Per-stage timing logged.

**Skip-flag contracts** (explicit per codex review N5):

| Flag | Stages skipped | Stage 5 effect |
|---|---|---|
| `--no-subtitle` | Stage 3 entirely | Stage 5 burns only `<bv>.danmaku.ass`; the second `subtitles=` filter is omitted from filter_complex. |
| `--no-music-swap` | Stage 4 entirely; Stage 2 is also skipped if `--no-subtitle` is also set (since nothing else consumes `speech.wav`) | Stage 5 maps `[0:a]` (the raw mp4's native audio) directly, skipping the audio chain (no speech+bed mix). |
| Both flags | Stages 2, 3, 4 all skipped | Stage 5 is just the simple danmaku burn + native-audio passthrough — equivalent to today's `video2yt` simple path. |

Other flags pass through unchanged: `--cut`, `--speed`, `--preview-seconds`, `--quality`, `--codec`, `--font-size`, `--font-face`, `--device`, `--keep-temp` (no-op now; always kept).

## 8. Cache layout summary

```
temp/<uploader_prefix>：<title>/
├── <bv>.mp4                              # Stage 1 — yt-dlp output (existing convention)
├── <bv>.danmaku.xml                      # Stage 1 — danmaku XML  (existing convention)
├── <bv>.danmaku.ass                      # Stage 1 — biliass output (existing convention; NOT cut-rewritten — see §6 note 1)
├── <bv>/                                 # Stage 2 — song-remover's natural <basename>/ output dir
│   ├── speech.wav                        #   kept (consumed by stages 3 + 5)
│   ├── music.wav                         #   kept on disk; not consumed
│   ├── sfx.wav                           #   kept on disk; not consumed
│   ├── no_music.wav                      #   kept on disk; not consumed
│   ├── .stems_source_meta.json           # Stage 2 — cache-validity sidecar (see §11 Q9)
│   ├── .speech_source_meta.json          # Stage 3 — cache-validity sidecar for ASR + cleanup (see §11 Q9)
│   ├── speech.raw.srt                    # Stage 3 — whisperx ASR cache (<stem>.raw.srt convention)
│   ├── speech.cleaned.p0p6.srt           # Stage 3 — codex cleanup cache (<stem>.cleaned.<th>.srt)
│   └── speech.cleaned.ass                # Stage 3 — burn-ready ASS (always rebuilt; cheap)
├── <bv>.cleaned.ass                      # Stage 5 — symlink to <bv>/speech.cleaned.ass for ffmpeg's
│                                         #            cwd-with-basename quoting (see §6 path note);
│                                         #            ephemeral, recreated each burn
├── <bv>.music_bed.wav                    # Stage 4 — CC0 bed cache
├── <bv>.music_credits.txt                # Stage 4 — attribution sidecar
└── <bv>.music_bed_meta.json              # Stage 4 — cache-validity sidecar (see §11 Q9)
```

**Cache-key correctness**: the stems cache is keyed by `<bv>/speech.wav`'s presence, not by `<bv>.mp4`'s content hash. So if you re-run `video2yt-fetch` with a different `--quality` and yt-dlp produces a different `<bv>.mp4`, the stale `speech.wav` will be reused. **Fix**: stage 1 detects the `<bv>.mp4` quality from ffprobe; if it differs from what's recorded in `<bv>/.stems_source_meta.json` (a tiny sidecar written by stage 2), stage 2 invalidates the cache. Same trick for `<bv>.music_bed.wav` (keyed by total duration, recorded in a sidecar). See §11 Q9.

To force-rerun a stage: delete the corresponding file(s). The orchestrator always preserves the entire `temp/<dir>/` after a successful run (matches today's "raw mp4 + XML always preserved" rule), so the cache survives the next invocation. `--keep-temp` is a no-op now (always kept); kept as a flag for backwards CLI compat.

## 9. Migration / disposition of existing artifacts

- Existing `<bv>_with_danmaku.mp4`, `<bv>_with_danmaku_clean.mp4`, `<bv>_with_danmaku_clean_subbed.mp4` files in `output/` continue to exist on disk; the new pipeline does not produce them and does not delete them. Users clean up by hand.
- Existing `temp/<dir>/` raw mp4 + XML are reused by the new fetch stage's cache (filename pattern is the same).
- The merge step (`video2yt-merge`) is unchanged; it accepts whatever the new `<bv>_final.mp4` path is, the strict 1920x1080 30fps h264 rules continue to apply.

## 10. Test plan

- `test_smoke.py`: end-to-end orchestrator test mocking every subprocess at the `subprocess.run` boundary. Asserts the five stages fire in order, the final mp4 path is reported, and each cache file's presence skips the right stage on a second run.
- `test_burn_all.py`: pure filter_complex unit tests. Feed `_build_filter_complex` various combinations of (cuts y/n, speed y/n, subtitle y/n, music-swap y/n) and assert the emitted graph string has the expected labels and stages. No ffmpeg invocation.
- `test_stems.py`: subprocess-mocked song-remover invocation. Assert command-line args, that `<bv>/{speech,music,sfx,no_music}.wav` are all written, that the `.stems_source_meta.json` sidecar is written with the correct source meta, and that cache hits skip the subprocess.
- `test_subtitle.py`: input fixture stays as a video path (the CLI needs ffprobe-derived dimensions), but tests change to: (a) assert the CLI errors out cleanly when `<bv>/speech.wav` is missing, (b) assert silencedetect is invoked on `<bv>/speech.wav` (not on the deleted `<input>.vocals.wav`), (c) assert the `.speech_source_meta.json` sidecar is written and that a stale sidecar deletes `speech.raw.srt` AND every `speech.cleaned.*.srt` (test with both `cleaned.p0p6.srt` and `cleaned.p0p8.srt` present in the fixture, assert both are gone after invalidation), (d) assert that re-running with the same speech.wav and the same threshold hits both caches and skips ASR + cleanup. Drop the detection-logic (danmaku-XML / OCR / manual-flag) tests. Keep the ASR / cleanup / split / burn-style tests.
- `test_music_mix.py`: subprocess-mocked CC0 bed build. Same shape as today's music_swap tests for the bed-build path; remove the Demucs and mix-with-vocals paths.

Target: zero net loss of existing assertion coverage on the parts we keep; full new coverage on the burn-all graph.

## 11. Open questions for codex review and/or user

### Q1. Stems cache disposition — RESOLVED (user 2026-05-24)

User said: "1.先都留我自己删" (= keep all four stems by default, manual cleanup). Filed as: **all 4 stems remain on disk in `<dir>/<bv>/` after stage 2 completes**; downstream stages consume only `speech.wav`; no auto-delete flag is shipped initially. Matches today's raw-download cache convention (manual cleanup).

### Q2. song-remover as a path/Git dependency vs subprocess

Currently the repo at `~/code/song-remover` is local to the user's machine. Three options:

- **A. Subprocess only** (what this spec assumes). Pre-requisite: `song-remover` CLI must be on `$PATH`. Setup: `cd ~/code/song-remover && uv tool install .` (or document `uv run` from the song-remover dir). Pros: zero dep coupling between the two repos. Cons: setup step on every machine.
- **B. `[tool.uv.sources]` path dep**: `song-remover = { path = "../song-remover" }`. Pros: `uv sync` brings it in. Cons: hard-codes a relative path; CI / fresh clones break.
- **C. Vendor song-remover as a git submodule** under `third_party/`. Pros: reproducible. Cons: pulls in the ~447 MB model.

Recommendation: **A** for now (subprocess + manual `uv tool install`), document in CLAUDE.md. Revisit once song-remover has a published version.

Need user confirmation.

### Q3. The `--no-music-swap` flag — DECIDED (see §7)

Shipping it. Under `--no-music-swap`, stage 4 is skipped and stage 5 maps `<bv>.mp4`'s native audio instead of mixing speech + bed. User can override later if it causes confusion.

### Q4. Two ASS subtitles in one filter chain — VERIFIED (codex review 2026-05-24)

Codex tested `[0:v]subtitles=f='a.ass'[d1];[d1]subtitles=f='a.ass'[outv]` on ffmpeg 8.1 + libass locally; renders to null without error. The flat-basename + cwd rule is the key requirement, and the filter itself works. Listed as the lone real ffmpeg integration smoke we still owe in the test plan (see §10 — codex nice-to-have N3).

### Q5. Should `_gate_vocals` (commit `b8c8165`) stay?

Today's flow has a gate on the Demucs vocals stem to suppress music bleed. song-remover's `speech.wav` is allegedly cleaner. The design assumes no gate is needed. If speech.wav turns out to carry residue, gating could move into the burn stage.

Recommendation: **don't preemptively port the gate**. Listen to the first real speech.wav on a noisy BG segment, decide then.

### Q6. SRT vs ASS for the cleaned subtitle in the burn

Today `subtitle.py` writes SRT, then burns it via the `subtitles=` filter with a `force_style=` override. The design switches to writing ASS directly. Net win: simpler filter line, all styling in one file, no `force_style=` quoting. Net cost: one new conversion call (uses `compose.srt_to_ass`, already present and tested). Net cost is small, net win is large. Adopting unless reviewer pushes back.

### Q7. `cuts.rewrite_ass_for_cuts` ownership — DECIDED (see §6 note 1)

Cut-rewrite moves **entirely into stage 5**. Stages 1-4 produce un-cut artifacts; stage 5 runs `cuts.rewrite_ass_for_cuts` on both ASS files into ephemeral temp ASS files (`<bv>.danmaku.cut.ass`, `<bv>.cleaned.cut.ass`) used only for the in-progress ffmpeg invocation. This removes the today's flag-not-in-filename cache bug for `<bv>.danmaku.cut.ass`.

### Q8. Does the orchestrator need to know about a top-level subfolder structure for stages 1-4?

Currently the segment temp dir is `temp/<uploader_prefix>：<title>/`. Stages 1-4 all write into that one dir (stage 2 creates a `<bv>/` sub-folder per song-remover's natural layout; stage 3 writes inside that sub-folder; stages 1 and 4 write `<bv>.*` files at the parent level). Stage 5 writes into `output/<project>/<dir>/`. Reviewer please confirm the split is acceptable; the alternative (flatten everything into the parent dir) requires renaming song-remover's output, adding fragility.

### Q9. Stale-cache safety when quality / duration / threshold changes

Stage 2 caches by `<bv>/speech.wav` presence; if stage 1 produced a different `<bv>.mp4` (e.g. `--quality` flag changed), the stale stems are reused. Stage 4 caches by `<bv>.music_bed.wav`; if the source duration changes the bed length is wrong. Stage 3 caches by `<stem>.cleaned.<th>.srt` (today's behavior — threshold-keyed).

Proposed fix per stage:

- **Stage 2**: write `<bv>/.stems_source_meta.json` containing `{sha256: <first 1MB of <bv>.mp4>, duration: <seconds>, quality_label: <e.g. 1080p>}`. Stage 2 reads it on cache check; if it doesn't match, stems are invalidated. Cheapness: ffprobe + a 1MB SHA-256 ≈ negligible (~50ms).
- **Stage 3**: write `<bv>/.speech_source_meta.json` containing `{sha256: <first 1MB of <bv>/speech.wav>}` next to `speech.raw.srt`. Stage 3's cache check is a single ordered procedure (see §7 `video2yt-subtitle` for the canonical 4-step list): on sidecar mismatch, `speech.raw.srt` AND every file matching `speech.cleaned.*.srt` (glob, not just the current-run threshold) are deleted before rerun. This closes the codex review's B3 finding — without this chain, either a stale `speech.raw.srt` survives a stems regeneration, OR a fresh raw.srt is regenerated but an old cleaned.p<th>.srt (derived from the previous raw.srt, possibly at a different threshold from the current run) silently wins on the next pass with that threshold.
- **Stage 4**: `<bv>.music_bed_meta.json` keyed by `<bv>.mp4` total duration.

This adds three small files but eliminates the worst silent-bug class.

## 12. Estimated wall-clock comparison (17 min input segment)

| Phase | Current (Demucs + 3 ffmpeg) | New (song-remover `--device remote`) | New (song-remover `--device cpu`) |
|---|---|---|---|
| Fetch (yt-dlp + biliass) | ~30s | ~30s | ~30s |
| Source separation | Demucs ~10–30 min | song-remover Modal T4 ~12–15 min (estimated from 4 min → 3:39 baseline, scaled) | song-remover CPU ~3 hr |
| Burn danmaku | ~3 min | — | — |
| Music swap (audio remux) | ~30s | — | — |
| ASR + cleanup + split | ~21 min (warm: ~30s) | ~21 min (warm: ~30s; identical) | ~21 min |
| Burn subtitle | ~3 min | — | — |
| Single burn (danmaku + sub + amix) | — | ~3 min | ~3 min |
| **Total (cold)** | **~37–57 min** | **~36–39 min** (≈ parity) | **~3 hr 25 min** |
| **Total (warm: stems + `speech.raw.srt` + `speech.cleaned.*.srt` + `<bv>.music_bed.wav` cached, single burn from scratch)** | **~3 min** | **~3 min** | **~3 min** |
| Video re-encodes | 2 | 1 | 1 |
| Intermediate mp4 files | 2 (~600 MB + ~1 GB) | 0 | 0 |
| Cost per segment | $0 | ~$0.10–0.15 (within Modal $30/mo free tier) | $0 |

With `--device remote` (the new default), the cold-run wallclock is essentially at parity with today's pipeline AND we save one video re-encode + two intermediate mp4 files. Local CPU remains an option for offline / cost-sensitive runs.

## 13. Rollout plan (concrete TDD order, written after design is approved)

Deferred to the implementation plan in `docs/superpowers/plans/`. Not part of this design doc.


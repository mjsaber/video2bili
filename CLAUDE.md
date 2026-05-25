# CLAUDE.md

Project context for Claude agents working in this repo.

## Purpose

A local CLI that takes a Bilibili video URL and produces an MP4 with burned-in danmaku, optional STT subtitles, and an optional CC0 background music swap. The per-segment pipeline is five stages orchestrated by `video2yt`:

```
yt-dlp+biliass → song-remover stems → whisperx+codex subtitle → CC0 music bed → ONE ffmpeg pass that
burns danmaku ASS + subtitle ASS + sidechain-ducked speech+bed amix all together
```

Each stage has its own cache layer, its own CLI, and its own meta-sidecar so a rerun only redoes the slowest changed step. Supports `--cut START~END` to remove time ranges, `--speed FLOAT` for playback-multiplier output, `--preview-seconds` for fast iteration, `--no-subtitle` / `--no-music-swap` skip flags, and `--device {cpu,mps,auto,remote}` (default `remote` — Modal cloud GPU ~7.2× faster than local CPU).

## Commands

```bash
uv run video2yt "<url>" -o output/<project>/                           # full pipeline (5 stages)
uv run video2yt "<url>" --no-subtitle -o output/<project>/             # skip Stage 3 STT subtitle
uv run video2yt "<url>" --no-music-swap -o output/<project>/           # skip Stage 4; use source audio
uv run video2yt "<url>" --no-subtitle --no-music-swap -o ...           # legacy danmaku-only path
uv run video2yt "<url>" --device cpu -o ...                            # offline source separation
uv run video2yt "<url>" --cut 30~60 --speed 1.5 -o ...                 # cuts + speed multiplier
uv run video2yt-fetch "<url>" -o temp/                                 # only Stage 1 (download + biliass)
uv run video2yt-stems temp/<dir>/<bv>.mp4                              # only Stage 2 (song-remover)
uv run video2yt-subtitle temp/<dir>/<bv>.mp4                           # only Stage 3 (whisperx+codex)
uv run video2yt-music-mix temp/<dir>/<bv>.mp4                          # only Stage 4 (CC0 bed)
uv run video2yt-burn temp/<dir>/ --bv <bv> -o output/<bv>_final.mp4    # only Stage 5 (single ffmpeg)
uv run video2yt-compose --audio a.mp3 --image bg.jpg --srt subs.srt --title "T"   # intro composer
uv run video2yt-merge --segment a.mp4 --label "A" --segment b.mp4 --label "B" --segment c.mp4 --label "C" --title "T"   # concat + loudnorm + chapters
uv run pytest                                                          # run tests (569)
uv add <pkg>                                                           # add a dep (NEVER edit pyproject.toml deps by hand)
```

## External dependencies

- `ffmpeg` and `ffprobe` must be in PATH (system install, not Python package). Check with `shutil.which('ffmpeg')`. **Must include libass** — see "Known gotchas".
- video2yt downloads the raw danmaku XML via `yt-dlp --write-subs --sub-langs danmaku` and converts to ASS in-process using `biliass.convert_to_ass`, so the height and font_size are known before conversion. The `yt-dlp-danmaku` plugin is no longer used as a postprocessor (refactored away in `aa1d91c`); we still depend on the `biliass` Python package that ships with it.
- `song-remover` (out-of-tree subprocess at `~/code/song-remover`) must be on `$PATH` for `video2yt-stems` (Stage 2). One-time install: `cd ~/code/song-remover && uv tool install '.[remote]'` (the `[remote]` extra bakes the `modal` SDK into the tool's venv — without it, `--device remote` will fail with `ModuleNotFoundError: modal`). Verify with `song-remover --version`. For the default Modal cloud-GPU path (`--device remote`, 7.2× faster than local CPU, ~$0.10/segment within Modal's $30/mo free tier), the one-time Modal setup additionally requires: `uv run modal token new && uv run modal deploy -m modal_app.prep && uv run modal run -m modal_app.prep && uv run modal deploy -m modal_app.separator` (all from the song-remover repo).
- `codex` CLI (used by Stage 3 subtitle cleanup) — `brew install codex && codex login`.

## Project folder convention

When working on a multi-step video project (intro + multiple burnt segments + final merge), pass `-o output/<project>/` to every `video2yt` / `video2yt-compose` / `video2yt-merge` invocation so all artifacts land under one folder. Example: `output/back2back/` contains `intro.mp4`, segment subfolders, the final merged MP4, the YouTube thumbnail, and any scratch files. This keeps unrelated projects isolated and makes cleanup easy.

## Battlegrounds workflow rule (intro-script drafting)

For Hearthstone Battlegrounds video projects, **never draft the intro script before verifying the topic's terminology**. After the `ringnaga` mistake (drafted assuming "護戒" was a Spellcraft buff when it actually meant the card 戒指龍 / Ring Bearer), this is hard rule:

1. Run `WebFetch https://search.bilibili.com/all?keyword=<策略名>` and read the top UP-主 video titles + descriptions.
2. Confirm the 流派 pivots on the right card / hero (typically a 6-7星核心隨從).
3. Use BG vocabulary (阵容/隨從/酒館/餵/疊屬性/吃雞), NOT constructed-mode vocabulary (牌組/起手/過渡). Full glossary in `docs/superpowers/specs/2026-04-18-video-production-workflow.md` Step 1.

## Known gotchas

### ffmpeg / burn pipeline

- **ffmpeg `subtitles=` filter path escaping**: chokes on absolute paths containing spaces, colons, or parentheses. Workaround in `burn.py`: run subprocess with `cwd=temp_dir` and pass the ASS filename as a basename; the `-i` input also uses the basename. ffmpeg 8+ is stricter and requires the explicit `subtitles=f='<name>'` quoted form.
- **Chaining two `subtitles=` filters in one filter_complex**: T6 verified on ffmpeg 8.1 + libass that `[cv]subtitles=f='d.ass'[sv1]; [sv1]subtitles=f='c.ass'[sv]` renders both layers correctly. Cleaned-subtitle ASS lives under `<bv>/speech.cleaned.ass`; burn pre-flight symlinks it to a flat sibling `<bv>.cleaned.ass` so the cwd-with-basename trick works for both files.
- **Cleaned ASS symlink target is absolute**: `sym_path.symlink_to(cleaned_target.resolve())`. Relative targets resolve against the symlink's parent (not cwd) and would produce a broken link when `temp_dir` itself is relative.
- **Multi-range cuts + music-swap require asplit**: ffmpeg filter labels are single-consumer. With N>1 cuts AND `apply_music_swap=True`, the normalized `[1:a]`/`[2:a]` outputs must be asplit before the per-range atrim loop, or libavfilter rejects the graph.
- **ffmpeg must be built with libass**: the default `brew install ffmpeg` bottle does NOT always include libass, so the `subtitles` filter we rely on is missing. Symptom: ffmpeg emits `No option name near '<filename.ass>'` or `No such filter: 'subtitles'`. Fix: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`. Pre-flight check: `ffmpeg -filters | grep subtitles` must list the filter.
- **Speed is applied last in the filter chain**: subtitles burn BEFORE `setpts` so the ASS timeline matches the original video; `setpts`/`atempo` then scale the already-burned pixels and the mixed audio. Same logic for both the danmaku layer and the cleaned-subtitle layer.
- **Cut boundary dialogues are dropped, not clipped**: when a danmaku/cleaned dialogue intersects a `--cut` range (even by a single frame), the whole dialogue is dropped. Rationale: simpler semantics, avoids partial-display weirdness. See `cuts.rewrite_ass_for_cuts`. The rewrite is ephemeral inside `burn.render` — the on-disk `<bv>.danmaku.ass` and `<bv>/speech.cleaned.ass` always stay un-cut for cache stability.
- **Burn output args satisfy merge strict mode**: every burn re-encode uses `-pix_fmt yuv420p -r 30 -ar 48000 -c:v libx264 -c:a aac` so `video2yt-merge`'s strict 1920x1080 30fps h264 yuv420p + AAC 48kHz check passes.

### Cache invalidation chain (spec §11 Q9)

- **`<bv>/.stems_source_meta.json`**: stems cache key. Records `{sha256: first-1MB-of-<bv>.mp4, duration, width, height, quality_label}`. Mismatch → song-remover re-runs.
- **`<bv>/.speech_source_meta.json`**: subtitle cache key. Records `{sha256: first-1MB-of-speech.wav}`. Mismatch → deletes `speech.raw.srt` AND every `speech.cleaned.*.srt` (glob covers all historical threshold variants — codex caught the "fresh raw + stale cleaned at different threshold silently wins" bug).
- **`<bv>.music_bed_meta.json`**: music-mix cache key. Records `{duration, width, height}` with a 0.5s duration tolerance for ffprobe jitter. Mismatch → bed + credits regenerate atomically.
- **Atomic writes**: all meta sidecars + the music_credits.txt write to a `.tmp` and then `os.replace`. A mid-run crash never leaves a half-written sidecar that the next run would accept as cache-valid.

### yt-dlp / Bilibili

- **yt-dlp release cadence**: yt-dlp updates frequently because Bilibili's extractor rules shift. If downloads suddenly break, first try `uv lock --upgrade-package yt-dlp`.
- **Chrome cookie DB lock**: `--cookies-from-browser chrome` requires Chrome to not be holding the cookie database lock. If it fails, close Chrome first.
- **Bilibili VIP-locked 1080p**: some BV sources only expose 480p/360p without a premium account (yt-dlp `-F` confirms with `1080P ... you have to become a premium member`). `video2yt-merge` enforces strict 1920x1080 30fps h264, so a 480p burnt segment will fail merge late. **Pre-flight**: after `video2yt-fetch`, eyeball the "probing source video" log — if it warns about lower-than-requested resolution, either upscale via `ffmpeg -i in.mp4 -vf "scale=1920:1080:flags=lanczos" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 -c:a copy out.mp4` or swap source.

### Stems / song-remover

- **`--device remote` requires one-time Modal setup**: cli.run does an early Modal-token preflight (checks `~/.modal.toml` exists) so a misconfigured remote run fails BEFORE the 30s yt-dlp fetch, not after. Use `--device cpu` for offline runs (slower).
- **All 4 stems kept on disk**: `<bv>/{speech,music,sfx,no_music}.wav` are all preserved after Stage 2 finishes. Downstream stages only consume `speech.wav`; the other three are for manual inspection. User decision 2026-05-24: "先都留我自己删".
- **If you manually edit speech.wav, the cache regenerates**: the sidecar's sha256 won't match. To force regen WITHOUT changing speech.wav, delete `<bv>/.stems_source_meta.json` and re-run.

### Subtitle / whisperx

- **Cold cleanup is ~13 min**: codex-based glossary cleanup on a 31-line BG transcript takes ~775s wall-clock; default `CLEANUP_TIMEOUT_SECONDS = 1200` (20 min) leaves headroom. Total cold pipeline on a 17-min segment: ~12-15 min stems (remote) + ~8 min ASR + ~13 min cleanup + ~3 min burn ≈ **~36 min**. Warm cache: ~3 min total.
- **silencedetect runs on speech.wav directly**: Stage 3 picks the cleanest pause-split boundaries by running silencedetect on song-remover's `speech.wav` (the old vocals.wav sidecar from music-swap is gone). whisperx large-v3 is the ASR engine. SenseVoice was rejected (returns one giant string with no per-segment timestamps and hallucinates lyrics on BGM-heavy clips).
- **Subtitle CLI input is `<bv>.mp4`, NOT speech.wav**: the subtitle CLI needs ffprobe-derived dimensions for ASS PlayResX/Y. It looks up `<bv>/speech.wav` as a sibling internally; errors with "Run video2yt-stems first" if missing.

### Music-mix (CC0 bed build)

- **CC0 risk reduction, not a guarantee**: song-remover's `speech.wav` is used as the dry voice in the final amix; the original music+SFX mix is discarded. Game sound effects are lost by design — Approach A trade-off, see the spec. The replacement CC0 track also carries its own (very low) claim risk. Strong suppression, not mathematical guarantee.
- **Music library + attribution**: `~/.cache/video2yt/music/` is the source of truth. On first run music_mix auto-downloads a shipped manifest (`src/video2yt/data/music_library.json`) of calm Kevin MacLeod tracks from the Internet Archive — these are **CC BY 3.0, attribution required**. `music_mix.render` writes `<bv>.music_credits.txt`; the orchestrator copies it to `<bv>_final_music_credits.txt`; those lines MUST go in the YouTube description. To avoid attribution, drop YouTube Audio Library tracks into the cache dir by hand (cache files with no manifest entry need no credit). NEVER put YouTube Audio Library tracks in the manifest — its license forbids redistribution.

### Workflow / cleanup

- **`--keep-temp` is a no-op**: T7 of step6-restructure made the orchestrator preserve all per-stage caches by default (raw mp4 + xml + danmaku.ass + 4 stems + raw.srt + cleaned.*.srt + music_bed.wav). Flag kept for backwards CLI compat. To force a fresh run of a single stage, delete its meta sidecar; to nuke a whole segment, delete the `temp/<dir>/` subfolder.
- **Output filename**: `<bv>_final[_cut][_<speed>x][_preview].mp4`. The legacy `_with_danmaku` / `_clean` / `_subbed` pipeline-stage suffixes are gone (T7 of step6-restructure) since one ffmpeg pass does all three.
- **Agent E2E test rule**: DO NOT run `rm -rf output/` or `rm -rf temp/` during E2E tests — that wipes every cached raw download and the outputs of unrelated videos. Clean only the specific `temp/<subfolder>/` under test, or just let the cache hit on the next run. This is a workflow rule, not a code invariant.

### Compose / merge

- **compose SRT path escaping**: `compose.render` uses `cwd=<srt.parent>` and references the SRT by basename in the `subtitles` filter (same trick as `burn.py`). Absolute paths for `-i` inputs are fine because `-i` doesn't go through filter_complex.
- **merge strict mode**: all `--segment` inputs must be 1920x1080 30fps h264 AND ≥10s long, and there must be ≥3 segments. The 10s/3-segment rules mirror YouTube's chapter requirements — fewer/shorter chapters means YouTube discards the chapter list. No auto-normalization. Fail fast with all violations listed.
- **merge chapters**: there is no burned-in progress bar — segmentation is delivered as chapter markers. The **only officially-supported** YouTube chapter source is timestamps in the video description (≥3 ascending, first at 00:00, each ≥10s, exactly one block). merge produces two outputs: `<title>_chapters.txt` is the description paste (this is the supported path); `<title>_ffmeta.txt` is embedded into the MP4 via `-map_metadata`/`-map_chapters` as a best-effort extra — YouTube does NOT officially document reading embedded chapter atoms, so do NOT treat the embed as a safety net. Common breakage: a description with two timestamp blocks (繁體 + 简体) is not strictly ascending and YouTube discards the whole list — keep the block to exactly one occurrence.

## Architecture

```
src/video2yt/
├── cli.py            # video2yt — orchestrator: chains the 5 stages, skip flags, per-stage timing
├── fetch.py          # Stage 1: yt-dlp + biliass; returns FetchResult dataclass
├── fetch_cli.py      # video2yt-fetch entry point
├── download.py       # thin yt-dlp subprocess wrapper (cache check + format spec)
├── stems.py          # Stage 2: song-remover subprocess wrapper + .stems_source_meta.json
├── stems_cli.py      # video2yt-stems entry point
├── subtitle.py       # Stage 3: whisperx ASR + silencedetect-on-speech.wav + codex cleanup
├── subtitle_cli.py   # video2yt-subtitle entry point; sibling-lookup <bv>/speech.wav;
│                     #   .speech_source_meta.json cache chain; writes <bv>/speech.cleaned.ass
├── music_mix.py      # Stage 4: CC0 bed build + .music_bed_meta.json
├── music_mix_cli.py  # video2yt-music-mix entry point
├── music_library.py  # CC0 manifest + download cache + track selection
├── burn.py           # Stage 5: single ffmpeg pass — chained subtitles + sidechain-ducked amix
│                     #   + ephemeral cut-rewrite + pre-flight cleaned-ASS symlink
├── burn_cli.py       # video2yt-burn entry point
├── meta.py           # shared sidecar helpers: atomic JSON, first-1MB sha256, meta_matches
├── compose.py        # ffmpeg wrapper for audio+image+SRT -> 1080p MP4 (intro flow, untouched)
├── compose_cli.py    # video2yt-compose entry point
├── merge.py          # strict segment validation, concat + per-seg loudnorm, chapters embed
├── merge_cli.py      # video2yt-merge entry point
├── validate.py       # ffprobe + source/ASS/output validators
└── cuts.py           # cut range parsing, normalization, keep_ranges, ASS rewriter
```

Tests live in `tests/test_smoke.py` (~530 tests covering fetch / burn / cli / compose / merge / music_library) plus `tests/test_stems.py` (23) / `tests/test_music_mix.py` (12) / `tests/test_subtitle.py` (87) / `tests/test_burn_all.py` (23). All external tools (ffmpeg, ffprobe, yt-dlp, song-remover, whisperx, codex) are mocked at the `subprocess.run` boundary — no network, no real subprocess in CI. `tests/test_burn_real_ffmpeg.py` is opt-in (skipped unless ffmpeg+libass is on PATH) and exercises the chained-subtitles + amix graph against real ffmpeg — see T10 of the step6-restructure plan.

`cli.run()` flow (the orchestrator, T7 of step6-restructure):

```
preflight → early Modal-token check (only when needs_stems and --device remote) →
Stage 1 fetch.fetch_and_build → Stage 2 stems.separate (gated on needs_stems) →
Stage 3 subtitle_cli.run (gated on --no-subtitle) → Stage 4 music_mix.render
(gated on --no-music-swap) → Stage 5 burn.render (single ffmpeg pass) →
copy music_credits.txt next to <bv>_final.mp4 → validate output
```

Each stage logs its wall-clock to the per-run timings summary.

## Feature flags quick reference

```
--quality {480,720,1080}: yt-dlp format height cap (Stage 1)
--codec {h264,h265,auto}: format codec preference (default h264 for YouTube) (Stage 1)
--font-face NAME:        ASS font family (default "Hiragino Sans GB", macOS-accessible CJK)
--font-size N:           Danmaku font size (default auto: video_height * 25/540 per Bilibili native)
--preview-seconds N:     ffmpeg -t clamp on output
--cut START~END:         remove time ranges, repeatable, ~ separator, SS/MM:SS/HH:MM:SS
--speed {0.5..2.0}:      playback multiplier via setpts+atempo (pitch preserved)
--no-subtitle:           skip Stage 3 (STT subtitle)
--no-music-swap:         skip Stage 4 (CC0 bed); Stage 5 maps source audio
--device {cpu,mps,auto,remote}: Stage 2 song-remover device (default remote = Modal GPU)
--chunk-min N:           Stage 2 chunk length for --device remote (default 5)
--keep-temp:             no-op (everything kept by default since T7)
```

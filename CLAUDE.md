# CLAUDE.md

Project context for Claude agents working in this repo.

## Purpose

A local CLI that takes a Bilibili video URL and produces an MP4 with danmaku burned in. Pipeline: `yt-dlp` (video + raw danmaku XML) → `biliass.convert_to_ass` (in-process) → `ffmpeg` (`subtitles=` filter, optionally inside a `filter_complex` cut/concat/speed chain) → output MP4. Supports `--preview-seconds` for fast iteration, `--cut START~END` to remove time ranges from the output, `--speed FLOAT` for playback-multiplier output, `--codec` to pick h264/h265, and Bilibili-accurate font sizing.

## Commands

```bash
uv run video2yt "<url>"                                    # full video
uv run video2yt "<url>" --preview-seconds 60               # first 60s
uv run video2yt "<url>" --cut 30~60 --cut 2:15~2:45        # remove ranges
uv run video2yt "<url>" --speed 1.5                        # 1.5x playback
uv run video2yt "<url>" --font-size 48 --codec h265        # style overrides
uv run video2yt "<url>" -o output/<project>/                # nest into per-project folder (recommended)
uv run python -m video2yt "<url>"                          # run as module
uv run video2yt-compose --audio a.mp3 --image bg.jpg --srt subs.srt --title "T"   # compose from stills
uv run video2yt-merge --segment a.mp4 --label "A" --segment b.mp4 --label "B" --segment c.mp4 --label "C" --title "T"   # concat + loudnorm + chapters (≥3 segments, each ≥10s)
uv run video2yt-subtitle seg.mp4 --danmaku raw.xml         # add STT subtitles if not already present
uv run video2yt-music-swap seg.mp4                         # swap copyrighted BGM for royalty-free music
uv run pytest                                              # run tests (230)
uv add <pkg>                                               # add a dep (NEVER edit pyproject.toml deps by hand)
```

## External dependencies

- `ffmpeg` and `ffprobe` must be in PATH (system install, not Python package). Check with `shutil.which('ffmpeg')`.
- video2yt downloads the raw danmaku XML via `yt-dlp --write-subs --sub-langs danmaku` and converts to ASS in-process using `biliass.convert_to_ass`, so the height and font_size are known before conversion. The `yt-dlp-danmaku` plugin is no longer used as a postprocessor (refactored away in `aa1d91c`); we still depend on the `biliass` Python package that ships with it.

## Project folder convention

When working on a multi-step video project (intro + multiple burnt segments + final merge), pass `-o output/<project>/` to every `video2yt` / `video2yt-compose` / `video2yt-merge` invocation so all artifacts land under one folder. Example: `output/back2back/` contains `intro.mp4`, segment subfolders, the final merged MP4, the YouTube thumbnail, and any scratch files. This keeps unrelated projects isolated and makes cleanup easy.

## Battlegrounds workflow rule (intro-script drafting)

For Hearthstone Battlegrounds video projects, **never draft the intro script before verifying the topic's terminology**. After the `ringnaga` mistake (drafted assuming "護戒" was a Spellcraft buff when it actually meant the card 戒指龍 / Ring Bearer), this is hard rule:

1. Run `WebFetch https://search.bilibili.com/all?keyword=<策略名>` and read the top UP-主 video titles + descriptions.
2. Confirm the 流派 pivots on the right card / hero (typically a 6-7星核心隨從).
3. Use BG vocabulary (阵容/隨從/酒館/餵/疊屬性/吃雞), NOT constructed-mode vocabulary (牌組/起手/過渡). Full glossary in `docs/superpowers/specs/2026-04-18-video-production-workflow.md` Step 1.

## Known gotchas

- **ffmpeg `subtitles=` filter path escaping**: The `subtitles=<path>` filter in `-vf` chokes on absolute paths containing spaces, colons, or parentheses. Workaround in `burn.py`: run `subprocess` with `cwd=temp_dir` and pass the ASS filename as a basename; the `-i` input is also a basename (only the output path is absolute). ffmpeg 8+ is stricter and requires the explicit `subtitles=f='<name>'` quoted form (see the `-vf` line and docstring in `src/video2yt/burn.py`).
- **ffmpeg must be built with libass**: the default `brew install ffmpeg` bottle does NOT always include libass, so the `subtitles` filter we rely on is missing. Symptom: ffmpeg emits `No option name near '<filename.ass>'` or `No such filter: 'subtitles'` — it looks like a quoting bug but isn't. Fix: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`. Pre-flight check: `ffmpeg -filters | grep subtitles` must list the filter.
- **yt-dlp release cadence**: yt-dlp updates frequently because Bilibili's extractor rules shift. If downloads suddenly break, first try `uv lock --upgrade-package yt-dlp`.
- **Chrome cookie DB lock**: `--cookies-from-browser chrome` requires Chrome to not be holding the cookie database lock. If it fails, close Chrome first.
- **Cut boundary dialogues are dropped, not clipped**: when a danmaku dialogue intersects a `--cut` range (even by a single frame), the whole dialogue is dropped. Rationale: simpler semantics, avoids partial-display weirdness. See `src/video2yt/cuts.py::rewrite_ass_for_cuts`.
- **Filter_complex path for cuts**: when `--cut` is used, `burn.render` builds a `filter_complex` with `trim`/`atrim`/`concat`/`subtitles` and uses `-c:a aac` (can't `copy` after `atrim`). No-cut runs use the simple `-vf subtitles=` path with `-c:a copy`.
- **Speed forces filter_complex**: any non-1.0 `--speed` value routes through the `filter_complex` path (`atempo` can't coexist with `-c:a copy`). `_build_filter_complex` emits uniform `[outv]`/`[outa]` final labels and uses `null`/`anull` passthrough filters to keep the graph shape consistent whether cut, speed, both, or neither are present. Subtitles are burned BEFORE `setpts` so danmaku are baked in at the original timeline and then time-scaled along with the rest of the frame.
- **Raw download caching**: `download.fetch` checks `temp_dir` for `<bv>.{mp4,mkv,webm}` AND `<bv>*.xml` before invoking yt-dlp; if both are present, it skips yt-dlp entirely and returns `from_cache=True` (cli logs `using cached download from …`). Default cleanup in `cli.run` removes only the derived ASS files (`<bv>.danmaku.ass`, `<bv>.danmaku.cut.ass`) and INTENTIONALLY leaves the raw mp4 + XML on disk so the next run hits the cache. `--keep-temp` additionally preserves the derived ASS files. To force a fresh download, delete the specific subfolder under `temp/` by hand.
- **Agent E2E test rule**: DO NOT run `rm -rf output/` or `rm -rf temp/` during E2E tests — that wipes every cached raw download and the outputs of unrelated videos. Clean only the specific `temp/<subfolder>/` under test, or just let the cache hit on the next run. This is a workflow rule, not a code invariant.
- **Output filename suffixes**: `_cut`, `_<speed>x`, `_preview` get appended to `<bv>_with_danmaku.mp4` based on flags, so different parameter combos coexist. Default (no modifiers) keeps the original filename. See `cli._build_output_filename`.
- **compose SRT path escaping**: `compose.render` uses `cwd=<srt.parent>` and references the SRT by basename in the `subtitles` filter (same trick as `burn.py`). Absolute paths for `-i` inputs are fine because `-i` doesn't go through filter_complex.
- **merge strict mode**: all `--segment` inputs must be 1920x1080 30fps h264 AND ≥10s long, and there must be ≥3 segments. The 10s/3-segment rules mirror YouTube's chapter requirements — fewer/shorter chapters means YouTube discards the chapter list. No auto-normalization. Fail fast with all violations listed.
- **merge chapters**: there is no burned-in progress bar — segmentation is delivered as chapter markers. The **only officially-supported** YouTube chapter source is timestamps in the video description (≥3 ascending, first at 00:00, each ≥10s, exactly one block). merge produces two outputs: `<title>_chapters.txt` is the description paste (this is the supported path); `<title>_ffmeta.txt` is embedded into the MP4 via `-map_metadata`/`-map_chapters` as a best-effort extra — YouTube does NOT officially document reading embedded chapter atoms, so do NOT treat the embed as a safety net. Common breakage: a description with two timestamp blocks (繁體 + 简体) is not strictly ascending and YouTube discards the whole list — keep the block to exactly one occurrence.
- **music-swap is risk reduction, not a guarantee**: `video2yt-music-swap` isolates the commentary voice (Demucs) and discards the original music+SFX mix, so the game sound effects are lost by design (Approach A — see `docs/superpowers/specs/2026-05-20-music-swap-design.md`). Demucs separation is imperfect: faint music can bleed into the vocals stem, and the replacement track carries its own claim risk. It strongly suppresses the streamer's music but does not mathematically guarantee a claim-free upload. Demucs is also slow (10–30 min for a 17-min segment on CPU; faster on Apple Silicon MPS).
- **music-swap library + attribution**: the music bed is built from `~/.cache/video2yt/music/` (the source of truth). On first run the tool auto-downloads a shipped manifest (`src/video2yt/data/music_library.json`) of calm Kevin MacLeod tracks from the Internet Archive — these are **CC BY 3.0, so attribution is required**. `render` writes `<output>_music_credits.txt`; those lines MUST go in the YouTube description. To avoid attribution, drop YouTube Audio Library tracks into the cache dir by hand (cache files with no manifest entry need no credit). Expand the manifest with any archive.org direct-MP3 URL + real `sha256`/`duration`/`attribution`. NEVER put YouTube Audio Library tracks in the manifest — its license forbids redistribution.
- **music-swap needs `soundfile`**: Demucs (via torchaudio) has no default backend without `soundfile` installed and a fresh clone will fail with `RuntimeError: Couldn't find appropriate backend to handle uri ... vocals.wav and format None`. Already in `pyproject.toml` since commit `c47d35e`; if you ever hit it on a new machine, `uv add soundfile`.
- **Bilibili VIP-locked 1080p**: some BV sources only expose 480p/360p without a premium account (yt-dlp `-F` confirms with `1080P ... you have to become a premium member`). `video2yt-merge` enforces strict 1920x1080 30fps h264, so a 480p burnt segment will fail merge late after burning + music-swap already burned 30+ min. **Pre-flight**: after `video2yt` burn, eyeball the "probing source video" log — if it warns about lower-than-requested resolution, either upscale via `ffmpeg -i in.mp4 -vf "scale=1920:1080:flags=lanczos" -c:v libx264 -preset medium -crf 20 -pix_fmt yuv420p -r 30 -c:a copy out.mp4` (~5–10 min for 18 min input, visibly softer but presentable) or swap source.
- **video2yt-subtitle cold cleanup is ~13 min**: codex-based glossary cleanup on a 31-line BG transcript takes ~775s wall-clock; default `CLEANUP_TIMEOUT_SECONDS = 1200` (20 min) leaves headroom. Total pipeline on a 17-min segment: ~8 min ASR + ~13 min cleanup + ~3 min burn ≈ **24 min**, slower than realtime. SenseVoice was rejected (returns one giant string with no per-segment timestamps and hallucinates lyrics on BGM-heavy clips); whisperx large-v3 is the engine. `--enable-ocr` is **off by default** — HS hand-cards are stable bottom text and trigger false positives.
- **subtitle passthrough never hardlinks**: `passthrough` and `burn_subtitles` both refuse on `samefile(src, dst)` and `passthrough` always copies, never hardlinks — eliminates the data-loss class where ffmpeg `-y` on a hardlinked output truncates the input.

## Architecture

```
src/video2yt/
├── cli.py            # arg parsing, run() orchestration, per-phase timing,
│                     # subfolder naming (<uploader[:4]>：<title>), font_size auto
├── download.py       # yt-dlp wrapper (fetch with raw-download cache + get_metadata + generate_ass via biliass)
├── burn.py           # ffmpeg wrapper (simple -vf path + filter_complex path for cuts)
├── compose.py        # ffmpeg wrapper for audio+image+SRT -> 1080p MP4 (standalone from burn.py)
├── compose_cli.py    # video2yt-compose entry point (parse_args/run/main)
├── merge.py          # strict segment validation, ffmpeg filter_complex with concat + per-seg
│                     # loudnorm, chapters.txt + ffmetadata embedded into the MP4 via -map_chapters
├── merge_cli.py      # video2yt-merge entry point (parse_args/run/main)
├── validate.py       # ffprobe + source/ASS/output validators
├── cuts.py           # cut range parsing, normalization, keep_ranges, ASS rewriter
├── subtitle.py       # detect (danmaku XML + OCR) + SenseVoice ASR + Codex cleanup + split + burn
├── subtitle_cli.py   # video2yt-subtitle entry point
├── music_swap.py     # extract → Demucs vocal isolation → CC0 bed → mix → remux
├── music_swap_cli.py # video2yt-music-swap entry point
└── music_library.py  # CC0 manifest + download cache + track selection
```

Tests live in `tests/test_smoke.py` (162 tests). Everything is mocked at the `subprocess.run` boundary — no network, no ffmpeg, no ffprobe is actually invoked in tests.

`cli.run()` flow: preflight → extract BV → fetch metadata → build per-video subfolder → `download.fetch` (cache-hit if raw files present, else yt-dlp) → probe source → compute auto font size → `biliass.convert_to_ass` → parse/normalize `--cut` → rewrite ASS for cuts → `burn.render` → probe output and validate against `expected_duration` → cleanup (derived ASS only by default, plus keep everything with `--keep-temp`; raw mp4+xml always preserved). Each phase is timed and logged.

`compose_cli.run()` flow (the `video2yt-compose` entry point): preflight → validate input files exist → `validate.probe` the audio (must have an audio stream) → `compose.check_srt` (≥1 timecode block required, UTF-8 with GBK fallback) → `_sanitize_title` → `compose.render` (ffmpeg `-loop 1` image + audio with `filter_complex` scale/pad/subtitles, libx264 tune stillimage, aac 192k, `-shortest`) → probe output and assert 1920x1080 h264 + audio + duration within 1s of input audio. All inputs and behavior are independent of `cli.py`; no existing pipeline was touched.

## Feature flags quick reference

```
--quality {480,720,1080}: yt-dlp format height cap
--codec {h264,h265,auto}: format codec preference (default h264 for YouTube)
--font-face NAME:        ASS font family (default "Hiragino Sans GB", macOS-accessible CJK)
--font-size N:           Dialogue font size (default auto: video_height * 25/540 per Bilibili native)
--preview-seconds N:     ffmpeg -t clamp on output
--cut START~END:         remove time ranges, repeatable, ~ separator, SS/MM:SS/HH:MM:SS
--speed {0.5..2.0}:      playback multiplier via setpts+atempo (pitch preserved); any non-1.0 forces filter_complex
--keep-temp:             also retain derived ASS files (raw mp4+xml are ALWAYS kept for caching)
```

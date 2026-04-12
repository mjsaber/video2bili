# CLAUDE.md

Project context for Claude agents working in this repo.

## Purpose

A local CLI that takes a Bilibili video URL and produces an MP4 with danmaku burned in. Pipeline: `yt-dlp` (video + raw danmaku XML) → `biliass.convert_to_ass` (in-process) → `ffmpeg` (`subtitles=` filter, optionally inside a `filter_complex` cut/concat chain) → output MP4. Supports `--preview-seconds` for fast iteration, `--cut START~END` to remove time ranges from the output, `--codec` to pick h264/h265, and Bilibili-accurate font sizing.

## Commands

```bash
uv run video2yt "<url>"                                    # full video
uv run video2yt "<url>" --preview-seconds 60               # first 60s
uv run video2yt "<url>" --cut 30~60 --cut 2:15~2:45        # remove ranges
uv run video2yt "<url>" --font-size 48 --codec h265        # style overrides
uv run python -m video2yt "<url>"                          # run as module
uv run pytest                                              # run tests (120)
uv add <pkg>                                               # add a dep (NEVER edit pyproject.toml deps by hand)
```

## External dependencies

- `ffmpeg` and `ffprobe` must be in PATH (system install, not Python package). Check with `shutil.which('ffmpeg')`.
- video2yt downloads the raw danmaku XML via `yt-dlp --write-subs --sub-langs danmaku` and converts to ASS in-process using `biliass.convert_to_ass`, so the height and font_size are known before conversion. The `yt-dlp-danmaku` plugin is no longer used as a postprocessor (refactored away in `aa1d91c`); we still depend on the `biliass` Python package that ships with it.

## Known gotchas

- **ffmpeg `subtitles=` filter path escaping**: The `subtitles=<path>` filter in `-vf` chokes on absolute paths containing spaces, colons, or parentheses. Workaround in `burn.py`: run `subprocess` with `cwd=temp_dir` and pass the ASS filename as a basename; the `-i` input is also a basename (only the output path is absolute). ffmpeg 8+ is stricter and requires the explicit `subtitles=f='<name>'` quoted form (see the `-vf` line and docstring in `src/video2yt/burn.py`).
- **ffmpeg must be built with libass**: the default `brew install ffmpeg` bottle does NOT always include libass, so the `subtitles` filter we rely on is missing. Symptom: ffmpeg emits `No option name near '<filename.ass>'` or `No such filter: 'subtitles'` — it looks like a quoting bug but isn't. Fix: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`. Pre-flight check: `ffmpeg -filters | grep subtitles` must list the filter.
- **yt-dlp release cadence**: yt-dlp updates frequently because Bilibili's extractor rules shift. If downloads suddenly break, first try `uv lock --upgrade-package yt-dlp`.
- **Chrome cookie DB lock**: `--cookies-from-browser chrome` requires Chrome to not be holding the cookie database lock. If it fails, close Chrome first.
- **Cut boundary dialogues are dropped, not clipped**: when a danmaku dialogue intersects a `--cut` range (even by a single frame), the whole dialogue is dropped. Rationale: simpler semantics, avoids partial-display weirdness. See `src/video2yt/cuts.py::rewrite_ass_for_cuts`.
- **Filter_complex path for cuts**: when `--cut` is used, `burn.render` builds a `filter_complex` with `trim`/`atrim`/`concat`/`subtitles` and uses `-c:a aac` (can't `copy` after `atrim`). No-cut runs use the simple `-vf subtitles=` path with `-c:a copy`.
- **Raw download caching**: `download.fetch` checks `temp_dir` for `<bv>.{mp4,mkv,webm}` AND `<bv>*.xml` before invoking yt-dlp; if both are present, it skips yt-dlp entirely and returns `from_cache=True` (cli logs `using cached download from …`). Default cleanup in `cli.run` removes only the derived ASS files (`<bv>.danmaku.ass`, `<bv>.danmaku.cut.ass`) and INTENTIONALLY leaves the raw mp4 + XML on disk so the next run hits the cache. `--keep-temp` additionally preserves the derived ASS files. To force a fresh download, delete the specific subfolder under `temp/` by hand.
- **Agent E2E test rule**: DO NOT run `rm -rf output/` or `rm -rf temp/` during E2E tests — that wipes every cached raw download and the outputs of unrelated videos. Clean only the specific `temp/<subfolder>/` under test, or just let the cache hit on the next run. This is a workflow rule, not a code invariant.

## Architecture

```
src/video2yt/
├── cli.py            # arg parsing, run() orchestration, per-phase timing,
│                     # subfolder naming (<uploader[:4]>：<title>), font_size auto
├── download.py       # yt-dlp wrapper (fetch with raw-download cache + get_metadata + generate_ass via biliass)
├── burn.py           # ffmpeg wrapper (simple -vf path + filter_complex path for cuts)
├── validate.py       # ffprobe + source/ASS/output validators
└── cuts.py           # cut range parsing, normalization, keep_ranges, ASS rewriter
```

Tests live in `tests/test_smoke.py` (120 tests). Everything is mocked at the `subprocess.run` boundary — no network, no ffmpeg, no ffprobe is actually invoked in tests.

`run()` flow: preflight → extract BV → fetch metadata → build per-video subfolder → `download.fetch` (cache-hit if raw files present, else yt-dlp) → probe source → compute auto font size → `biliass.convert_to_ass` → parse/normalize `--cut` → rewrite ASS for cuts → `burn.render` → probe output and validate against `expected_duration` → cleanup (derived ASS only by default, plus keep everything with `--keep-temp`; raw mp4+xml always preserved). Each phase is timed and logged.

## Feature flags quick reference

```
--quality {480,720,1080}: yt-dlp format height cap
--codec {h264,h265,auto}: format codec preference (default h264 for YouTube)
--font-face NAME:        ASS font family (default "Hiragino Sans GB", macOS-accessible CJK)
--font-size N:           Dialogue font size (default auto: video_height * 25/540 per Bilibili native)
--preview-seconds N:     ffmpeg -t clamp on output
--cut START~END:         remove time ranges, repeatable, ~ separator, SS/MM:SS/HH:MM:SS
--keep-temp:             also retain derived ASS files (raw mp4+xml are ALWAYS kept for caching)
```

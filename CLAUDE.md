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

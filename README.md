# video2yt

A local Python CLI toolkit for producing Battlegrounds videos for YouTube: source discovery, Bilibili downloads, danmaku and speech subtitles, replacement music, intros, thumbnails, publishing and measurement.

The main command runs five cached stages: `fetch → stems → subtitle → music-mix → burn`. The final FFmpeg pass combines both subtitle layers, speech and music, cuts, and playback speed. See [CLAUDE.md](CLAUDE.md) for engineering context and [the production workflow](docs/superpowers/specs/2026-04-18-video-production-workflow.md) for the editorial process.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` in PATH, built with libass (macOS: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`)
- Chrome browser installed (for cookie-based login to access 1080p content)

## Install

```bash
uv sync
```

### Speech separation and subtitles

The default pipeline uses the external `song-remover` tool for Stage 2. Install it from `~/code/song-remover` with `uv tool install '.[remote]'`, then complete its Modal setup for the default `--device remote`, or use `--device cpu` for local separation. See [CLAUDE.md](CLAUDE.md#external-dependencies) for setup.

Stage 3 (`video2yt-subtitle`) shells out to the external `speech2srt` CLI (Volcengine 火山 Seed-ASR + codex cleanup) since 2026-05-27. Per the speech2srt-integration plan in `docs/superpowers/plans/2026-05-27-speech2srt-integration.md`:

- **Install once**: `cd ~/code/speech2srt && uv tool install . --force`
- **API key**: `VOLCENGINE_API_KEY` either exported or in `.env` at the cwd (get it from 火山引擎控制台 → 语音技术 → 豆包录音文件识别模型2.0)
- **Codex CLI**: `brew install codex && codex login` — used by Stage 3 cleanup (NOT by the intro alignment SRT, which is pure ffmpeg)
- **Intro alignment (`video2yt-transcribe`)**: pure ffmpeg/ffprobe since 2026-07-04 — speech span via `silencedetect`, proportional script slicing. whisperx was removed (see docs/superpowers/specs/2026-07-04-transcribe-ffmpeg-span.md).
- **Per-project context file**: `output/<project>/subtitle_context.txt` (≤ 2 KB UTF-8) describing the streamer, 流派, key cards, 口頭禪, known ASR errors. Pass via `--subtitle-context-file` on `video2yt`. See CLAUDE.md "Subtitle / speech2srt" for full operating details.
- **Skip Stage 3** entirely with `--no-subtitle` for streamers whose source already has burnt-in subs (e.g. 郭楓荷).

The old `rapidocr-onnxruntime` / `--enable-ocr` flow was removed before the speech2srt cutover.

## Quick start

```bash
# Full pipeline (requires song-remover and speech2srt setup)
uv run video2yt "https://www.bilibili.com/video/BVxxxxxxxxxx/"

# Danmaku only, retaining source audio
uv run video2yt "https://www.bilibili.com/video/BVxxxxxxxxxx/" --no-subtitle --no-music-swap
```

The tool downloads the video and raw danmaku XML, converts danmaku to ASS with `biliass`, then runs the enabled audio/subtitle stages and produces `./output/<uploader>：<title>/<bv>_final.mp4`.

## Usage

```bash
uv run video2yt <url> [options]
```

| Flag | Default | Description |
|---|---|---|
| `url` (positional) | — | Bilibili video URL (must contain a `BV...` id) |
| `-o, --output-dir` | `./output` | Where the final MP4 goes (under a per-video subfolder) |
| `-t, --temp-dir` | `./temp` | Per-stage cache: raw video/XML, ASS, audio stems, subtitle sidecars and music bed. Preserved after success. |
| `-q, --quality` | `1080` | Max video quality, one of `{480, 720, 1080}` |
| `-b, --browser` | `chrome` | Browser to read cookies from |
| `--codec` | `h264` | Video codec preference, one of `{h264, h265, auto}`. `h264` is most compatible / preferred by YouTube; `h265` produces smaller files; `auto` lets yt-dlp pick. |
| `--font-face` | `Hiragino Sans GB` | ASS font family. The default is preinstalled on macOS and visible to libass via fontconfig. |
| `--font-size` | `auto` | Pixel size for a standard (nominal=25) danmaku. Default `auto` uses Bilibili's native formula `video_height * 25 / 540` (≈ `height / 21.6`). |
| `--preview-seconds` | none | If set, cap the burned output to the first N seconds (`ffmpeg -t N`). Useful for fast style/codec iteration. |
| `--cut START~END` | none | Remove a time range from the output. Repeatable. See [Time format for `--cut`](#time-format-for---cut). |
| `--speed FLOAT` | `1.0` | Playback speed multiplier for the output. Range `[0.5, 2.0]`. Common values: `1.1`, `1.25`, `1.5`, `2.0`. Applies to video, audio (pitch preserved via ffmpeg `atempo`), and danmaku together. |
| `--keep-temp` | off | Compatibility no-op; all stage caches are always preserved. |
| `--no-subtitle` | off | Skip speech transcription/subtitles, for example when the source already has subtitles. |
| `--subtitle-context-file PATH` | none | Project-specific streamer/card terminology context for subtitle cleanup (≤2 KB UTF-8). |
| `--no-music-swap` | off | Retain source audio instead of separated speech and replacement music. |
| `--no-danmaku` | off | Allow a source with zero danmaku; does not suppress existing comments. |
| `--device` | `remote` | Separation device: `cpu`, `mps`, `auto`, or Modal `remote`. |
| `--chunk-min` | `5` | Remote separation chunk length in minutes. |

## Output layout

For each run video2yt creates a per-video subfolder named `<uploader[:4]>：<title>` (using the fullwidth colon U+FF1A) under both `--output-dir` and `--temp-dir`. The title is sanitized for filesystem safety and truncated to 60 characters.

```
output/
└── 哈哈：某个搞笑视频的标题/
    └── BV1xxxxxxxxx_final.mp4
```

If the uploader is missing the subfolder is just `<title>`; if both are missing it falls back to the BV id.

## Output filenames

The output MP4 is named `<bv_id>_final[_<suffix>].mp4`, where the suffix encodes which non-default options were used. The former `_with_danmaku`, `_clean`, and `_subbed` stage suffixes have been replaced by `_final`.

Suffix parts (in fixed order):

- `_cut` if any `--cut` ranges were provided
- `_<speed>x` if `--speed != 1.0` (e.g. `_1.5x`, `_1.25x`, `_2x`)
- `_preview` if `--preview-seconds` was provided

Because the order is fixed, a given parameter combination always produces the same filename — so different combinations coexist on disk and re-running the same settings overwrites the previous output deterministically.

| `--cut` | `--speed` | `--preview-seconds` | filename |
|---|---|---|---|
| no  | 1.0  | no  | `BV_final.mp4` |
| no  | 1.5  | no  | `BV_final_1.5x.mp4` |
| yes | 1.0  | no  | `BV_final_cut.mp4` |
| yes | 1.5  | no  | `BV_final_cut_1.5x.mp4` |
| no  | 1.25 | yes | `BV_final_1.25x_preview.mp4` |
| yes | 1.0  | yes | `BV_final_cut_preview.mp4` |
| yes | 1.5  | yes | `BV_final_cut_1.5x_preview.mp4` |

Note: the preview duration is intentionally NOT encoded in the filename. Preview is for iteration, so different preview lengths overwrite each other by design; if you need to keep multiple previews, rename them manually.

## Examples

```bash
# Simple full-video run
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/"

# Preview the first 60 seconds (fast iteration on style/codec)
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" --preview-seconds 60

# Remove a single time range
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" --cut 37~59

# Remove multiple ranges
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" \
    --cut 0:30~1:00 --cut 2:15~2:45

# 1.5x playback speed (pitch preserved)
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" --speed 1.5

# Cut a range and double the playback speed
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" --cut 30~60 --speed 2

# 720p h265 for smaller files
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" -q 720 --codec h265

# Custom font face and explicit font size
uv run video2yt "https://www.bilibili.com/video/BV1xxxxxxxxx/" \
    --font-face "Noto Sans CJK SC" --font-size 48
```

## Time format for `--cut`

Each `--cut` value is `START~END` (separator is `~`, U+007E). Both sides accept three formats, disambiguated by the number of `:` delimiters:

| Form | Example | Seconds |
|---|---|---|
| `SS` | `30`, `90.5` | 30, 90.5 |
| `MM:SS` | `0:30`, `5:12.5` | 30, 312.5 |
| `HH:MM:SS` | `0:00:30`, `1:10:05.25` | 30, 4205.25 |

Fractional seconds are allowed in any form. `--cut` is repeatable; ranges are auto-swapped if `start > end`, zero-width ranges are dropped, overlapping/touching ranges are merged. The cut list may not cover the entire video.

`--cut` and `--preview-seconds` interact in this order: cut is applied first on the source timeline, then preview clamps the resulting (shorter) timeline. So `--cut 30~60 --preview-seconds 60` on a 5-minute source produces a 60-second output containing source `[0, 30) ∪ [60, 90)`.

## Playback speed (`--speed`)

`--speed FLOAT` (default `1.0`) multiplies the playback speed of the output. Range: `0.5` (half-speed) to `2.0` (double-speed). Common values: `1.1`, `1.25`, `1.5`, `2.0`. Speed applies to video, audio (pitch preserved via ffmpeg `atempo`), and danmaku together — the danmaku is burned onto the original timeline first and then the whole frame is time-scaled, so bullets move faster naturally. Any non-1.0 speed forces the `filter_complex` path (`atempo` can't coexist with `-c:a copy`), so audio is re-encoded.

## Caching

video2yt caches raw downloads (the yt-dlp `<bv>.mp4` and `<bv>.danmaku.xml`) in `temp/<title_subfolder>/`. Subsequent runs of the same video reuse the cached mp4 and XML without re-downloading — `download.fetch` checks for both files and, if present, skips yt-dlp entirely and logs `using cached download from …`.

Each downstream stage also keeps its cache. Use `video2yt-stems --force`,
`video2yt-subtitle --force-asr`, or `video2yt-music-mix --force` to regenerate one
stage. To force a new source download, remove only that source's cached MP4/XML;
never wipe the entire `temp/` or `output/` directory.

After a verified publication, use `video2yt-cleanup --project <project>` to inspect
its cleanup plan, then `--yes` to apply it. The tool archives lightweight artifacts
before reclaiming media and keeps the current published output as a buffer.

## Notes

- Chrome must be quit before running so `--cookies-from-browser` can read the cookie database (it requires an exclusive lock).
- Preview mode still downloads the full video; only the burn step is clamped. Future optimization could trim during download.
- When `--cut` is in play the burn step uses an `ffmpeg filter_complex` chain (`trim`/`atrim`/`concat`/`subtitles`) — a single encode pass over the whole timeline.
- Danmaku that straddle a cut boundary are dropped entirely rather than clipped or shifted in fragments. This keeps the rules simple and avoids partial-display weirdness; in practice few dialogues happen to span a cut.

## Compose from audio + image + SRT

Separate entry point `video2yt-compose` for creating a 1080p MP4 from an audio file, a static background image, and an SRT subtitle file. Useful for podcast uploads, lecture recordings, audiobook chapters, etc.

### Usage

```bash
uv run video2yt-compose \
  --audio path/to/audio.mp3 \
  --image path/to/background.jpg \
  --srt path/to/subs.srt \
  --title "My Video Title"
```

### Options

| Flag | Default | Description |
|---|---|---|
| `--audio PATH` | required | Audio file (mp3/m4a/wav/flac/ogg/etc.) |
| `--image PATH` | required | Background image (jpg/png/webp) |
| `--srt PATH` | required | SRT subtitle file (UTF-8 or GBK) |
| `--title TITLE` | required | Used for subfolder and output filename |
| `-o, --output-dir DIR` | `./output` | Output base directory |
| `--font-face NAME` | `Hiragino Sans GB` | Subtitle font family |
| `--font-size N` | `42` | Subtitle font size in pixels |

### Output

The final MP4 goes to `<output_dir>/<sanitized_title>/<sanitized_title>.mp4`.

### Behavior notes

- Video: 1080p h264 (libx264 preset medium crf 20, tuned for still image), yuv420p, 30 fps
- Audio: AAC 192 kbps
- Duration: matches the input audio (image loops via `-loop 1 -shortest`)
- Subtitles: burned in via ffmpeg's `subtitles` filter with hard-coded style (white text, black outline 2px, centered bottom, MarginV 80). Only `--font-face` and `--font-size` are adjustable from the CLI.
- Image: scaled to fit 1920x1080 with aspect ratio preserved, black bars added where needed (letterbox). No stretching.
- SRT must contain at least one valid timecode block; empty/malformed SRTs fail fast.
- Libass with a CJK font must be installed (see "Requirements" above).

## Merge segments into one video

Concatenate multiple 1080p h264 segments with loudness-normalized audio and chapter markers — embedded into the output MP4 and also written as a YouTube chapters text file.

### Usage

```bash
uv run video2yt-merge \
  --segment intro.mp4 --label "Intro" \
  --segment part1.mp4 --label "第一部分" \
  --segment part2.mp4 --label "第二部分" \
  --title "完整视频标题"
```

### Options

| Flag | Required | Description |
|---|---|---|
| `--segment PATH` | yes (repeatable) | Input segment. Must be 1920x1080 30fps h264. |
| `--label TEXT` | yes (repeatable) | Chapter label for the corresponding segment. |
| `--title TITLE` | yes | Output filename stem and chapters file prefix. |
| `-o, --output PATH` | no | Output MP4 path. Default: first segment's parent directory + `<title>.mp4`. |
| `--chapters-file PATH` | no | Editorial chapter timestamps on the final-video timeline. |
| `--no-chapters` | no | Disable chapter generation. |

### Outputs

- `<output_dir>/<title>.mp4` — final merged video, with chapter markers when enabled and valid
- `<output_dir>/<title>_chapters.txt` — valid YouTube-format chapter markers, when generated (paste into video description)
- `<output_dir>/<title>_ffmeta.txt` — chapter metadata embedded into the MP4 when generated (kept for inspection)

### Behavior

- **Media validation**: one or more positive-length 1920x1080 30fps h264 segments with audio. Short hooks and single-source videos are supported. Chapters are independent: `--chapters-file PATH` accepts final-video timestamp text, `--no-chapters` disables chapters. By default segment boundaries become chapters only if valid (3+, first 00:00, each ≥10s); otherwise the video renders without chapters and stale chapter sidecars are removed.
- **Per-segment audio normalization**: each segment's audio goes through `loudnorm=I=-14:TP=-1:LRA=11` (YouTube reference loudness) before concatenation.
- **Chapters**: valid segment boundaries become automatic chapters, or provide independent editorial timestamps with `--chapters-file`. The officially-supported way to get chapters onto YouTube is via the video description, so `<title>_chapters.txt` is written in YouTube's text format (first chapter at `00:00`) — paste it into the description as a single ascending block. The same chapters are also embedded into the output MP4 (`-map_metadata`/`-map_chapters`) as a best-effort extra; this isn't officially documented as supported by YouTube, so don't treat it as a fallback for a missing/broken description block.

## Replace background music

Replacement music is enabled by default. Stage 2 invokes `song-remover` and keeps
all four audio stems; Stage 4 builds a music bed; Stage 5 mixes the speech stem
with that bed and ducks the bed during speech. Source game effects are discarded
with the original mix. Use `--no-music-swap` to retain source audio.

For an existing fetched source, run the stages independently (this example keeps danmaku and skips speech subtitles):

```bash
uv run video2yt-stems 'temp/<source>/<bv>.mp4'
uv run video2yt-music-mix 'temp/<source>/<bv>.mp4' --seed 1
uv run video2yt-burn 'temp/<source>/' --bv '<bv>' --no-subtitle -o 'output/<project>/<bv>_final.mp4'
```

The former `video2yt-music-swap` CLI is retired. The shipped music manifest
contains CC BY 3.0 tracks that require attribution: copy the generated
`<bv>_final_music_credits.txt` into the YouTube description. The current bed-volume
baseline is 0.12. Listen to a short preview to check speech clarity and residual
music; separation does not guarantee that a source is free of Content ID claims.

## Development

```bash
uv run --extra dev pytest -q
```

Most external-service boundaries are mocked. Tests that require FFmpeg/libass
use local synthetic media and skip when the required tools are unavailable.
No real upload or OAuth collection is needed to run the suite.

## Publishing reliability and growth workflow

See [the growth workflow](docs/growth-workflow.md) for result-first hooks, decision-led editing, configurable thumbnail experiments, contextual CTA, safe publishing, and 24h/7d/28d review. These defaults supersede the old fixed long intro/title/cover rules.

- `video2yt-upload`: saves `publication.json`, reuses the uploaded ID on retry, and reports unfinished thumbnail/playlist work. Interrupted unknown uploads require verified recovery with `--adopt-video-id`, or `--retry-uncertain` only after checking Studio.
- `video2yt-cleanup`: metadata-only drafts never qualify; completed receipts are ordered by upload time. Archives small scripts, thumbnails, metadata and experiments under `assets/publications/<video_id>/` before deleting media.
- `video2yt-topic`: ranks relative views/hour within streamer baselines, exposes unverified evidence/confidence/version, writes a full audit JSON, and preserves existing reports on total fetch failure.
- `video2yt-cta`: places a contextual subscription message over gameplay at an explicit time, preserving duration and audio.
- `video2yt-analytics import|collect|report`: stores dated measurements outside caches; optional API collection uses separate read-only authorization. Daily API date buckets and exact publication-relative checkpoints are distinguished.

The tooling prepares experiments and measures results; Studio A/B tests, end screens and actual audience response remain separate verification steps.

### 封面与背景画风

默认使用**日式动漫素描**：铅笔线稿、轻排线与纸纹，搭配日式小清新彩铅配色（薄荷绿、雾蓝、蜜桃粉、浅杏黄、奶油白），保留清晰可见的颜色。图像生成、封面和动态片头统一 `--style anime-sketch`；参考素材与用法见 [画风规范](docs/visual-style.md)。

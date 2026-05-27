# video2yt

Download a Bilibili video and burn its danmaku (bullet comments) into a YouTube-ready MP4. Supports preview clips, time-range cuts, playback speed, codec selection, and Bilibili-accurate danmaku sizing.

## Requirements

- Python 3.10+
- [uv](https://docs.astral.sh/uv/)
- `ffmpeg` and `ffprobe` in PATH, built with libass (macOS: `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg`)
- Chrome browser installed (for cookie-based login to access 1080p content)

## Install

```bash
uv sync
```

### Optional: subtitle generation

Stage 3 (`video2yt-subtitle`) shells out to the external `speech2srt` CLI (Volcengine 火山 Seed-ASR + codex cleanup) since 2026-05-27. Per the speech2srt-integration plan in `docs/superpowers/plans/2026-05-27-speech2srt-integration.md`:

- **Install once**: `cd ~/code/speech2srt && uv tool install . --force`
- **API key**: `VOLCENGINE_API_KEY` either exported or in `.env` at the cwd (get it from 火山引擎控制台 → 语音技术 → 豆包录音文件识别模型2.0)
- **Codex CLI**: `brew install codex && codex login` — used both by Stage 3 cleanup and by the Step 4 intro forced-alignment SRT
- **whisperx (Python dep)**: still in `pyproject.toml`, but ONLY used by `video2yt-transcribe` (intro alignment). NOT used by Stage 3 anymore.
- **Per-project context file**: `output/<project>/subtitle_context.txt` (≤ 2 KB UTF-8) describing the streamer, 流派, key cards, 口頭禪, known ASR errors. Pass via `--subtitle-context-file` on `video2yt`. See CLAUDE.md "Subtitle / speech2srt" for full operating details.
- **Skip Stage 3** entirely with `--no-subtitle` for streamers whose source already has burnt-in subs (e.g. 郭楓荷).

The old `rapidocr-onnxruntime` / `--enable-ocr` flow was removed before the speech2srt cutover.

## Quick start

```bash
uv run video2yt "https://www.bilibili.com/video/BVxxxxxxxxxx/"
```

The tool fetches metadata, downloads the video and raw danmaku XML, converts the danmaku to ASS in-process via `biliass`, and burns the result into an MP4 under `./output/<uploader>：<title>/`.

## Usage

```bash
uv run video2yt <url> [options]
```

| Flag | Default | Description |
|---|---|---|
| `url` (positional) | — | Bilibili video URL (must contain a `BV...` id) |
| `-o, --output-dir` | `./output` | Where the final MP4 goes (under a per-video subfolder) |
| `-t, --temp-dir` | `./temp` | Intermediate files. Raw downloads (video + XML) are always kept here for caching; derived ASS files are removed on success unless `--keep-temp` is set. |
| `-q, --quality` | `1080` | Max video quality, one of `{480, 720, 1080}` |
| `-b, --browser` | `chrome` | Browser to read cookies from |
| `--codec` | `h264` | Video codec preference, one of `{h264, h265, auto}`. `h264` is most compatible / preferred by YouTube; `h265` produces smaller files; `auto` lets yt-dlp pick. |
| `--font-face` | `Hiragino Sans GB` | ASS font family. The default is preinstalled on macOS and visible to libass via fontconfig. |
| `--font-size` | `auto` | Pixel size for a standard (nominal=25) danmaku. Default `auto` uses Bilibili's native formula `video_height * 25 / 540` (≈ `height / 21.6`). |
| `--preview-seconds` | none | If set, cap the burned output to the first N seconds (`ffmpeg -t N`). Useful for fast style/codec iteration. |
| `--cut START~END` | none | Remove a time range from the output. Repeatable. See [Time format for `--cut`](#time-format-for---cut). |
| `--speed FLOAT` | `1.0` | Playback speed multiplier for the output. Range `[0.5, 2.0]`. Common values: `1.1`, `1.25`, `1.5`, `2.0`. Applies to video, audio (pitch preserved via ffmpeg `atempo`), and danmaku together. |
| `--keep-temp` | off | Also keep derived ASS files after success. Raw downloads (video + danmaku XML) are ALWAYS kept regardless, to enable caching. |

## Output layout

For each run video2yt creates a per-video subfolder named `<uploader[:4]>：<title>` (using the fullwidth colon U+FF1A) under both `--output-dir` and `--temp-dir`. The title is sanitized for filesystem safety and truncated to 60 characters.

```
output/
└── 哈哈：某个搞笑视频的标题/
    └── BV1xxxxxxxxx_with_danmaku.mp4
```

If the uploader is missing the subfolder is just `<title>`; if both are missing it falls back to the BV id.

## Output filenames

The output MP4 is named `<bv_id>_with_danmaku[_<suffix>].mp4`, where the suffix encodes which non-default options were used. This is a backward-compatible addition: a plain run with no modifiers still produces `<bv_id>_with_danmaku.mp4`, matching pre-feature behavior.

Suffix parts (in fixed order):

- `_cut` if any `--cut` ranges were provided
- `_<speed>x` if `--speed != 1.0` (e.g. `_1.5x`, `_1.25x`, `_2x`)
- `_preview` if `--preview-seconds` was provided

Because the order is fixed, a given parameter combination always produces the same filename — so different combinations coexist on disk and re-running the same settings overwrites the previous output deterministically.

| `--cut` | `--speed` | `--preview-seconds` | filename |
|---|---|---|---|
| no  | 1.0  | no  | `BV_with_danmaku.mp4` |
| no  | 1.5  | no  | `BV_with_danmaku_1.5x.mp4` |
| yes | 1.0  | no  | `BV_with_danmaku_cut.mp4` |
| yes | 1.5  | no  | `BV_with_danmaku_cut_1.5x.mp4` |
| no  | 1.25 | yes | `BV_with_danmaku_1.25x_preview.mp4` |
| yes | 1.0  | yes | `BV_with_danmaku_cut_preview.mp4` |
| yes | 1.5  | yes | `BV_with_danmaku_cut_1.5x_preview.mp4` |

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

To force a fresh download, delete the cached files manually:

```bash
rm -rf temp/<title_subfolder>/
```

Only delete the specific subfolder you want to re-fetch; wiping `temp/` wholesale throws away the cache for every other video too.

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

### Outputs

- `<output_dir>/<title>.mp4` — final merged video, with chapter markers embedded in its metadata
- `<output_dir>/<title>_chapters.txt` — YouTube-format chapter markers (paste into video description)
- `<output_dir>/<title>_ffmeta.txt` — the ffmetadata file embedded into the MP4 (kept for inspection)

### Behavior

- **Strict input validation**: all segments must be 1920x1080 30fps h264 with an audio stream AND ≥10 seconds long, and there must be at least 3 segments. The duration / segment-count rules mirror YouTube's chapter requirements — anything else and YouTube discards the chapter list. Fail with a list of violations.
- **Per-segment audio normalization**: each segment's audio goes through `loudnorm=I=-14:TP=-1:LRA=11` (YouTube reference loudness) before concatenation.
- **Chapters**: each segment becomes one chapter. The officially-supported way to get chapters onto YouTube is via the video description, so `<title>_chapters.txt` is written in YouTube's text format (first chapter at `00:00`) — paste it into the description as a single ascending block. The same chapters are also embedded into the output MP4 (`-map_metadata`/`-map_chapters`) as a best-effort extra; this isn't officially documented as supported by YouTube, so don't treat it as a fallback for a missing/broken description block.

## Replace background music / reduce Content ID risk

`video2yt-music-swap` isolates streamer commentary with Demucs, discards the non-vocal mix, gates low-level non-speech residual bleed from the vocals stem, then mixes in royalty-free music.

```bash
uv run video2yt-music-swap path/to/BVxxx_with_danmaku.mp4 --seed 1
```

Useful A/B options:

```bash
# Disable the post-Demucs vocal gate for comparison
uv run video2yt-music-swap path/to/input.mp4 --no-vocal-gate -o no_gate.mp4

# More aggressive bleed suppression; may cut quiet speech
uv run video2yt-music-swap path/to/input.mp4 --vocal-gate-threshold 0.025 -o stronger_gate.mp4

# Softer release, less choppy but leaves more tails
uv run video2yt-music-swap path/to/input.mp4 --vocal-gate-release-ms 400 -o softer_gate.mp4
```

Testing a short sample before a full run:

```bash
SRC='path/to/BVxxx_with_danmaku.mp4'
SAMPLE='/tmp/video2yt_music_swap_probe_60s.mp4'
ffmpeg -hide_banner -y -ss 00:05:00 -t 60 -i "$SRC" -map 0:v:0 -map 0:a:0 -c copy "$SAMPLE"
uv run video2yt-music-swap "$SAMPLE" --no-vocal-gate --music-volume 0.0 -o /tmp/no_gate.mp4
uv run video2yt-music-swap "$SAMPLE" --music-volume 0.0 -o /tmp/gated.mp4

for f in /tmp/no_gate.mp4 /tmp/gated.mp4; do
  echo "--- $f"
  ffmpeg -hide_banner -nostats -i "$f" -af volumedetect -vn -f null - 2>&1 | grep -E 'mean_volume|max_volume'
done
```

Whole-file `volumedetect mean_volume` is only a coarse sanity check because loud speech can dominate the average. For better validation, compare per-second RMS: the gated output should have much lower median / low-percentile RMS than the no-gate output while keeping speech-heavy seconds in the same rough range. Always listen to a short A/B clip too: if speech sounds choppy, lower `--vocal-gate-threshold` or increase `--vocal-gate-release-ms`.

Trade-off: the gate mostly helps when the streamer is not speaking. If copyrighted music leaks under active speech, no energy gate can remove it perfectly without damaging the voice. For high-risk clips, compare a 60-second sample before processing the full video.


## Development

```bash
uv run pytest    # currently 230 tests; everything mocked at the subprocess boundary
```

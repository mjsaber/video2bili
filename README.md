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

## Development

```bash
uv run pytest    # currently 147 tests; everything mocked at the subprocess boundary
```

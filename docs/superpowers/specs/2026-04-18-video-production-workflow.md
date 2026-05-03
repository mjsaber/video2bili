# YouTube Video Production Workflow

**Date**: 2026-04-18
**Status**: Validated end-to-end on `back2back` project (S13 炉石战棋 教程)
**Target audience**: Future Claude agents and the user, when producing similar topical YouTube videos from Bilibili source material.

## 1. Goal

Take a topical brief (e.g. "S13 最強輪椅 背靠背流派 教程") and produce a publish-ready YouTube video with:

- A short (~30s) original spoken intro
- One or more burnt-in Bilibili source segments (with danmaku) as the body
- A concatenated final MP4 with progress bar + chapter markers + loudness normalization
- A YouTube thumbnail
- Localized title / description / tags
- Uploaded to YouTube via API with all metadata pre-filled

The pipeline is implemented as a sequence of 9 steps, each backed by an existing CLI command (`video2yt-*`) or a one-off script in `scripts/`.

## 2. Per-project folder convention

**Every artifact for a project MUST live under `output/<project>/`.** Use a short, lowercase, ASCII project name (e.g. `back2back`).

Pass `-o output/<project>/` to every `video2yt`, `video2yt-compose`, and `video2yt-merge` invocation. CLAUDE.md documents this convention in the "Project folder convention" section.

Final layout for `back2back/`:

```
output/back2back/
├── intro_script.txt              # Step 1 source
├── intro_script_prompt.txt       # (optional, if generated)
├── intro_image_prompt.txt        # Step 3 source
├── thumbnail_bg_prompt.txt       # Bonus step source
├── intro.mp3                     # Step 2 output
├── intro.srt                     # Step 4 output
├── intro_bg.png                  # Step 3 output (1920x1080, fitted)
├── intro_bg_raw.png              # Step 3 raw (1024x1024 from Gemini)
├── intro.mp4                     # Step 5 output (intro video)
├── thumbnail_bg.png              # Bonus step bg
├── thumbnail.png                 # Bonus step composed thumbnail (1280x720)
├── <uploader>：<title>/          # Step 6 burnt segment 1
│   └── BV...._with_danmaku_*.mp4
├── <uploader>：<title>/          # Step 6 burnt segment 2
│   └── BV...._with_danmaku_*.mp4
├── back2back_final.mp4           # Step 7 merged final video
├── back2back_final_chapters.txt  # Step 7 YouTube chapters
├── back2back_final_progress_bar.png
├── youtube_metadata.txt          # Step 8 human-readable
├── youtube_metadata.json         # Step 8 machine-readable (for Step 9)
└── (uploaded video URL)          # Step 9 stdout
```

## 3. External dependencies and credentials

| Component | Where | Setup |
|---|---|---|
| `ffmpeg`, `ffprobe` | system PATH | `brew tap homebrew-ffmpeg/ffmpeg && brew install homebrew-ffmpeg/ffmpeg/ffmpeg` (must include libass) |
| Volcengine BigTTS | API key | Volcano Ark console → API Key 管理 → create. Stored as `VOLCENGINE_API_KEY` in `.env`. Only the new (single-key) auth style works; legacy v1 endpoints need separate AppID. |
| Google Gemini (nanobanana) | API key | Google AI Studio → API key. Image-generation model requires a paid/billed key (free tier limit = 0). Stored as `GEMINI_API_KEY` in `.env`. |
| YouTube Data API v3 | OAuth client | Google Cloud Console → enable YouTube Data API v3 → create OAuth client (desktop app). Save JSON as `client_secret.json` (gitignored). First run opens browser for consent (test users must be allow-listed during testing mode). Token cached in `youtube_token.json` (gitignored). |
| Hearthstone Battlegrounds logo | `assets/hsbg_logo.png` | One-time download from Fandom wiki (RGBA, 4098x2146). |

`.env` and all secrets live in repo root, gitignored via `.gitignore` (`.env`, `client_secret*.json`, `youtube_token.json`).

## 4. The 9-step pipeline

### Step 1 — Write a 30-second script

**Input**: brief outline (sentence or two), target length (~30s).
**Output**: `output/<project>/intro_script.txt` (UTF-8 plain text, ~110 chars for 30s at 1.0x speed).

Hand-write or LLM-draft the script. Length rule of thumb: **3.7 chars/sec at speech_rate=0** (1.0x). For a 30s intro, aim for 100–120 Chinese chars.

### Step 2 — TTS via Volcengine BigTTS

**Input**: `intro_script.txt`, voice ID, speech rate.
**Output**: `output/<project>/intro.mp3`.
**Script**: `scripts/tts_quick.py`.
**API**: HTTP Chunked unidirectional (`POST https://openspeech.bytedance.com/api/v3/tts/unidirectional`).

```bash
uv run python scripts/tts_quick.py \
  --text-file output/<project>/intro_script.txt \
  --output    output/<project>/intro.mp3 \
  --speech-rate 0
```

Auth: `X-Api-Key: $VOLCENGINE_API_KEY` + `X-Api-Resource-Id: seed-tts-2.0`.
Default voice: `zh_female_vv_uranus_bigtts`.
Speech rate range: `[-50, 100]`; `0` = 1.0x, `100` = 2.0x, `-50` = 0.5x.

### Step 3 — Background image via Gemini (nanobanana)

**Input**: detailed art-direction prompt, target size.
**Output**: `output/<project>/intro_bg.png` (1920x1080, center-cropped).
**Script**: `scripts/image_quick.py`.

```bash
uv run python scripts/image_quick.py \
  --prompt-file output/<project>/intro_image_prompt.txt \
  --output      output/<project>/intro_bg.png \
  --save-raw    output/<project>/intro_bg_raw.png \
  --target-size 1920x1080 \
  --fit cover
```

Model: `gemini-2.5-flash-image` (default). Output is always 1024x1024; the script center-crops or letterboxes to the target. Prompt should explicitly say "no text, no logos, no watermarks" — Gemini hallucinates text/logos otherwise.

### Step 4 — Forced-alignment SRT

**Input**: `intro.mp3` + `intro_script.txt`.
**Output**: `output/<project>/intro.srt`.
**Tool**: existing `video2yt-transcribe` (whisperx + wav2vec2, CPU).

```bash
uv run video2yt-transcribe \
  --audio  output/<project>/intro.mp3 \
  --script output/<project>/intro_script.txt \
  -o       output/<project>/intro.srt
```

Text comes from the script (preserves correct terms / punctuation); whisperx provides only timestamps. Splits by Chinese sentence punctuation (`。`, `！`, `？`).

### Step 5 — Compose the intro MP4

**Input**: `intro.mp3` + `intro_bg.png` + `intro.srt`.
**Output**: `output/<project>/<title>/<title>.mp4` (1080p, 30fps, h264 + aac).
**Tool**: existing `video2yt-compose`.

```bash
uv run video2yt-compose \
  --audio  output/<project>/intro.mp3 \
  --image  output/<project>/intro_bg.png \
  --srt    output/<project>/intro.srt \
  --title  back2back_intro \
  -o       output/<project>/
```

Then move/rename the result to `output/<project>/intro.mp4` so Step 7 can reference it cleanly.

`compose.render` was patched in this session to probe the audio and pass `-t <audio_duration>` to ffmpeg, working around `-shortest` not stopping the looped image stream when AAC flushes. Output now matches the audio within ~80ms.

### Step 6 — Burn N Bilibili segments

**Input**: Bilibili URL + optional `--cut START~END` ranges + optional `--speed`.
**Output**: `output/<project>/<uploader>：<title>/<bv>_with_danmaku_*.mp4`.
**Tool**: existing `video2yt`.

```bash
uv run video2yt "<bilibili_url>" \
  [--cut 0~6]   \
  [--speed 1.25] \
  -o output/<project>/
```

Each segment becomes a 1920x1080 30fps h264 MP4 with danmaku burnt in. The output filename gets `_cut`, `_<speed>x`, `_preview` suffixes based on flags. The raw download (mp4 + danmaku XML) is preserved under `temp/<uploader>：<title>/` for caching.

### Step 7 — Merge into final video

**Input**: ordered list of `--segment` + `--label` pairs (intro first), plus a working title.
**Output**: `output/<project>/<title>.mp4` + `<title>_chapters.txt` + `<title>_progress_bar.png`.
**Tool**: existing `video2yt-merge`.

```bash
uv run video2yt-merge \
  --segment output/<project>/intro.mp4                            --label "intro" \
  --segment output/<project>/<uploader1>：.../<bv1>_with_danmaku_cut.mp4 --label "教程" \
  --segment output/<project>/<uploader2>：.../<bv2>_with_danmaku_1.25x.mp4 --label "郭楓荷實戰" \
  --title   "<working_title>" \
  -o        output/<project>/<project>_final.mp4
```

All `--segment` inputs MUST be 1920x1080 30fps h264 (strict). Output: concat + per-segment loudnorm to -14 LUFS + Pillow-rendered progress bar overlaid as PNG + ffmpeg `drawbox` highlighting current segment.

### Step 8 — Generate YouTube metadata

**Output**: two files in `output/<project>/`:

- `youtube_metadata.txt` — human-readable; sections separated by `===` headers; contains title, two description variants (繁體 Taiwan + 简体), tags, chapters.
- `youtube_metadata.json` — structured for Step 9. Fields:

```json
{
  "title": "...",
  "description": "...",
  "tags": ["..."],
  "category_id": "20",
  "default_language": "zh-Hant",
  "default_audio_language": "zh-Hant",
  "privacy_status": "public",
  "made_for_kids": false,
  "expected_channel_id": "UC...",
  "video_path": "output/<project>/<project>_final.mp4",
  "thumbnail_path": "output/<project>/thumbnail.png"
}
```

Title format used in this project: `[爐石戰棋]S13 <topic> | <streamer name> 實戰 [彈幕]`. Description should include the chapter list (so YouTube renders chapter markers). For Taiwan audience, primary description is 繁體 with TW grammar; append 简体 below as secondary.

### Bonus — YouTube thumbnail

**Input**: bg image (Step 3 style), logo PNG, title text.
**Output**: `output/<project>/thumbnail.png` (1280x720).
**Script**: `scripts/thumbnail_compose.py`.

Two-stage approach to dodge Gemini's poor CJK / logo rendering:

1. Generate a clean dark-fantasy bg via Gemini (no text, no logos in prompt; reserve quiet zones for logo + text).
2. Pillow composites: real logo top-left + title text in chosen orientation.

```bash
# 1. Background
uv run python scripts/image_quick.py \
  --prompt-file output/<project>/thumbnail_bg_prompt.txt \
  --output      output/<project>/thumbnail_bg.png \
  --save-raw    output/<project>/thumbnail_bg_raw.png \
  --target-size 1280x720 --fit cover

# 2. Composite
uv run python scripts/thumbnail_compose.py \
  --bg          output/<project>/thumbnail_bg.png \
  --logo        assets/hsbg_logo.png \
  --title       "<title>" \
  --orientation vertical-left \
  --font-size   128 \
  --title-anchor-x-ratio 0.35 \
  --output      output/<project>/thumbnail.png
```

`thumbnail_compose.py` supports two orientations: `horizontal-bottom` (title across the bottom) and `vertical-left` (title stacked vertically, ASCII tokens like "S13" stay horizontal). `--title-anchor-x-ratio` controls horizontal placement (0.25 = center of left half; 0.35 nudges right to clear the logo).

### Step 9 — Upload to YouTube

**Input**: `youtube_metadata.json`, `client_secret.json`, cached `youtube_token.json` (or fresh OAuth flow on first run).
**Output**: published video URL printed to stderr.
**Script**: `scripts/youtube_upload.py`.

```bash
# First time: OAuth dry-run to verify channel
uv run python scripts/youtube_upload.py \
  --metadata output/<project>/youtube_metadata.json \
  --dry-run

# Real upload
uv run python scripts/youtube_upload.py \
  --metadata output/<project>/youtube_metadata.json
```

Behavior:

1. OAuth via `InstalledAppFlow.run_local_server(port=0)`. Browser opens for consent on first run; token cached to `youtube_token.json` after.
2. Lists authenticated channels via `channels.list(mine=True)`. **Aborts** if `expected_channel_id` from metadata is not in the list (catches wrong-account auth).
3. Resumable upload via `MediaFileUpload` with 8 MB chunks. Progress logged every ≥5%.
4. Uploads thumbnail via `thumbnails().set()` after video upload completes.
5. Prints watch URL + studio URL.

OAuth gotchas:

- App in "Testing" status only allows allow-listed test users (add at OAuth consent screen → test users).
- Test-mode tokens expire in 7 days; either re-auth or publish the OAuth app to production.
- Brand channels require signing in to that brand account during the OAuth consent flow.

## 5. Scripts added by this workflow

All under `scripts/` (untracked by default — they're project-specific tooling, but useful enough to be reused; promote to `src/video2yt/` if formalizing into proper CLIs).

| File | Purpose | Key deps |
|---|---|---|
| `scripts/tts_quick.py` | Volcengine BigTTS HTTP Chunked client | `requests`, `python-dotenv` |
| `scripts/image_quick.py` | Gemini image-gen + crop/letterbox to target size | `google-genai`, `Pillow`, `python-dotenv` |
| `scripts/thumbnail_compose.py` | Pillow composite: bg + logo + horizontal/vertical title | `Pillow` |
| `scripts/youtube_upload.py` | YouTube Data API v3 OAuth + resumable upload + thumbnail set | `google-api-python-client`, `google-auth-oauthlib`, `google-auth-httplib2` |

`pyproject.toml` got these new deps added during this session:

- `google-genai>=1.73.1`
- `google-api-python-client>=2.194.0`
- `google-auth-oauthlib>=1.3.1`
- `google-auth-httplib2>=0.3.1`
- `python-dotenv>=1.2.2`
- `requests>=2.33.1`

## 6. Tech debt and follow-ups

| Area | Status | Notes |
|---|---|---|
| `compose -shortest` bug | **Fixed** in this session | `compose.render` now probes audio duration and adds `-t <audio_duration>` as an output-side clamp. |
| Promote `scripts/*.py` to CLIs | Pending | User originally chose option (A) — formalize as `video2yt-tts`, `video2yt-image`, `video2yt-thumbnail`, `video2yt-upload` with TDD. Current scripts are working but lack tests and are not installed as console scripts. |
| Image fit aspect ratio | Pending | Gemini outputs 1024x1024; `cover` crop discards ~44% vertically when going to 16:9. Could try prompting "16:9 widescreen" + accept Gemini's best effort, or use a model that respects aspect ratio. |
| Thumbnail font auto-fit | Pending | Vertical-left mode silently overflows if `font_size × tokens × line_spacing > target_h`. Should auto-shrink or warn. |
| OAuth app publishing | Pending (user-side) | While in Testing status, tokens expire in 7 days. To upload reliably long-term, publish the OAuth consent screen (or rotate tokens). |

## 7. Verification — what passed on the back2back project

- `intro.mp3` 21.89s → `intro.mp4` 21.97s (Δ < 0.1s ✓)
- Final `back2back_final.mp4`: 21:55 (1315.5s), 1920x1080 30fps h264 + aac, 847 MB
- Chapters file generated correctly with three entries (00:00 / 00:21 / 03:03)
- 231 pytest tests pass with the compose fix included
- YouTube upload succeeded to channel `UCEgIrCo0pR6DyyrXuSn3wBg`, public, with thumbnail
  - Video ID: `DuglxlhKbzw` — https://www.youtube.com/watch?v=DuglxlhKbzw
  - Total upload time: 8m 24s for 847 MB (~1.7 MB/s effective)

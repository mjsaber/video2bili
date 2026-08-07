# S14 鱼饵野兽 Production and Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把郭枫荷与瓦莉拉的两条 S14 鱼饵野兽实战制作成一支突出新版本卡牌、配有高反差深海鱼饵 Intro 的公开视频。

**Architecture:** 复用仓库既有的 Stage 1–5 缓存管线：先串行下载，再从 speech 与弹幕理解真实内容，核对官方 zhTW 术语后制作动态 Intro，最后烧录两条正片、追加 CTA、合并、生成缩略图与元数据。上传是独立的最终状态变更，必须在最终成片与元数据审核通过后执行，并由上传器自动加入 S14 播放列表。

**Tech Stack:** `video2yt-prefetch`, `video2yt-stems`, `video2yt-subtitle`, `video2yt-tts`, `video2yt-transcribe`, `video2yt-image`, `video2yt-intro`, `video2yt-music-mix`, `video2yt-burn`, `video2yt-merge`, `video2yt-upload`, ffmpeg/ffprobe, HearthstoneJSON zhTW card art.

---

## File map

- Create: `output/fishbait_beast_s14/content_understanding.md` — 两条实战的独立理解与合并叙事角度。
- Create: `output/fishbait_beast_s14/intro_script.txt` — 经术语核对的繁体 Intro 旁白。
- Create: `output/fishbait_beast_s14/terms_zhTW.md` — 官方卡面证据与简繁映射。
- Create: `output/fishbait_beast_s14/subtitle_context.txt` — 正片字幕清洗词表，UTF-8 且不超过 2 KB。
- Create: `output/fishbait_beast_s14/intro_image_prompt.txt` — 高反差深海鱼饵背景 Prompt。
- Create: `output/fishbait_beast_s14/intro_cards.txt` — Intro 中实际出现的新卡卡面与 SRT 匹配词。
- Create: `output/fishbait_beast_s14/intro.{mp3,srt,mp4}` and `intro_bg{,_raw}.png` — 动态 Intro 工件。
- Create: `output/fishbait_beast_s14/guo/` and `output/fishbait_beast_s14/vala/` — 两条烧录正片。
- Create: `output/fishbait_beast_s14/fishbait_beast_s14_final.mp4` — 最终合并视频。
- Create: `output/fishbait_beast_s14/thumbnail.png` and `thumbnail_preview_640.png` — 完整与缩小预览缩略图。
- Create: `output/fishbait_beast_s14/youtube_metadata.json` — YouTube 标题、说明、章节、来源、音乐署名与标签。
- Create: `output/fishbait_beast_s14/subscribe_comment.txt` — 上传后的繁体订阅评论。
- Do not modify: unrelated dirty worktree files and previously shipped project outputs before the cleanup task.

### Task 1: Preflight and initialize the project

- [ ] **Step 1: Verify required tools and credentials without printing secrets**

Run:

```bash
command -v ffmpeg
command -v ffprobe
command -v song-remover
command -v speech2srt
command -v codex
test -s .env
test -s client_secret.json
ffmpeg -hide_banner -filters 2>/dev/null | rg ' subtitles '
```

Expected: every `command -v` returns one path, both secret-file checks exit 0, and ffmpeg lists the `subtitles` filter.

- [ ] **Step 2: Create only the current project directories**

Run:

```bash
mkdir -p output/fishbait_beast_s14/guo output/fishbait_beast_s14/vala
```

Expected: the three directories exist and no unrelated files change.

### Task 2: Download and validate both source videos

- [ ] **Step 1: Prefetch the selected sources serially**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1wdGA61EhL' \
  'https://www.bilibili.com/video/BV1ADMk6mEDv' \
  -o temp/
```

Expected: exit 0; both BVIDs report completed downloads and non-empty danmaku ASS files.

- [ ] **Step 2: Resolve the cached paths and assert one exact match per BVID**

Run:

```bash
rg --files temp | rg '/BV1wdGA61EhL\.mp4$'
rg --files temp | rg '/BV1ADMk6mEDv\.mp4$'
rg --files temp | rg '/BV1wdGA61EhL\.danmaku\.ass$'
rg --files temp | rg '/BV1ADMk6mEDv\.danmaku\.ass$'
```

Expected: each command prints exactly one non-empty path.

- [ ] **Step 3: Verify video dimensions, codecs, duration, and decode health**

Run after assigning the unique paths printed above:

```bash
guo_video=$(rg --files temp | rg '/BV1wdGA61EhL\.mp4$')
vala_video=$(rg --files temp | rg '/BV1ADMk6mEDv\.mp4$')
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate -show_entries format=duration -of json "$guo_video"
ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate -show_entries format=duration -of json "$vala_video"
ffmpeg -v error -i "$guo_video" -f null -
ffmpeg -v error -i "$vala_video" -f null -
```

Expected: both sources are 1920×1080, have video and audio streams, have plausible durations near 18:15 and 9:35, and both full-decode commands exit 0 with no errors.

### Task 3: Extract speech once and validate the real content

- [ ] **Step 1: Generate speech stems for both sources**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1wdGA61EhL\.mp4$')
vala_video=$(rg --files temp | rg '/BV1ADMk6mEDv\.mp4$')
uv run video2yt-stems "$guo_video"
uv run video2yt-stems "$vala_video"
```

Expected: each BVID cache directory contains non-empty `speech.wav`, `music.wav`, `sfx.wav`, and `no_music.wav`; the source metadata sidecar is present.

- [ ] **Step 2: Run raw ASR exactly once per source**

Run:

```bash
set -a
source .env
set +a
guo_video=$(rg --files temp | rg '/BV1wdGA61EhL\.mp4$')
vala_video=$(rg --files temp | rg '/BV1ADMk6mEDv\.mp4$')
uv run video2yt-subtitle "$guo_video" --skip-cleanup
uv run video2yt-subtitle "$vala_video" --skip-cleanup
```

Expected: exit 0 for both; each cache contains `speech.wav.speech2srt.srt`, its JSON cache sidecar, and a raw `speech.cleaned.srt` copy. Do not run ASR a second time later.

- [ ] **Step 3: Check transcript coverage against source duration**

Run:

```bash
for bvid in BV1wdGA61EhL BV1ADMk6mEDv; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  srt_path=$(rg --files "$(dirname "$video_path")/$bvid" | rg 'speech\.wav\.speech2srt\.srt$')
  ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$video_path"
  tail -12 "$srt_path"
done
```

Expected: both transcripts contain blocks through the late game; the final timestamp is consistent with the last spoken section rather than being truncated near the beginning or middle.

- [ ] **Step 4: Cross-check speech with danmaku before drafting**

Read both raw SRT files and extract dialogue lines from both `*.danmaku.ass` files. Record for each video: hero, fishbait enabler, Dark Gift, growth engine, key pivot, final board, and any claimed S14 card name. Reject any title-only assumption not supported by speech, screen state, or danmaku.

### Task 4: Write content understanding and Intro draft

- [ ] **Step 1: Create `content_understanding.md` with fixed evidence sections**

The file must contain:

```markdown
# S14 鱼饵野兽内容理解

## 郭枫荷：BV1wdGA61EhL
- 实际英雄：
- 新版本组件：
- 成长链：
- 关键回合与终局：
- speech / 弹幕证据：

## 瓦莉拉：BV1ADMk6mEDv
- 实际英雄：
- 新版本组件：
- 成长链：
- 关键回合与终局：
- speech / 弹幕证据：

## 合并角度
- 两局共同机制：
- 两局差异：
- Intro 只展示的实战卡牌：
```

Fill every field with concrete findings from Task 3; do not leave empty bullets.

- [ ] **Step 2: Draft `intro_script.txt`**

Requirements: start exactly with `你敢相信？`; Traditional Chinese; approximately 100–120 Chinese characters; declarative tone; use `旅店` and `異變` vocabulary; emphasize S14 Fishbait and only cards that actually appear in the two videos; end by setting up the two-streamer comparison.

- [ ] **Step 3: Run textual acceptance checks**

Run:

```bash
test -s output/fishbait_beast_s14/content_understanding.md
test -s output/fishbait_beast_s14/intro_script.txt
head -c 18 output/fishbait_beast_s14/intro_script.txt
rg -n '酒館|畸變|牌組|套牌|構築|TBD|TODO' output/fishbait_beast_s14/content_understanding.md output/fishbait_beast_s14/intro_script.txt
```

Expected: the intro begins with `你敢相信？`; the final `rg` command produces no matches.

- [ ] **Step 4: Review checkpoint #1**

Present the complete understanding and Intro script together. Stop until the user approves or requests revisions.

### Task 5: Verify official zhTW terminology

- [ ] **Step 1: Resolve every named gameplay term**

For every card, hero, Dark Gift, trinket, or anomaly named in the approved Intro, assign its exact English card name to `card_name`, run `uv run video2yt-research-card --name "$card_name"`, resolve the official card ID, and download the official BGS zhTW art from:

```text
https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/${card_id}.png
```

Assign the resolved HearthstoneJSON identifier to `card_id` and a stable lowercase English filename stem to `card_slug`, then save each verified card as `assets/cards/${card_slug}_zhTW_bgs_512.png`. Record card ID, enUS name, official zhTW name, and source URL in `output/fishbait_beast_s14/terms_zhTW.md`.

- [ ] **Step 2: Correct the Intro before TTS**

Replace every Simplified Chinese, colloquial, or guessed term with the name visible on official zhTW card art. Do not synthesize speech until this check is complete.

- [ ] **Step 3: Seed subtitle cleanup context**

Create `output/fishbait_beast_s14/subtitle_context.txt` containing the two streamer names, verified terms, common spoken aliases, and specific ASR-error-to-official-name mappings.

Run:

```bash
test -s output/fishbait_beast_s14/terms_zhTW.md
test -s output/fishbait_beast_s14/subtitle_context.txt
test "$(wc -c < output/fishbait_beast_s14/subtitle_context.txt)" -le 2048
rg -n 'TBD|TODO|待定' output/fishbait_beast_s14/terms_zhTW.md output/fishbait_beast_s14/subtitle_context.txt
```

Expected: all checks pass and the final search has no matches.

### Task 6: Generate the upgraded background and dynamic Intro

- [ ] **Step 1: Create the high-impact background Prompt**

Write this approved base Prompt to `output/fishbait_beast_s14/intro_image_prompt.txt`, then replace only imagery details supported by the verified cards if needed:

```text
A cinematic high-impact Hearthstone-inspired battlegrounds tavern transformed by bioluminescent deep-sea magic, a single molten-gold enchanted fishbait glowing intensely at the lower center as the clear focal point, saturated teal and cyan currents, coral silhouettes, wet polished wood, suspended bubbles and magical particles, dramatic volumetric lighting, strong cool-versus-warm contrast, rich depth, premium fantasy game key art, locally darker and less detailed across the entire right side, lower-left subtitle area, and top title strip, no characters, no creatures, no cards, no text, no numbers, no logos, no interface, 16:9 composition.
```

- [ ] **Step 2: Generate TTS and aligned subtitles**

Run:

```bash
set -a
source .env
set +a
uv run video2yt-tts --text-file output/fishbait_beast_s14/intro_script.txt -o output/fishbait_beast_s14/intro.mp3
uv run video2yt-transcribe \
  --audio output/fishbait_beast_s14/intro.mp3 \
  --script output/fishbait_beast_s14/intro_script.txt \
  --max-block-chars 22 \
  -o output/fishbait_beast_s14/intro.srt
```

Expected: both outputs are non-empty; the final SRT timestamp reaches the spoken audio tail within the established silence tolerance.

- [ ] **Step 3: Generate and inspect the background**

Run:

```bash
uv run video2yt-image --backend codex \
  --prompt-file output/fishbait_beast_s14/intro_image_prompt.txt \
  -o output/fishbait_beast_s14/intro_bg.png \
  --save-raw output/fishbait_beast_s14/intro_bg_raw.png
ffprobe -v error -show_entries stream=width,height -of csv=p=0 output/fishbait_beast_s14/intro_bg.png
```

Expected: fitted output is 1920×1080. Inspect the image at full size and 640px width: one molten-gold bait remains the dominant focal point, with no figure, creature, text, logo, card, or competing bright object; right side, lower-left, and top strip remain readable safe zones.

- [ ] **Step 4: Build the card timeline and Intro**

Write one `assets/cards/*.png | 官方繁中卡名` line per card named in the approved SRT to `intro_cards.txt`, preserving first-mention order. Then run:

```bash
uv run video2yt-intro \
  --audio output/fishbait_beast_s14/intro.mp3 \
  --bg output/fishbait_beast_s14/intro_bg.png \
  --srt output/fishbait_beast_s14/intro.srt \
  --cards output/fishbait_beast_s14/intro_cards.txt \
  -o output/fishbait_beast_s14/intro.mp4
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate -show_entries format=duration -of json output/fishbait_beast_s14/intro.mp4
ffmpeg -v error -i output/fishbait_beast_s14/intro.mp4 -f null -
```

Expected: 1920×1080, 30 fps, H.264/AAC, full decode succeeds, every card appears after its spoken name, and subtitles/mascot remain legible over the upgraded background.

- [ ] **Step 5: Review checkpoint #2**

Present `intro.mp4` plus the 640px background preview. Stop until the user approves or requests a prompt/image revision.

### Task 7: Prepare cleaned Traditional Chinese subtitles and burn both battles

- [ ] **Step 1: Inspect each source for existing hard subtitles**

Extract beginning, middle, and late representative frames from each source with ffmpeg and visually inspect them. If a source already has bottom hard subtitles, record `--no-subtitle` for that source; otherwise continue with timestamp-preserving cleanup.

- [ ] **Step 2: Clean raw SRT text without changing timing**

For every source that needs subtitles, convert only dialogue text to Traditional Chinese and apply `subtitle_context.txt` mappings. Preserve every block number and timestamp byte-for-byte. Compare raw and cleaned block counts and timestamp lists; fail if either differs. Convert each cleaned SRT to its corresponding `BV1wdGA61EhL/speech.cleaned.ass` or `BV1ADMk6mEDv/speech.cleaned.ass` using `compose.srt_to_ass` at 1920×1080, font size 50, bottom position, outline 4, shadow 2, margin 80.

- [ ] **Step 3: Generate music beds**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1wdGA61EhL\.mp4$')
vala_video=$(rg --files temp | rg '/BV1ADMk6mEDv\.mp4$')
uv run video2yt-music-mix "$guo_video"
uv run video2yt-music-mix "$vala_video"
```

Expected: each source directory contains a non-empty music bed, metadata sidecar, and attribution file; bed duration matches source duration within 0.5 seconds.

- [ ] **Step 4: Burn both body segments**

Run with `--no-subtitle` only for a source proven in Step 1 to contain adequate hard subtitles:

```bash
guo_video=$(rg --files temp | rg '/BV1wdGA61EhL\.mp4$')
vala_video=$(rg --files temp | rg '/BV1ADMk6mEDv\.mp4$')
uv run video2yt-burn "$(dirname "$guo_video")" --bv BV1wdGA61EhL -o output/fishbait_beast_s14/guo/BV1wdGA61EhL_final.mp4
uv run video2yt-burn "$(dirname "$vala_video")" --bv BV1ADMk6mEDv -o output/fishbait_beast_s14/vala/BV1ADMk6mEDv_final.mp4
```

Expected: both outputs are 1920×1080, 30 fps, H.264/AAC 48 kHz; full decode succeeds; speech is clear, music is ducked at the established 0.12 bed level, and subtitles/danmaku do not collide.

### Task 8: Append CTA and merge the final video

- [ ] **Step 1: Append CTA to the first battle only**

Run:

```bash
scripts/append_cta.sh output/fishbait_beast_s14/guo/BV1wdGA61EhL_final.mp4
```

Expected: `BV1wdGA61EhL_final_cta.mp4` exists, is longer than the original by the CTA duration, and full decode succeeds.

- [ ] **Step 2: Merge with exactly one chapter sequence**

Run:

```bash
uv run video2yt-merge \
  --segment output/fishbait_beast_s14/intro.mp4 --label '開場：S14 魚餌野獸' \
  --segment output/fishbait_beast_s14/guo/BV1wdGA61EhL_final_cta.mp4 --label '郭楓荷：魚餌野獸版本答案' \
  --segment output/fishbait_beast_s14/vala/BV1ADMk6mEDv_final.mp4 --label '瓦莉拉：不敗魚餌野獸' \
  --title 'S14 魚餌野獸完整教學' \
  -o output/fishbait_beast_s14/fishbait_beast_s14_final.mp4
```

Expected: final MP4 and chapter/ffmetadata files exist; all three chapters are at least 10 seconds and strictly ascending from 00:00.

- [ ] **Step 3: Verify final media**

Run:

```bash
ffprobe -v error -show_entries stream=codec_name,width,height,r_frame_rate,sample_rate -show_entries format=duration -of json output/fishbait_beast_s14/fishbait_beast_s14_final.mp4
ffmpeg -v error -i output/fishbait_beast_s14/fishbait_beast_s14_final.mp4 -f null -
sed -n '1,20p' output/fishbait_beast_s14/fishbait_beast_s14_final_chapters.txt
```

Expected: 1920×1080, 30 fps, H.264/AAC 48 kHz, clean full decode, and one valid chapter block.

### Task 9: Build thumbnail and YouTube metadata

- [ ] **Step 1: Render the channel-standard thumbnail**

Choose the most visually legible verified S14 fishbait/core card from `intro_cards.txt`, assign its actual path to `thumbnail_card`, and run:

```bash
uv run python scripts/thumbnail_polish.py \
  --bg output/fishbait_beast_s14/intro_bg.png \
  --card "$thumbnail_card" \
  --output output/fishbait_beast_s14/thumbnail.png \
  --primary '魚餌野獸' \
  --secondary '版本答案'
ffmpeg -y -i output/fishbait_beast_s14/thumbnail.png \
  -vf 'scale=640:-2' output/fishbait_beast_s14/thumbnail_preview_640.png
ffprobe -v error -show_entries stream=width,height -of csv=p=0 output/fishbait_beast_s14/thumbnail.png
stat -f '%z' output/fishbait_beast_s14/thumbnail.png
```

Expected: dimensions are 1280×720 and file size is below 2,000,000 bytes; the 640px preview retains the molten-gold focal contrast, readable title, unobscured card name, and clear mascot silhouette.

- [ ] **Step 2: Create `youtube_metadata.json`**

Required title pattern:

```text
「爐石戰記：英雄戰場」S14 新版本魚餌野獸完整教學 | 郭楓荷 × 瓦莉拉實戰 [彈幕]
```

The Traditional Chinese description must include exactly one chapter block, both Bilibili source URLs, all generated CC BY music credits, and first hashtags `#英雄戰場教學 #英雄戰場 #爐石戰記`. Set category 20, language zh-Hant, public visibility, and expected channel ID `UCEgIrCo0pR6DyyrXuSn3wBg`.

- [ ] **Step 3: Create the subscribe comment**

Write a short Traditional Chinese recap of the S14 Fishbait mechanic followed by a natural prompt to like, subscribe, enable notifications, and comment the next desired comp.

### Task 10: Final review and authorized upload

- [ ] **Step 1: Present the final review package**

Provide the final MP4, thumbnail preview, exact title, complete description, chapters, tags, source URLs, and music credits. Stop for explicit upload authorization.

- [ ] **Step 2: Run uploader dry-run**

Run the repository uploader in dry-run mode using `youtube_metadata.json`. Verify resolved channel ID, title, privacy, thumbnail, description, and playlist classification before any upload.

- [ ] **Step 3: Upload after authorization**

Run the real uploader only after the user authorizes it. Expected: public processing succeeds and the returned watch URL is reachable.

- [ ] **Step 4: Verify playlist isolation and post the comment**

Confirm the upload is present in the S14 playlist and absent from the S13 playlist. Run `scripts/post_comment.py` with `subscribe_comment.txt` and confirm success.

### Task 11: Post-upload cleanup

- [ ] **Step 1: Preview cleanup targets**

Run:

```bash
uv run video2yt-cleanup --project fishbait_beast_s14
```

Expected: dry-run targets only the current project's temp caches and the previous shipped project's output; it preserves `output/fishbait_beast_s14/`.

- [ ] **Step 2: Execute cleanup after target review**

Run:

```bash
uv run video2yt-cleanup --project fishbait_beast_s14 --yes
```

Expected: reported targets are removed, current project output remains as the one-period buffer, and the public YouTube URL remains available.

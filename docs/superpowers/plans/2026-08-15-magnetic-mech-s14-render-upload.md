# S14 Magnetic Mech Render and Upload Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将已审核的 S14 磁力机械 Intro 与两段实战制作成完整繁体教学视频，并公开上传到正确频道及 S14 播放列表。

**Architecture:** 复用已经验证的两条 1080p 源、stems 与 raw ASR，不进行第二次转录。先完成 Intro TTS 与卡牌同步视觉，再机械转换并修正正文字幕、生成 CC0 音乐床、烧录两段实战，随后追加 CTA、合并章节、生成频道标准封面与 metadata，最后公开上传、自动归类播放列表、发布订阅评论并做 API 验证。

**Tech Stack:** `video2yt-tts`, `video2yt-transcribe`, built-in ImageGen, `video2yt-intro`, OpenCC/s2twp, `compose.srt_to_ass`, `video2yt-music-mix`, `video2yt-burn`, ffmpeg/ffprobe, `append_cta.sh`, `video2yt-merge`, Pillow thumbnail compositor, YouTube Data API v3.

---

## File map

- Modify: `output/magnetic_mech_s14/WORKFLOW_NOTES.md` — record authorization, stage outcomes, upload ID, playlist and comment verification.
- Create: `output/magnetic_mech_s14/intro_image_prompt.txt` — final mechanical key-art prompt.
- Create: `output/magnetic_mech_s14/intro_cards.txt` — SRT-matched official card order.
- Create: `output/magnetic_mech_s14/intro.mp3`, `intro.srt`, `intro_bg_raw.png`, `intro_bg.png`, `intro.mp4` — dynamic Intro artifacts.
- Modify: both `temp/.../<BVID>/speech.cleaned.srt` and `speech.cleaned.ass` — deterministic Traditional cleanup with identical block IDs/timestamps.
- Create: `output/magnetic_mech_s14/guo/BV1xcu26hEAG_final.mp4` and `output/magnetic_mech_s14/vala/BV1m8u969Ea5_final.mp4` — body segments.
- Create: `output/magnetic_mech_s14/guo/BV1xcu26hEAG_final_cta.mp4` — battle one plus channel CTA.
- Create: `output/magnetic_mech_s14/magnetic_mech_s14_final.mp4` plus chapters and ffmetadata.
- Create: `output/magnetic_mech_s14/thumbnail.png`, `youtube_metadata.json`, and `subscribe_comment.txt`.

### Task 1: Record authorization and produce the dynamic Intro

- [ ] **Step 1: Record the approval boundary**

Update `WORKFLOW_NOTES.md` so Review #1 and explicit public upload authorization are checked. Record that later visual choices are autonomous internal gates.

- [ ] **Step 2: Generate and validate TTS**

Run:

```bash
set -a; source .env; set +a
uv run video2yt-tts --text-file output/magnetic_mech_s14/intro_script.txt \
  -o output/magnetic_mech_s14/intro.mp3
uv run video2yt-transcribe --audio output/magnetic_mech_s14/intro.mp3 \
  --script output/magnetic_mech_s14/intro_script.txt --max-block-chars 22 \
  -o output/magnetic_mech_s14/intro.srt
```

Expected: decodable 24 kHz mono MP3; SRT begins at speech start, ends at audio tail, concatenated text equals the approved script, and duration is 45–50 seconds. If the generated voice exceeds 50 seconds, shorten only redundant wording while preserving the three verified mechanisms and urgent ending, then regenerate once.

- [ ] **Step 3: Generate a single high-impact background with built-in ImageGen**

Write a concise `stylized-concept` prompt for a 16:9 fantasy-mechanical foundry: central magnetic reactor pulling segmented metal rings into one visible closed energy circuit; electric blue versus molten orange; strong depth and thumbnail-scale contrast; right side, lower-left, and top strip locally dark; no people, mascot, cards, text, letters, numbers, logo, watermark, fake UI, duplicate reactors, or loose clutter.

Generate with the built-in image tool, copy the selected project-bound output to `output/magnetic_mech_s14/intro_bg_raw.png`, resize/crop non-destructively to 1920×1080 as `intro_bg.png`, inspect both full resolution and 640×360 preview, and iterate once only if the focal loop or safe zones fail.

- [ ] **Step 4: Compose and review the Intro**

Create:

```text
spark_snapper_zhTW_bgs_512.png | 火花截斷者
polarizing_beatboxer_zhTW_bgs_512.png | 電磁節奏口技手
shark_cannon_zhTW_bgs_512.png | 鯊魚砲
```

Then run:

```bash
uv run video2yt-intro \
  --audio output/magnetic_mech_s14/intro.mp3 \
  --bg output/magnetic_mech_s14/intro_bg.png \
  --srt output/magnetic_mech_s14/intro.srt \
  --cards output/magnetic_mech_s14/intro_cards.txt \
  -o output/magnetic_mech_s14/intro.mp4
```

Expected: 1920×1080 H.264/yuv420p 30 fps + AAC; exact audio-length match; all three official zhTW cards appear in first-mention order; subtitles remain at most two lines and do not overlap card or mascot; first and final 0.2 seconds are intact.

### Task 2: Produce Traditional body subtitles without rerunning ASR

- [ ] **Step 1: Mechanically convert both raw canonical SRTs**

Use each canonical `speech.wav.speech2srt.srt` as the immutable source. Convert text lines with OpenCC `s2twp`, then apply only verified replacements from `subtitle_context.txt`, including `BBOX` → `電磁節奏口技手`, `火花破壞機` → `火花截斷者`, `鯊魚火炮` → `鯊魚砲`, `酒館法術` → `旅店法術`, and streamer names.

- [ ] **Step 2: Preserve structural invariants**

Run a parser comparison proving both cleaned files retain the exact ordered block-number list and timestamp list of their raw counterparts, contain no empty dialogue, and are idempotent under `s2twp`.

- [ ] **Step 3: Regenerate ASS deterministically**

Call `video2yt.compose.srt_to_ass` with 1920×1080, `Hiragino Sans GB`, 50 px, bottom placement, outline 4, shadow 2, and vertical margin 80. Write each `<BVID>/speech.cleaned.ass` and verify dialogue count equals SRT block count.

### Task 3: Build music beds and burn both body segments

- [ ] **Step 1: Generate cached CC BY music beds**

Run once per exact MP4:

```bash
uv run video2yt-music-mix 'temp/炉石郭枫：新版本，补丁后的机械！一张磁力1000身材！/BV1xcu26hEAG.mp4'
uv run video2yt-music-mix 'temp/炉石传说：【炉石瓦莉拉】酒馆战棋新版本 机械这么玩就对了/BV1m8u969Ea5.mp4'
```

Expected: non-empty music bed and credits for each source, with bed duration within 0.5 seconds of source. Preserve the code-locked 0.12 bed-volume baseline.

- [ ] **Step 2: Burn both segments**

Run:

```bash
uv run video2yt-burn 'temp/炉石郭枫：新版本，补丁后的机械！一张磁力1000身材！' \
  --bv BV1xcu26hEAG -o output/magnetic_mech_s14/guo/BV1xcu26hEAG_final.mp4
uv run video2yt-burn 'temp/炉石传说：【炉石瓦莉拉】酒馆战棋新版本 机械这么玩就对了' \
  --bv BV1m8u969Ea5 -o output/magnetic_mech_s14/vala/BV1m8u969Ea5_final.mp4
```

Expected: both outputs satisfy merge strict mode: 1920×1080, 30 fps, H.264/yuv420p, AAC 48 kHz, with danmaku and readable Traditional subtitles.

- [ ] **Step 3: Fully decode and visually sample**

Decode video and audio of both outputs with `ffmpeg -v error -xerror`. Inspect start, middle, mechanism timestamps, final boards, and last second; ensure no black frames, early truncation, subtitle overlap, or missing audio.

### Task 4: Append CTA and merge the final video

- [ ] **Step 1: Append CTA to the first battle only**

Run:

```bash
scripts/append_cta.sh output/magnetic_mech_s14/guo/BV1xcu26hEAG_final.mp4
```

Expected: `BV1xcu26hEAG_final_cta.mp4` has a clean re-encoded join, full original duration plus CTA, and no decreasing DTS.

- [ ] **Step 2: Merge three chapters**

Run:

```bash
uv run video2yt-merge \
  --segment output/magnetic_mech_s14/intro.mp4 --label '開場：新版磁力機械' \
  --segment output/magnetic_mech_s14/guo/BV1xcu26hEAG_final_cta.mp4 --label '郭楓荷：火花合體破千' \
  --segment output/magnetic_mech_s14/vala/BV1m8u969Ea5_final.mp4 --label '瓦莉拉：海盜經濟轉機械' \
  --title 'S14 磁力機械完整教學' \
  -o output/magnetic_mech_s14/magnetic_mech_s14_final.mp4
```

Expected: exactly three ascending chapters, first at 00:00, each at least ten seconds; final media fully decodes and duration equals input sum within one second.

### Task 5: Create thumbnail and metadata

- [ ] **Step 1: Build the channel-standard thumbnail**

Use the approved design's recommended cover direction autonomously: primary `磁力機械`, secondary `單卡破千`. Run:

```bash
uv run python scripts/thumbnail_polish.py \
  --bg output/magnetic_mech_s14/intro_bg.png \
  --card assets/cards/polarizing_beatboxer_zhTW_bgs_512.png \
  --card2 assets/cards/spark_snapper_zhTW_bgs_512.png \
  --output output/magnetic_mech_s14/thumbnail.png \
  --primary '磁力機械' --secondary '單卡破千'
```

Expected: 1280×720, under 2 MB, two title rows remain readable at 640×360, official card names are visible enough to identify, and the mascot does not cover the main mechanism card.

- [ ] **Step 2: Write publication metadata**

Create `youtube_metadata.json` with title `「爐石戰記：英雄戰場」新賽季磁力機械完整教學 | 郭楓荷 × 瓦莉拉 實戰 [彈幕]`, season 14, public privacy, correct channel ID, exact final/thumbnail paths, a single chapter block, both Bilibili URLs, every unique music credit from both source credit files, and required first-three hashtags `#英雄戰場教學 #英雄戰場 #爐石戰記`.

Create a fresh Traditional `subscribe_comment.txt` that recaps 火花截斷者＋金色電磁節奏口技手, asks viewers which S14 comp they want next, and calls for 按讚、訂閱、開啟小鈴鐺.

- [ ] **Step 3: Validate the publication package**

Verify JSON validity, title ≤100 Unicode characters, exactly one chapter block, exactly two unique Bilibili URLs, exact music-credit set equality, public privacy, season 14, correct channel ID, thumbnail <2 MB, and playlist classification includes S14 but excludes S13.

### Task 6: Public upload, comment, verification, and cleanup

- [ ] **Step 1: Authenticate and verify the channel**

Run:

```bash
uv run video2yt-upload --metadata output/magnetic_mech_s14/youtube_metadata.json --dry-run
```

Expected: authenticated channel `UCEgIrCo0pR6DyyrXuSn3wBg`. If token refresh requires consent, use the in-app browser automation path and only surface a user blocker after exhausting it.

- [ ] **Step 2: Upload publicly and capture the video ID**

Run the real upload once. Verify the returned video ID, watch URL, public privacy, successful processing, thumbnail, and automatic playlist membership. Confirm it is in the S14 comp playlist and not in the S13 playlist.

- [ ] **Step 3: Post and verify the subscribe comment**

Run `scripts/post_comment.py` with the uploaded video ID, the new comment file, and the expected channel ID. Record the returned comment ID.

- [ ] **Step 4: Record publication and reclaim disk safely**

Update `WORKFLOW_NOTES.md` with YouTube URL, video ID, privacy/processing status, playlists, and comment ID. Run `video2yt-cleanup --project magnetic_mech_s14` as a dry run, inspect exact targets, then run with `--yes`; keep the current output as the one-period buffer and never hand-delete caches.

- [ ] **Step 5: Final verification**

Re-query YouTube for public status and processing success; confirm thumbnail, playlists, and comment. Run `git diff --check` on project-authored text and report the public watch URL plus saved project artifacts.

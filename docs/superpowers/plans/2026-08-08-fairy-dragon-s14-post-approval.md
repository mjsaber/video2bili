# S14 仙女龍流 Post-Approval Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將已確認的 S14 仙女龍 Intro 與兩段實戰製作成完整影片，使用指定封面文案，通過媒體與內容終審後公開上傳 YouTube、加入 S14 播放清單並發布訂閱留言。

**Architecture:** 從已驗證的下載、stems、raw ASR 與官方術語產物續跑。先完成官方卡面、TTS、ImageGen 背景與動態 Intro，再以不重跑 ASR 的方式製作繁中字幕，分別完成音樂、燒錄、CTA、合併、封面和 metadata；只有全部媒體驗收通過後才執行公開上傳。

**Tech Stack:** `video2yt-tts`, `video2yt-intro`, ImageGen, HearthstoneJSON BGS art, OpenCC/s2twp, ffmpeg/ffprobe, `video2yt-music-mix`, `video2yt-burn`, `video2yt-merge`, Pillow thumbnail compositor, YouTube Data API.

---

## File map

- Create: `output/fairy_dragon_s14/assets/cards/*.png` — 本期實際 Intro 卡面。
- Create: `output/fairy_dragon_s14/intro.{mp3,srt,mp4}` — 已核對文案的 TTS、時間軸與動態 Intro。
- Create: `output/fairy_dragon_s14/intro_bg*.png`, `intro_image_prompt.txt`, `intro_cards.txt` — ImageGen 視覺與卡面順序。
- Create: `temp/<source>/<bvid>/speech.cleaned.{srt,ass}` — 不重跑 ASR 的繁中字幕。
- Create: `output/fairy_dragon_s14/{guo,night}/*_final.mp4` — 兩段正片。
- Create: `output/fairy_dragon_s14/fairy_dragon_s14_final.mp4` and chapter metadata — 完整成片。
- Create: `output/fairy_dragon_s14/thumbnail.png`, `youtube_metadata.json`, `subscribe_comment.txt` — 發布產物。
- Modify: `output/fairy_dragon_s14/WORKFLOW_NOTES.md` — 記錄 Intro 已確認、公開上傳已授權與每一階段狀態。
- Modify after successful upload only: `assets/topic/done_topics.txt` — 新增已完成題材與 YouTube ID，避免重複選題。

### Task 1: Record approval and preflight the remaining pipeline

- [ ] **Step 1: Record the exact authorization boundary**

Mark Intro approval and public upload authorization checked in `WORKFLOW_NOTES.md`; record the exact thumbnail lines `新赛季新发明！` and `龙族翻身！`. Do not mark final review or upload complete yet.

- [ ] **Step 2: Verify tools, credentials, assets and capacity**

Run:

```bash
command -v ffmpeg && command -v ffprobe && command -v speech2srt
test -s client_secret.json && test -s youtube_token.json
test -s assets/cta/subscribe_cta.mp4
test -s assets/avatar/avatar.png
df -h .
```

Expected: tools and files exist; current free space is recorded before rendering.

### Task 2: Build the approved Intro

- [ ] **Step 1: Download only the official cards named in the Intro**

Download the nine verified zhTW BGS card faces in first-mention order: `BG24_004`, `BG29_810`, `BG29_813`, `BG36_MagicItem_208`, `BG36_760`, `BG28_518`, `BG35_883`, `BG32_822`, `BG33_825`. Verify every PNG is non-empty, decodes, and visibly matches `terms_zhTW.md`.

- [ ] **Step 2: Generate and validate TTS**

Run the repository TTS command on `intro_script.txt`, producing `intro.mp3` and `intro.srt`. Verify full MP3 decode, SRT text equality, start `0.000`, tail gap below 0.1 seconds, and duration 45–50 seconds. If outside the bound, shorten only redundant wording while preserving the approved S13→S14 comparison and every mechanism link.

- [ ] **Step 3: Generate the high-impact background with ImageGen**

Generate a text-free 16:9 cinematic Dalaran dragon scene: luminous fairy dragon attacking through a violet arcane prison, strong cyan/magenta contrast, large central action silhouette, clean lower caption area, clean side space for official card overlays, no Hearthstone logos, no UI, no watermark, no extra creatures, and no generated text. Save the raw and selected 1920×1080 assets inside the project and inspect the full-resolution output.

- [ ] **Step 4: Render and visually review dynamic Intro**

Write `intro_cards.txt` in first-mention order and run `video2yt-intro`. Verify 1920×1080 H.264/AAC, duration alignment, full decode, all nine official cards readable at their first mentions, one-line captions, no mascot/card overlap, and no truncated final CTA.

### Task 3: Produce deterministic Traditional subtitles without another ASR call

- [ ] **Step 1: Convert raw SRT text while preserving structure**

For each BVID, copy the canonical raw SRT structure, convert only dialogue text to Traditional Chinese, and apply exact mappings from `subtitle_context.txt`. Preserve every block number and timestamp byte-for-byte; do not invoke `speech2srt` or `--force-asr`.

- [ ] **Step 2: Regenerate ASS and verify invariants**

Use `video2yt.compose.srt_to_ass` with 1920×1080, `Hiragino Sans GB`, size 50, bottom alignment, outline 4, shadow 2, margin 80. Assert raw/clean block counts, IDs and timestamp lists are identical, every dialogue is non-empty, s2twp conversion is idempotent, and the official terms are present where spoken.

### Task 4: Build and validate both battle segments

- [ ] **Step 1: Create CC0 music beds**

Run `video2yt-music-mix` once per cached source. Verify non-empty bed and credits files, 48 kHz audio, full decode, and source-length match within one second.

- [ ] **Step 2: Burn both sources**

Run `video2yt-burn` for 郭楓荷 into `output/fairy_dragon_s14/guo/` and 夜吹 into `output/fairy_dragon_s14/night/`. Verify each output is 1920×1080, 30 fps, H.264/AAC 48 kHz, has exactly video+audio, fully decodes, matches source duration, and visibly contains separated danmaku and Traditional speech subtitles.

### Task 5: Append CTA and merge the final program

- [ ] **Step 1: Append CTA to battle one only**

Run `scripts/append_cta.sh` on the 郭楓荷 final segment. Verify the output duration equals battle one plus the CTA within one second and that the join has no black flash or backward-timestamp truncation.

- [ ] **Step 2: Merge with three chapters**

Merge `intro.mp4`, 郭楓荷 CTA segment and 夜吹 segment with labels `開場：S14 仙女龍翻身`, `郭楓荷：新卡循環仙女龍`, and `夜吹：海盜賞金轉龍`. Verify the MP4 and generated chapter files, exactly three ascending chapters, the first at `00:00`, and total duration matching all inputs.

### Task 6: Create the approved thumbnail and metadata

- [ ] **Step 1: Render thumbnail with exact user copy**

Use `scripts/thumbnail_polish.py` with the selected visual, 躍翼 official card, and exact text `新赛季新发明！` / `龙族翻身！`. Keep the text in Simplified exactly as supplied. Verify 1280×720, below 2 MB, and legibility at 640×360.

- [ ] **Step 2: Author metadata and comment**

Create a Traditional Chinese title using the channel format `「爐石戰記：英雄戰場」新賽季…`, a description with exactly one chapter block, both Bilibili URLs, all unique music credits, first-three hashtag `#英雄戰場教學`, public privacy, season 14, the expected channel ID, and the final media/thumbnail paths. Create a concise Traditional subscribe comment with like/subscribe/bell CTA.

### Task 7: Final review gate

- [ ] **Step 1: Run complete media validation**

Freshly probe and fully decode the final MP4; inspect Intro card timings, both transitions, CTA join, late-game boards, final frame, subtitle placement and audio continuity. Verify title length, metadata JSON, chapter equality, source URLs, music-credit set equality, thumbnail size and preview legibility.

- [ ] **Step 2: Verify playlist routing before upload**

Call `playlists.classify(title, 14)` and require the S14 route while rejecting every S13 route. Stop if this assertion fails.

### Task 8: Public upload, playlist check and comment

- [ ] **Step 1: Dry-run authentication and channel guard**

Run `video2yt-upload --metadata ... --dry-run`. If OAuth is expired, complete the browser consent flow, then rerun until the expected channel check passes.

- [ ] **Step 2: Upload publicly**

Run the real uploader once. Capture the YouTube video ID and URL, verify `privacyStatus=public`, thumbnail applied, and S14 playlist membership. Do not retry a completed resumable upload merely because a later playlist step reports an error; inspect the video ID first.

- [ ] **Step 3: Publish the comment and record completion**

Run `scripts/post_comment.py` with the uploaded ID and `subscribe_comment.txt`. Record the YouTube URL and playlist result in `WORKFLOW_NOTES.md`, append the completed topic to `assets/topic/done_topics.txt`, and run fresh final existence/metadata checks. Do not delete project outputs or caches during this task.

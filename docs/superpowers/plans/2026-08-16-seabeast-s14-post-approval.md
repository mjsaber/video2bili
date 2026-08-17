# S14 新賽季海獸流 Post-Approval Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 將已批准的 S14「海獸流」單素材方案製作成可發布的繁中 YouTube 成片包，並在任何公開上傳之前停下等待使用者終審。

**Architecture:** 僅使用郭楓荷 `BV1jnuZ67Epi` 的既有 1080p 來源、stems 與唯一 canonical raw ASR，不下載或混入已排除素材，也不重跑 ASR。先製作 TTS、ImageGen 背景與官方卡面動態 Intro；再保持原時間軸製作繁中字幕、音樂床與單段正片，追加 CTA 後合併兩章；最後產生能清楚表達「海盜供血、野獸觸發亡語」的封面與 metadata，完成全量驗證后停止，不執行公開上傳。

**Tech Stack:** `video2yt-tts`, `video2yt-transcribe`, built-in ImageGen, `video2yt-intro`, OpenCC/s2twp, `video2yt.compose.srt_to_ass`, `video2yt-music-mix`, `video2yt-burn`, ffmpeg/ffprobe, `scripts/append_cta.sh`, `video2yt-merge`, Pillow thumbnail compositor.

---

## File map

- Modify: `output/seabeast_s14/WORKFLOW_NOTES.md` — 记录用户批准与明确的未授权上传边界。
- Create: `output/seabeast_s14/intro_image_prompt.txt`, `intro_cards.txt`, `intro.mp3`, `intro.srt`, `intro_bg_raw.png`, `intro_bg.png`, `intro.mp4` — 动态开场产物。
- Create: `temp/炉石郭枫：新发明：思路已成，海兽流！/BV1jnuZ67Epi/speech.cleaned.srt` and `.ass` — 保持 canonical raw ASR 结构的繁中字幕。
- Create: `output/seabeast_s14/guo/BV1jnuZ67Epi_final.mp4` and `_cta.mp4` — 单素材正片与 CTA 版本。
- Create: `output/seabeast_s14/seabeast_s14_final.mp4` plus chapters/ffmetadata — 两章完整成片。
- Create: `output/seabeast_s14/thumbnail.png`, `youtube_metadata.json`, `subscribe_comment.txt` — 待终审发布包。

### Task 1: Record approval and preflight the production boundary

- [ ] **Step 1: Record exact approval**

Check only `User approved Intro and packaging` in `WORKFLOW_NOTES.md`. Preserve `Public upload authorization: absent`; record that upload, playlists, comment posting, cleanup and `done_topics.txt` remain out of scope.

- [ ] **Step 2: Verify inputs and capacity**

Verify ffmpeg/ffprobe, CTA, official card PNGs, source MP4, stems, canonical raw SRT/JSON and available disk. Assert the excluded BVID `BV1sYgA6CEms` is absent from all planned public artifacts.

### Task 2: Build and validate the approved dynamic Intro

- [ ] **Step 1: Generate TTS and aligned subtitles**

Run:

```bash
set -a; source .env; set +a
uv run video2yt-tts --text-file output/seabeast_s14/intro_script.txt \
  -o output/seabeast_s14/intro.mp3
uv run video2yt-transcribe --audio output/seabeast_s14/intro.mp3 \
  --script output/seabeast_s14/intro_script.txt --max-block-chars 22 \
  -o output/seabeast_s14/intro.srt
```

Verify a full audio decode, exact concatenated script text, subtitle tail alignment, and a 45–50 second duration. If the duration misses the range, change only redundant phrasing without altering any approved mechanism claim.

- [ ] **Step 2: Generate a text-free Pirate-to-Beast key visual**

Use built-in ImageGen for a 16:9 cinematic fantasy-tavern scene: a gigantic glowing Pirate on the left donates a visible river of green-gold life energy into a predatory bird/Beast trigger chain on the right, with a spectral deathrattle pulse and a secondary necromancer silhouette suggesting Titus. Preserve clean top, lower subtitle and card-overlay zones. Generate no text, letters, numbers, logo, watermark, fake UI or fake cards. Save raw output as `intro_bg_raw.png`, crop/resize to 1920×1080 as `intro_bg.png`, and visually inspect full size plus 640×360.

- [ ] **Step 3: Compose the official-card Intro**

Create `intro_cards.txt` in first-mention order using official zhTW assets for `積極的逃脫者`, `帶鎖箱`, `『大師掠奪者』鉤牙`, `防禦獻祭`, `死亡陸行鷹`, and `提圖斯‧瑞文戴爾`. Run:

```bash
uv run video2yt-intro \
  --audio output/seabeast_s14/intro.mp3 \
  --bg output/seabeast_s14/intro_bg.png \
  --srt output/seabeast_s14/intro.srt \
  --cards output/seabeast_s14/intro_cards.txt \
  -o output/seabeast_s14/intro.mp4
```

Verify 1920×1080 H.264/yuv420p at 30 fps with AAC, full decode, audio-duration match, first-mention card order, readable subtitles, and no overlap/truncation.

### Task 3: Produce deterministic Traditional body subtitles without another ASR

- [ ] **Step 1: Convert only dialogue text**

Treat `speech.wav.speech2srt.srt` as immutable. Convert dialogue text through OpenCC `s2twp`, apply only verified mappings in `subtitle_context.txt`, and write `speech.cleaned.srt`. Do not call `speech2srt`, `video2yt-subtitle`, `--force-asr`, or any other transcription path.

- [ ] **Step 2: Prove structural invariants and generate ASS**

Assert exact equality of ordered block IDs and timestamp strings between raw and cleaned SRT, no empty dialogue, and idempotent `s2twp`. Generate `speech.cleaned.ass` with `video2yt.compose.srt_to_ass` at 1920×1080, `Hiragino Sans GB`, 50 px, bottom placement, outline 4, shadow 2 and margin 80; verify ASS dialogue count equals SRT block count.

### Task 4: Build the single body segment

- [ ] **Step 1: Generate the cached CC0 music bed**

Run once:

```bash
uv run video2yt-music-mix \
  'temp/炉石郭枫：新发明：思路已成，海兽流！/BV1jnuZ67Epi.mp4'
```

Verify the music bed and credits are non-empty, fully decodable, and duration-matched within one second.

- [ ] **Step 2: Burn and normalize the source**

Run:

```bash
uv run video2yt-burn 'temp/炉石郭枫：新发明：思路已成，海兽流！' \
  --bv BV1jnuZ67Epi \
  -o output/seabeast_s14/guo/BV1jnuZ67Epi_final.mp4
```

The re-encoded result must have monotonic timestamps and satisfy merge strict mode: 1920×1080, 30 fps, H.264/yuv420p, AAC 48 kHz, exactly one video and one audio stream. Fully decode video/audio and visually inspect start, subtitle collisions, the mechanism reveal around 10:20, transfer around 19:26, and the final second. Do not claim a win not visible in the source.

### Task 5: Append CTA and merge exactly two chapters

- [ ] **Step 1: Append CTA to the only battle**

Run:

```bash
scripts/append_cta.sh \
  output/seabeast_s14/guo/BV1jnuZ67Epi_final.mp4
```

Verify output duration equals body plus CTA within 0.6 seconds and contains no backward timestamps or black join frame.

- [ ] **Step 2: Merge Intro and the single CTA body**

Run:

```bash
uv run video2yt-merge \
  --segment output/seabeast_s14/intro.mp4 --label '開場：新賽季海獸流' \
  --segment output/seabeast_s14/guo/BV1jnuZ67Epi_final_cta.mp4 --label '郭楓荷：兩萬血海盜傳血' \
  --title 'S14 新賽季海獸流' \
  -o output/seabeast_s14/seabeast_s14_final.mp4
```

Verify exactly two ascending chapters, first at 00:00, source-sum duration within one second, full decode, audio continuity and final frame.

### Task 6: Create the approved thumbnail and metadata

- [ ] **Step 1: Render a relationship-first thumbnail**

Use the selected Pirate-to-Beast background and official Escapee plus Deathstrider card art. Retain the approved message hierarchy: `新賽季`, `海獸流！`, `兩萬血海盜`, `野獸觸發亡語`. If the locked compositor cannot express all four lines without weakening the relationship, produce the final 1280×720 raster with the same brand assets and typography while preserving the exact approved copy. Verify under 2 MB and legibility at 640×360.

- [ ] **Step 2: Author the pre-publication package**

Create `youtube_metadata.json` with exact title `新賽季海獸流！兩萬血海盜瘋狂傳血，野獸反覆觸發亡語`, season 14, expected channel ID, final/thumbnail paths, exactly one chapter block, only the included Bilibili URL, every unique generated music credit, and first-three hashtags `#英雄戰場教學 #英雄戰場 #爐石戰記`. Create a concise Traditional `subscribe_comment.txt`, but do not post it. Metadata may describe intended publication settings, but its existence is not upload authorization.

### Task 7: Final validation and mandatory stop

- [ ] **Step 1: Validate media and claims**

Freshly probe and fully decode the final MP4. Inspect Intro, chapter transition, CTA join, mechanism frames, subtitles, final frame and thumbnail. Validate JSON, title length, two-chapter equality, exact source URL count, credit-set equality, correct S14 classification and no S13 classification. Search all publication artifacts for the excluded BVID and fail if found.

- [ ] **Step 2: Stop before external mutation**

Update `WORKFLOW_NOTES.md` with completed local artifacts and verification results. Do not call `video2yt-upload`, YouTube APIs, browser upload controls, playlist mutation, comment posting, cleanup, or modify `assets/topic/done_topics.txt`. Return the local final video, thumbnail and metadata for explicit user review and separate upload authorization.

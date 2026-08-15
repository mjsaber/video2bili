# S14 瑪卓薩斯匕首 Evidence and Intro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Current execution boundary — 2026-08-14:** The user approved topic option 1. Execute inline through source understanding, official terminology, and the completed Intro script, then stop for review. Do not synthesize TTS, generate imagery, burn body videos, upload, comment, or clean caches before that review.

**Goal:** 把郭楓荷與 Kimmy 的兩段 S14 實戰整理成一支以瑪卓薩斯匕首為核心的雙路線教學，先交付可核驗的機制證據與 Intro 文案。

**Architecture:** 串行下載兩段 Bilibili 素材，為每個 BVID 建立可復用的 Stage 1–3 cache，且 raw ASR 只執行一次。之後聯合讀取原始語音、彈幕、關鍵幀與最新 HearthstoneJSON zhTW 資料，先建立「飾品靜態規則／贈禮結果／兩局實際作用」三層證據，再撰寫 45–50 秒 Intro。

**Tech Stack:** `video2yt-prefetch`, `video2yt-stems`, `video2yt-subtitle --skip-cleanup`, ffmpeg/ffprobe, HearthstoneJSON latest zhTW/enUS data and BGS art, Markdown evidence records.

---

## File map

- Create: `output/maldraxxus_dagger_s14/WORKFLOW_NOTES.md` — sources, review boundary, and stage checklist.
- Create: `output/maldraxxus_dagger_s14/content_understanding.md` — timestamped analysis of both runs and the combined mechanism.
- Create: `output/maldraxxus_dagger_s14/terms_zhTW.md` — official IDs, zhTW names, current rules, and card-art URLs.
- Create: `output/maldraxxus_dagger_s14/subtitle_context.txt` — aliases and official terms for later subtitle cleanup, at most 2 KB.
- Create: `output/maldraxxus_dagger_s14/intro_script.txt` — Traditional Chinese Intro awaiting user review.
- Create: `output/maldraxxus_dagger_s14/evidence/guo/` and `output/maldraxxus_dagger_s14/evidence/kimmy/` — targeted frames only.
- Do not create yet: Intro TTS/SRT/background/MP4, body renders, thumbnail, metadata, or upload artifacts.
- Do not modify: unrelated dirty worktree files, shipped project outputs, `assets/topic/done_topics.txt`, or existing card assets.

### Task 1: Preflight and initialize the review-bounded project

- [ ] **Step 1: Verify the approved source records**

Run:

```bash
rg -n 'BV1S4gN6xEz9|BV1w2ud6QEaA|瑪卓薩斯匕首' \
  docs/superpowers/specs/2026-08-14-maldraxxus-dagger-s14-production-design.md \
  output/topics/2026-08-14.md
```

Expected: both BVIDs occur in the report and design, and the design carries the corrected official zhTW trinket name.

- [ ] **Step 2: Verify tools and secrets without printing secret contents**

Run:

```bash
command -v ffmpeg
command -v ffprobe
uv run which yt-dlp
command -v song-remover
command -v speech2srt
test -s .env
test -s ~/.modal.toml
ffmpeg -hide_banner -filters 2>/dev/null | rg ' subtitles '
```

Expected: all executables resolve, both protected files exist, and ffmpeg exposes the libass subtitles filter.

- [ ] **Step 3: Initialize only this project**

Create the project and evidence directories. Create `WORKFLOW_NOTES.md` containing both full Bilibili URLs, the official topic name, checkboxes for download/raw ASR/evidence/official terms/Intro/user approval, and the explicit statement `Public upload authorization: absent for this project`.

Expected: only `output/maldraxxus_dagger_s14/` is initialized; no cache or older output is removed.

### Task 2: Download and validate both sources serially

- [ ] **Step 1: Prefetch in narrative order**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1S4gN6xEz9' \
  'https://www.bilibili.com/video/BV1w2ud6QEaA' \
  -o temp/
```

Expected: exit 0; each source yields one MP4, one XML danmaku file, and one converted ASS file under `temp/`.

- [ ] **Step 2: Resolve exact paths and assert non-empty artifacts**

Run for each BVID:

```bash
for bvid in BV1S4gN6xEz9 BV1w2ud6QEaA; do
  test "$(rg --files temp | rg -c "/${bvid}\\.mp4$")" -eq 1
  test "$(rg --files temp | rg -c "/${bvid}\\.danmaku\\.xml$")" -eq 1
  test "$(rg --files temp | rg -c "/${bvid}\\.danmaku\\.ass$")" -eq 1
  rg --files temp | rg "/${bvid}\\.(mp4|danmaku\\.(xml|ass))$"
done
```

Expected: exactly three non-empty artifact paths resolve per BVID.

- [ ] **Step 3: Verify streams and full decode**

Run:

```bash
for bvid in BV1S4gN6xEz9 BV1w2ud6QEaA; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  ffprobe -v error -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate \
    -show_entries format=duration -of json "$video_path"
  ffmpeg -v error -xerror -i "$video_path" -map 0:v:0 -f null -
  ffmpeg -v error -xerror -i "$video_path" -map 0:a:0 -f null -
done
```

Expected: both sources are 1920×1080 with audio, durations are close to 21:19 and 18:06, and all four full decodes exit 0 without errors.

### Task 3: Generate stems and one raw ASR per source

- [ ] **Step 1: Separate stems for each exact MP4**

Run:

```bash
for bvid in BV1S4gN6xEz9 BV1w2ud6QEaA; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  uv run video2yt-stems "$video_path"
done
```

Expected: each BVID directory contains `speech.wav`, `music.wav`, `sfx.wav`, `no_music.wav`, and `.stems_source_meta.json`; stem durations match the source within one second.

- [ ] **Step 2: Reuse valid canonical ASR or run it exactly once**

For each BVID, inspect `speech.wav.speech2srt.{srt,json}`. If both exist and the JSON hash matches the current `speech.wav`, reuse them. Otherwise run:

```bash
set -a
source .env
set +a
uv run video2yt-subtitle "$video_path" --skip-cleanup
```

Expected: no `--force-asr`; each source ends with one non-empty canonical SRT/JSON pair, `cleanup_enabled=false`, and transcript coverage near the video tail.

### Task 4: Build source-grounded mechanism evidence

- [ ] **Step 1: Read all raw text evidence**

Read both canonical raw SRTs and both danmaku XML/ASS files. Search Simplified and Traditional aliases for 匕首、瑪卓薩斯、黑暗贈禮、火車王、李洛伊、獅鷲獸、奮戰、致命劇毒、重生、聖盾術、免疫、融合、瑞文 and every visible late-game value.

Expected: every retained assertion records BVID, timestamp, and whether it comes from speech, danmaku, or visible UI.

- [ ] **Step 2: Create overview and targeted frames**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1S4gN6xEz9\.mp4$')
kimmy_video=$(rg --files temp | rg '/BV1w2ud6QEaA\.mp4$')
ffmpeg -y -i "$guo_video" -vf 'fps=1/40,scale=480:-2,tile=6x6' -frames:v 1 output/maldraxxus_dagger_s14/evidence/guo/contact.png
ffmpeg -y -i "$kimmy_video" -vf 'fps=1/40,scale=480:-2,tile=6x5' -frames:v 1 output/maldraxxus_dagger_s14/evidence/kimmy/contact.png
```

Then extract full-resolution frames at every trinket choice, discovered copy, Dark Gift rule, core-minion hover, trigger, pivot, and final-board timestamp.

Expected: targeted images make all Intro-eligible rules and results readable; overview sheets cover both complete games.

- [ ] **Step 3: Resolve current official zhTW records**

Refresh HearthstoneJSON latest zhTW/enUS data. Match actual on-screen art to exact IDs, then verify the official BGS image URL:

```text
https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/${card_id}.png
```

At minimum verify `BG36_MagicItem_370 瑪卓薩斯匕首`, `BG23_318 『魯莽者』李洛伊`, and `BG36_204 獵頭獅鷲獸`. Resolve every named Dark Gift separately; do not infer a Gift from the trinket's static text.

Expected: each Intro card has an actual video timestamp, official ID, exact zhTW name/current text, and readable official art.

- [ ] **Step 4: Write the fixed evidence documents**

Create `content_understanding.md` with these sections:

```markdown
# S14 瑪卓薩斯匕首雙路線內容理解
## 郭楓荷：BV1S4gN6xEz9
## Kimmy：BV1w2ud6QEaA
## 實際卡牌與機制表
## 瑪卓薩斯匕首的完整處理順序
## 李洛伊終局路線
## 獵頭獅鷲獸資源路線
## 兩局可見結果
## Intro 可展示卡牌
## 排除的未證實說法
```

Create `terms_zhTW.md` with Card ID, enUS name, official zhTW name, exact rule, local/stable card-art filename, official URL, and source timestamp. Create `subtitle_context.txt` with both streamer names, official terms, and concrete ASR alias mappings.

- [ ] **Step 5: Run evidence acceptance checks**

Run:

```bash
test -s output/maldraxxus_dagger_s14/content_understanding.md
test -s output/maldraxxus_dagger_s14/terms_zhTW.md
test -s output/maldraxxus_dagger_s14/subtitle_context.txt
test "$(wc -c < output/maldraxxus_dagger_s14/subtitle_context.txt)" -le 2048
rg -n 'BV1S4gN6xEz9|BV1w2ud6QEaA|完整處理順序|排除的未證實說法' output/maldraxxus_dagger_s14/content_understanding.md
! rg -n 'T[BB]D|T[OO]DO|待定|必定提供|直接賦予場上' output/maldraxxus_dagger_s14/terms_zhTW.md
```

Expected: all sections and sources exist, context is within 2 KB, and the term record contains no placeholders or false trinket claims.

### Task 5: Draft the Intro and stop for user confirmation

- [ ] **Step 1: Write `intro_script.txt` from verified evidence only**

Requirements:

- Start exactly with `你敢相信？`.
- Use official Traditional Chinese Battlegrounds terminology.
- Target 45–50 seconds, initially about 220–245 Chinese characters.
- State that the trinket discovers an unbuffed copy with a Dark Gift and repeats at the start of each turn; never claim it buffs the board copy directly.
- Explain the two actual routes in their verified trigger order, including every new card or Dark Gift material to the result.
- Use objective, direct, highly assertive wording; avoid anthropomorphism and metaphors such as `咬一口`, `起飛`, or `引擎`.
- Do not call a random Gift guaranteed, and do not turn one successful game into an unsupported universal T0 claim.
- End with an evidence-calibrated season-opening strength verdict and immediate learning CTA.

- [ ] **Step 2: Run textual acceptance checks**

Run:

```bash
test -s output/maldraxxus_dagger_s14/intro_script.txt
python -c "from pathlib import Path; s=Path('output/maldraxxus_dagger_s14/intro_script.txt').read_text().strip(); assert s.startswith('你敢相信？'); assert 210 <= len(s) <= 255; print(len(s))"
rg -n '新版本|瑪卓薩斯匕首|黑暗贈禮|每個回合|趕緊學' output/maldraxxus_dagger_s14/intro_script.txt
! rg -n '酒館|畸變|牌組|套牌|構築|咬一口|起飛|引擎|T[BB]D|T[OO]DO|待定' output/maldraxxus_dagger_s14/intro_script.txt
```

Expected: opening, length, new-version framing, exact trinket mechanism, urgent ending, and forbidden-language checks pass.

- [ ] **Step 3: Present the review package and stop**

Mark download, raw ASR, evidence, official terms, and Intro draft complete in `WORKFLOW_NOTES.md`, leaving user Intro approval unchecked. Present both source URLs, the exact mechanism chain, the complementary role of each game, every numerical claim used, the complete Intro script, and its predicted duration.

Stop here. Do not generate TTS, imagery, Intro video, body renders, metadata, comments, cleanup, or upload until the user approves or revises the Intro.

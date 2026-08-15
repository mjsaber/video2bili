# S14 Magnetic Mech Evidence and Intro Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将郭楓荷与瓦莉拉的两段 S14 磁力机械实战整理成一支机制清楚、证据可靠的繁体中文教学，并先交付完整内容理解与 45–50 秒 Intro 审核稿。

**Architecture:** 两条 Bilibili 素材各自保留独立 Stage 1–3 cache，raw ASR 每个 BVID 最多执行一次。联合读取原始语音、弹幕、关键帧与最新 HearthstoneJSON zhTW 数据，分别建立“高倍率磁力互贴”和“海盗经济转机械”证据，再合并成版本变化明确的 Intro。

**Tech Stack:** `video2yt-prefetch`, `video2yt-stems`, `video2yt-subtitle --skip-cleanup`, ffmpeg/ffprobe, HearthstoneJSON latest zhTW/enUS data and official BGS art, Markdown evidence records.

---

## File map

- Create: `output/magnetic_mech_s14/WORKFLOW_NOTES.md` — sources, authorization boundary, stage checklist, validation results.
- Create: `output/magnetic_mech_s14/content_understanding.md` — both source analyses, timestamped card/mechanism table, exact numeric claims, exclusions.
- Create: `output/magnetic_mech_s14/terms_zhTW.md` — official IDs, zhTW names/current rules, official art URLs, source timestamps.
- Create: `output/magnetic_mech_s14/subtitle_context.txt` — official terms and concrete ASR aliases, at most 2 KB.
- Create: `output/magnetic_mech_s14/intro_script.txt` — Traditional Chinese Intro awaiting user review.
- Create: `output/magnetic_mech_s14/evidence/guo/` and `output/magnetic_mech_s14/evidence/vala/` — overview and targeted evidence frames.
- Do not create before review: Intro TTS/SRT/background/MP4, body renders, thumbnail, metadata, upload artifacts.
- Do not modify: unrelated dirty worktree files, older shipped projects, `assets/topic/done_topics.txt`, or prior card assets.

### Task 1: Preflight and initialize the review-bounded project

- [ ] **Step 1: Verify approved source records**

Run:

```bash
rg -n 'BV1xcu26hEAG|BV1m8u969Ea5|磁力機械' \
  docs/superpowers/specs/2026-08-14-magnetic-mech-s14-production-design.md \
  output/topics/2026-08-14.md
```

Expected: both BVIDs occur in the report and design; the design identifies the topic as S14 magnetic Mechs.

- [ ] **Step 2: Verify tools, credentials, and disk without exposing secret contents**

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
df -h .
```

Expected: all tools resolve, both protected files exist, libass subtitles is available, and free space is recorded.

- [ ] **Step 3: Initialize only the magnetic-Mech project**

Create `output/magnetic_mech_s14/{evidence/guo,evidence/vala}` and `WORKFLOW_NOTES.md`. The notes must contain both full Bilibili URLs, the topic name, stage checkboxes, `Public upload authorization: absent for this project`, and the first review boundary.

Expected: no older output or cache is removed.

### Task 2: Download and fully validate both sources

- [ ] **Step 1: Prefetch in narrative order**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1xcu26hEAG' \
  'https://www.bilibili.com/video/BV1m8u969Ea5' \
  -o temp/ -b 'chrome:Default'
```

Expected: exit 0; each BVID yields one non-empty MP4, XML danmaku, and ASS danmaku file under `temp/`.

- [ ] **Step 2: Resolve exact artifacts**

Run:

```bash
for bvid in BV1xcu26hEAG BV1m8u969Ea5; do
  test "$(rg --files temp | rg -c "/${bvid}\\.mp4$")" -eq 1
  test "$(rg --files temp | rg -c "/${bvid}\\.danmaku\\.xml$")" -eq 1
  test "$(rg --files temp | rg -c "/${bvid}\\.danmaku\\.ass$")" -eq 1
done
```

Expected: exactly three source artifacts per BVID.

- [ ] **Step 3: Probe and fully decode video and audio**

For each exact MP4, run `ffprobe` for codec, resolution, frame rate, sample rate and duration, then:

```bash
ffmpeg -v error -xerror -i "$video_path" -map 0:v:0 -f null -
ffmpeg -v error -xerror -i "$video_path" -map 0:a:0 -f null -
```

Expected: both sources are 1920×1080 with audio, durations are close to 21:07 and 21:51, and all four decodes exit 0 with no error output.

### Task 3: Generate stems and one raw ASR per BVID

- [ ] **Step 1: Separate stems from each exact source**

Run once per MP4:

```bash
uv run video2yt-stems "$video_path"
```

Expected: each BVID directory contains non-empty `speech.wav`, `music.wav`, `sfx.wav`, `no_music.wav`, and `.stems_source_meta.json`; durations match the source within one second.

- [ ] **Step 2: Reuse valid canonical ASR or run exactly once**

Inspect `speech.wav.speech2srt.{srt,json}`. If a pair exists and its metadata matches the current `speech.wav`, reuse it. Otherwise run once per BVID:

```bash
set -a
source .env
set +a
uv run video2yt-subtitle "$video_path" --skip-cleanup
```

Expected: no `--force-asr`; each source has one canonical SRT/JSON pair, `cleanup_enabled=false`, SHA recorded, and transcript coverage close to the source tail.

### Task 4: Build source-grounded magnetic-Mech evidence

- [ ] **Step 1: Read every raw text source**

Read both complete canonical SRTs and both XML/ASS danmaku files. Search Simplified and Traditional aliases for 机械／機械、磁力、火花机／火花機、黑暗之赐／黑暗贈禮、双重／雙重、砰砰、海盗／海盜、经济／經濟、阮大师／阮大師、1000、9000 and all visible named cards or trinkets.

Expected: retained assertions record BVID, timestamp, evidence type, and confidence; no claim is accepted from the topic summary alone.

- [ ] **Step 2: Generate overview and targeted frames**

Create full-game contact sheets:

```bash
ffmpeg -y -i "$guo_video" -vf 'fps=1/40,scale=480:-2,tile=6x6' -frames:v 1 output/magnetic_mech_s14/evidence/guo/contact.png
ffmpeg -y -i "$vala_video" -vf 'fps=1/40,scale=480:-2,tile=6x6' -frames:v 1 output/magnetic_mech_s14/evidence/vala/contact.png
```

Then extract full-resolution frames at every core-card hover, Dark Gift/Trinket choice, Magnetic attachment, economy pivot, major stat jump, final board, and result screen.

Expected: every Intro-eligible rule and numeric claim has a readable frame or exact speech timestamp.

- [ ] **Step 3: Resolve current official zhTW cards and trinkets**

Refresh HearthstoneJSON latest zhTW/enUS card data. Match actual on-screen art to exact IDs and verify official art URLs:

```text
https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/${card_id}.png
```

At minimum resolve the report aliases “火花机” and “砰砰”, every material Dark Gift, the Magnetic minions actually attached, and the hero/trinket only when they materially change the mechanism.

Expected: no scan alias enters the Intro until the official zhTW art is downloaded, opened, and readable.

- [ ] **Step 4: Write fixed evidence documents**

`content_understanding.md` must contain:

```markdown
# S14 磁力機械內容理解
## 郭楓荷：BV1xcu26hEAG
## 瓦莉拉：BV1m8u969Ea5
## 實際卡牌與機制表
## 新版本機械的完整成長順序
## 黑暗贈禮磁力路線
## 海盜經濟轉機械路線
## 可見數值與勝負
## Intro 可展示卡牌
## 排除的未證實說法
```

`terms_zhTW.md` must record Card ID, enUS name, official zhTW name, current rule, source timestamp, official URL, and local art filename. `subtitle_context.txt` must remain flat text under 2 KB and include both streamer names, exact official terms, and concrete ASR replacements.

- [ ] **Step 5: Run evidence acceptance checks**

Run:

```bash
test -s output/magnetic_mech_s14/content_understanding.md
test -s output/magnetic_mech_s14/terms_zhTW.md
test -s output/magnetic_mech_s14/subtitle_context.txt
test "$(wc -c < output/magnetic_mech_s14/subtitle_context.txt)" -le 2048
rg -n 'BV1xcu26hEAG|BV1m8u969Ea5|新版本機械的完整成長順序|排除的未證實說法' output/magnetic_mech_s14/content_understanding.md
! rg -n 'T[BB]D|T[OO]DO|待定|必定提供|直接翻倍|稳定破万' output/magnetic_mech_s14/terms_zhTW.md
```

Expected: all sources and sections exist, context is within 2 KB, and no placeholder or unsupported mechanism remains.

### Task 5: Draft the Intro and stop for user confirmation

- [ ] **Step 1: Write `intro_script.txt` from verified evidence only**

Requirements:

- Start exactly with `你敢相信？`.
- Use official Traditional Chinese Battlegrounds terminology.
- Target 45–50 seconds, initially about 220–245 Chinese characters.
- Explain what changed in the new version before showing the large numbers.
- Include the actual new-card, Dark Gift, Trinket, Magnetic, and economy-pivot mechanisms material to both results.
- Use objective, direct, highly assertive wording; avoid anthropomorphism and metaphors.
- Use only confirmed own-board values; identify whether each number is a single Magnetic attachment, final minion, or opponent value.
- End with an evidence-calibrated season-opening strength verdict and immediate-learning CTA.

- [ ] **Step 2: Run textual acceptance checks**

Run:

```bash
test -s output/magnetic_mech_s14/intro_script.txt
python3 -c "from pathlib import Path; s=Path('output/magnetic_mech_s14/intro_script.txt').read_text().strip(); assert s.startswith('你敢相信？'); assert 210 <= len(s) <= 255; print(len(s))"
rg -n '新版本|磁力|趕緊學' output/magnetic_mech_s14/intro_script.txt
! rg -n '酒館|畸變|牌組|套牌|構築|咬一口|起飛|引擎|T[BB]D|T[OO]DO|待定' output/magnetic_mech_s14/intro_script.txt
```

Expected: opening, length, version framing, Magnetic mechanism, urgent ending, and forbidden-language checks pass.

- [ ] **Step 3: Present the review package and stop**

Mark download, raw ASR, evidence, official terms, and Intro complete in `WORKFLOW_NOTES.md`, leaving user approval unchecked. Present both full source URLs, the exact mechanism chains, every number used and what it measures, the complete Intro script, and predicted duration.

Stop here. Do not generate TTS, imagery, body renders, metadata, upload/comment, or cleanup until the user approves or revises the Intro.

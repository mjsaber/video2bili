# S14 仙女龙流 Production Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Current execution boundary — 2026-08-08:** The user approved the design and requested inline execution through the completed Intro script, then a review pause. Do not synthesize TTS, generate backgrounds, burn body videos, upload, comment, or clean caches before that review.

**Goal:** 把郭楓荷与夜吹的两条 S14 龙族实战做成一期以“新赛季新发明！龙族翻身！”为封面卖点的教学视频，并先完成可审核的真实机制证据与 Intro 文案。

**Architecture:** 复用现有 Stage 1–3 缓存：串行下载两条 Bilibili 素材，每个 BVID 只运行一次 raw ASR；随后联合读取语音、弹幕、逐帧画面和最新 HearthstoneJSON zhTW 数据，先建立实际卡牌机制表，再从证据中写 45–50 秒 Intro。用户确认 Intro 后，才进入视觉生成、TTS、正片与上传阶段。

**Tech Stack:** `video2yt-prefetch`, `video2yt-stems`, `video2yt-subtitle`, ffmpeg/ffprobe, HearthstoneJSON `latest` zhTW/enUS data and BGS art, Markdown evidence records.

---

## File map

- Create: `output/fairy_dragon_s14/WORKFLOW_NOTES.md` — 来源、封面文案、授权边界和阶段状态。
- Create: `output/fairy_dragon_s14/content_understanding.md` — 两局逐时间点内容理解、共同机制和终局数值。
- Create: `output/fairy_dragon_s14/terms_zhTW.md` — 实际出现卡牌的官方 ID、繁中名、卡文和官方卡面 URL。
- Create: `output/fairy_dragon_s14/subtitle_context.txt` — 后续字幕清理所需的别称与官方词表，UTF-8 且不超过 2 KB。
- Create: `output/fairy_dragon_s14/intro_script.txt` — 待用户审核的繁体 Intro 文案。
- Create: `output/fairy_dragon_s14/evidence/guo/` and `output/fairy_dragon_s14/evidence/night/` — 只保存用于核验的抽帧图。
- Do not create yet: Intro TTS/SRT/背景/MP4、正片、封面、metadata 或上传产物。
- Do not modify: unrelated dirty worktree files, shipped project outputs, `assets/topic/done_topics.txt`, and existing card assets.

### Task 1: Preflight and initialize the review-bounded project

- [ ] **Step 1: Verify source and workflow inputs**

Run:

```bash
test -s docs/superpowers/specs/2026-08-08-fairy-dragon-s14-production-design.md
rg -n 'BV1ZbM26EE9H|BV1oxut6hEuJ|新赛季新发明|龙族翻身' \
  docs/superpowers/specs/2026-08-08-fairy-dragon-s14-production-design.md \
  output/topics/2026-08-08.md
```

Expected: both BVIDs and the exact approved cover copy occur in the design/topic evidence.

- [ ] **Step 2: Verify tools and secrets without printing secret contents**

Run:

```bash
command -v ffmpeg
command -v ffprobe
uv run which yt-dlp
uv run python -c 'import yt_dlp; print(yt_dlp.version.__version__)'
command -v song-remover
command -v speech2srt
test -s .env
test -s ~/.modal.toml
ffmpeg -hide_banner -filters 2>/dev/null | rg ' subtitles '
```

Expected: all executables resolve, both file checks exit 0, and ffmpeg exposes libass subtitles.

- [ ] **Step 3: Initialize only this project**

Create the project/evidence directories. Create `WORKFLOW_NOTES.md` with both BVIDs, their full URLs, exact cover lines `新赛季新发明！` / `龙族翻身！`, and checkboxes for download, raw ASR, evidence table, official terminology, Intro draft, and user Intro approval. Explicitly record that upload authorization is absent for this project.

Expected: only `output/fairy_dragon_s14/` is initialized; no previous output or cache is removed.

### Task 2: Download both sources serially and validate them

- [ ] **Step 1: Prefetch in the selected order**

Run:

```bash
uv run video2yt-prefetch \
  'https://www.bilibili.com/video/BV1ZbM26EE9H' \
  'https://www.bilibili.com/video/BV1oxut6hEuJ' \
  -o temp/
```

Expected: exit 0; each source produces one MP4, raw XML danmaku, and converted ASS. Downloads remain serial to avoid corrupt Bilibili merges.

- [ ] **Step 2: Resolve exact cache paths and assert non-empty artifacts**

Run:

```bash
for bvid in BV1ZbM26EE9H BV1oxut6hEuJ; do
  test "$(rg --files temp | rg -c "/${bvid}\\.mp4$")" -eq 1
  test "$(rg --files temp | rg -c "/${bvid}\\.danmaku\\.xml$")" -eq 1
  test "$(rg --files temp | rg -c "/${bvid}\\.danmaku\\.ass$")" -eq 1
  rg --files temp | rg "/${bvid}\\.(mp4|danmaku\\.(xml|ass))$"
done
```

Expected: exactly three paths print per BVID and all are non-empty.

- [ ] **Step 3: Verify streams, duration and full decode**

Run:

```bash
for bvid in BV1ZbM26EE9H BV1oxut6hEuJ; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  ffprobe -v error \
    -show_entries stream=codec_type,codec_name,width,height,r_frame_rate,sample_rate \
    -show_entries format=duration -of json "$video_path"
  ffmpeg -v error -xerror -i "$video_path" -map 0:v:0 -f null -
  ffmpeg -v error -xerror -i "$video_path" -map 0:a:0 -f null -
done
```

Expected: both are plausibly near 21 minutes, have 1080p video and audio, and both video/audio full decodes exit 0 without error output.

### Task 3: Generate stems and one raw ASR per source

- [ ] **Step 1: Separate stems**

Run:

```bash
for bvid in BV1ZbM26EE9H BV1oxut6hEuJ; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  uv run video2yt-stems "$video_path"
done
```

Expected: each BVID cache contains non-empty `speech.wav`, `music.wav`, `sfx.wav`, `no_music.wav`, and `.stems_source_meta.json`; each stem duration matches its source within one second.

- [ ] **Step 2: Confirm no canonical raw transcript exists before ASR**

Run:

```bash
for bvid in BV1ZbM26EE9H BV1oxut6hEuJ; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  cache_dir="$(dirname "$video_path")/$bvid"
  test ! -e "$cache_dir/speech.wav.speech2srt.srt"
  test ! -e "$cache_dir/speech.wav.speech2srt.json"
done
```

Expected: all assertions pass. If a canonical pair already exists, verify it belongs to the exact current source instead of rerunning ASR.

- [ ] **Step 3: Run raw ASR exactly once per BVID**

Run:

```bash
set -a
source .env
set +a
for bvid in BV1ZbM26EE9H BV1oxut6hEuJ; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  uv run video2yt-subtitle "$video_path" --skip-cleanup
done
```

Expected: two invocations total, no `--force-asr`, and each cache now contains exactly one non-empty canonical SRT/JSON pair with `cleanup_enabled=false`.

- [ ] **Step 4: Verify transcript coverage**

Run:

```bash
for bvid in BV1ZbM26EE9H BV1oxut6hEuJ; do
  video_path=$(rg --files temp | rg "/${bvid}\\.mp4$")
  cache_dir="$(dirname "$video_path")/$bvid"
  ffprobe -v error -show_entries format=duration -of default=nw=1:nk=1 "$video_path"
  tail -16 "$cache_dir/speech.wav.speech2srt.srt"
  jq '{cleanup_enabled,cleanup_applied,canonical_srt_sha256}' "$cache_dir/speech.wav.speech2srt.json"
done
```

Expected: each transcript reaches late-game speech near the source tail; JSON states cleanup was disabled/not applied and records the canonical hash.

### Task 4: Build source-grounded content understanding

- [ ] **Step 1: Extract searchable speech and danmaku evidence**

Read both canonical raw SRTs, both danmaku XMLs and both ASS files. Search Simplified/Traditional aliases for dragon, fairy dragon, poetic/bard dragon, windfury, Balinda, whistle, bounty, discover, battlecry, deathrattle, chef, pirate economy, triple, attack, and visible late-game values. Every retained assertion must record BVID and timestamp.

Expected: a working evidence list exists for setup, each actual core card, each trigger, each pivot, and terminal board values in both games.

- [ ] **Step 2: Create overview and targeted full-resolution frames**

Run:

```bash
guo_video=$(rg --files temp | rg '/BV1ZbM26EE9H\.mp4$')
night_video=$(rg --files temp | rg '/BV1oxut6hEuJ\.mp4$')
ffmpeg -y -i "$guo_video" -vf 'fps=1/45,scale=480:-2,tile=6x5' -frames:v 1 output/fairy_dragon_s14/evidence/guo/contact.png
ffmpeg -y -i "$night_video" -vf 'fps=1/45,scale=480:-2,tile=6x5' -frames:v 1 output/fairy_dragon_s14/evidence/night/contact.png
```

Then extract individual 1920×1080 PNGs at every evidence timestamp showing a core card hover, rule text, trigger animation, board pivot or final number.

Expected: the contact sheets cover both full games, while targeted frames make every Intro-eligible card and numerical claim readable.

- [ ] **Step 3: Resolve official zhTW cards from the latest data**

Download/read the latest HearthstoneJSON enUS and zhTW card data. Match actual on-screen art/text to official IDs, then verify each matched card using both locale records and its BGS art URL:

```text
https://art.hearthstonejson.com/v1/bgs/latest/zhTW/512x/${card_id}.png
```

Do not promote scanner names such as `仙女龙`, `诗心龙`, `巴林达`, `哨子` or `悬赏令` to official names without this match. Record any alias that cannot be resolved under “excluded/unverified.”

Expected: every card intended for the Intro has an actual video timestamp, exact official ID, zhTW name, current rule text and readable official card face.

- [ ] **Step 4: Write fixed evidence documents**

Create `content_understanding.md` with these sections:

```markdown
# S14 仙女龍流內容理解
## 郭楓荷：BV1ZbM26EE9H
## 夜吹：BV1oxut6hEuJ
## 實際卡牌與機制表
| Card ID | 官方繁中名 | 規則機制 | 實戰作用 | 來源 | 時間點 | 畫面 / speech / 彈幕證據 |
|---|---|---|---|---|---|---|
## 完整觸發順序
## 兩局啟動與轉型差異
## 可見終局數值
## Intro 可展示卡牌
## 排除的未證實說法
```

Create `terms_zhTW.md` with Card ID, enUS name, official zhTW name, exact current zhTW rule, local image path or planned stable filename, official BGS image URL, and source timestamp. Create `subtitle_context.txt` with the two streamer names, official terms and concrete ASR alias mappings.

- [ ] **Step 5: Run evidence acceptance checks**

Run:

```bash
test -s output/fairy_dragon_s14/content_understanding.md
test -s output/fairy_dragon_s14/terms_zhTW.md
test -s output/fairy_dragon_s14/subtitle_context.txt
test "$(wc -c < output/fairy_dragon_s14/subtitle_context.txt)" -le 2048
rg -n 'BV1ZbM26EE9H|BV1oxut6hEuJ|完整觸發順序|可見終局數值|排除的未證實說法' output/fairy_dragon_s14/content_understanding.md
! rg -n 'T[BB]D|T[OO]DO|待定|自動觸發|無限|千攻' output/fairy_dragon_s14/terms_zhTW.md
```

Expected: all fixed sections and both sources exist, the term context fits within 2 KB, and official rule records contain no placeholder or unsupported result language. A verified thousand-attack result belongs in the timestamped content evidence, not static card rules.

### Task 5: Draft the Intro and stop for user confirmation

- [ ] **Step 1: Write `intro_script.txt` from verified evidence only**

Requirements:

- Start exactly with `你敢相信？`.
- Use official Traditional Chinese BG terminology; use `旅店`, `隨從`, `陣容` and exact official card names.
- Target a predicted 45–50 seconds, initially about 220–245 Chinese characters.
- Lead with the verified final strength and new-version claim, then explain every material new-card mechanism in its real trigger order.
- Explain both the core growth mechanism and the economic/transition mechanism; do not reduce the topic to one vague “economy engine.”
- Distinguish Battlecry, Deathrattle, Discover, combat triggers, Tavern effects and persistent scaling whenever they differ.
- Use objective, direct and strongly exaggerated wording; avoid anthropomorphism and metaphors such as `咬一口`, `起飛`, `吃滿`, or `引擎`.
- Mention `千攻` only if Task 4 proves an own-board minion reaches at least 1000 attack.
- End with an evidence-calibrated urgent line in the established style: `這套絕對是賽季初期斷層 T0，趕緊學！` only if supported; otherwise use `這是賽季初期最值得學的龍族新體系，趕緊學！`.
- Do not include the thumbnail copy inside narration merely to repeat it.

- [ ] **Step 2: Run textual acceptance checks**

Run:

```bash
test -s output/fairy_dragon_s14/intro_script.txt
python -c "from pathlib import Path; s=Path('output/fairy_dragon_s14/intro_script.txt').read_text().strip(); assert s.startswith('你敢相信？'); assert 210 <= len(s) <= 255; print(len(s))"
rg -n '新版本|龍|旅店|趕緊學' output/fairy_dragon_s14/intro_script.txt
! rg -n '酒館|畸變|牌組|套牌|構築|咬一口|起飛|吃滿|引擎|T[BB]D|T[OO]DO|待定' output/fairy_dragon_s14/intro_script.txt
```

Expected: opening, length, version framing, dragon mechanism and urgent ending checks pass; forbidden language produces no matches.

- [ ] **Step 3: Record the boundary and present review package**

Mark download, raw ASR, evidence table, official terminology and Intro draft complete in `WORKFLOW_NOTES.md`, leaving user Intro approval unchecked. Present:

1. both source URLs;
2. exact official core-card mechanism chain;
3. the two games' complementary roles;
4. every verified result number used in the script;
5. the complete Intro script and predicted duration.

Stop here. Do not generate TTS, images, Intro video, body videos or external uploads until the user approves or revises the script.

### Task 6: Post-Intro continuation boundary

- [ ] **Step 1: Resume only after explicit Intro approval**

After approval, write a second execution plan covering TTS timing, official card downloads, ImageGen background, dynamic Intro, cleaned subtitles, music mix, burn, CTA, merge, thumbnail, metadata, final media review and optional upload. Public upload still requires a separate explicit authorization for this project.
